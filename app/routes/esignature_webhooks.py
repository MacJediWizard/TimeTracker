"""Inbound webhook handler for e-signature providers (DocuSeal etc.).

Mounted at ``POST /webhooks/esignature/<integration_id>``. The
integration_id is the path component used to route the request to the
right configured integration; **authentication is done via the
connector's HMAC verification**, not the URL. The path is intentionally
not secret.

Flow:
1. Look up ``Integration`` by id; 404 if missing or inactive.
2. Build the connector via ``IntegrationService.get_connector(...)``.
3. Read the raw request body (do NOT json-decode-then-reencode — that
   would break HMAC).
4. ``connector.verify_webhook(raw_body, headers)`` — constant-time
   HMAC check with replay-protection timestamp window; fail-closed on
   missing secret. Returns 401 on rejection.
5. ``connector.parse_webhook(raw_body)`` — normalises provider payload
   into ``ESignatureWebhookEvent``.
6. Look up the ``ESignatureRequest`` by ``(external_id, integration_id)``.
   Unknown external_id => 200 (treat as already-archived / not-ours).
7. Skip if event is older than our local state's last touch, or if
   the local record is already in a terminal state (idempotency).
8. ``TimesheetSignoffService.apply_webhook_event(esig_req, event)``
   handles the actual state mutation, artefact download, and
   status-mirror onto ``TimesheetSignoffRequest``.

Always returns 2xx after verification succeeds so the provider does
not retry. 4xx on signature failure means the provider WILL retry —
that's the desired behaviour for transient HMAC misconfigurations."""

import logging
from datetime import timezone

from flask import Blueprint, abort, request

from app import csrf
from app.integrations.esignature.base import ESignatureError
from app.models.esignature_request import ESignatureRequest, ESignatureStatus
from app.models.integration import Integration

esignature_webhooks_bp = Blueprint("esignature_webhooks", __name__)
_log = logging.getLogger(__name__)


_TERMINAL_STATUSES = {
    ESignatureStatus.SIGNED,
    ESignatureStatus.DECLINED,
    ESignatureStatus.EXPIRED,
    ESignatureStatus.CANCELLED,
    ESignatureStatus.FAILED,
}


def _as_utc(dt):
    """Normalise a datetime to timezone-aware UTC for safe comparison.

    Connector-parsed event timestamps are timezone-aware (see
    ``docuseal._parse_iso8601``), while our persisted ``updated_at`` columns
    are naive UTC (``datetime.utcnow`` default). Comparing the two directly
    raises ``TypeError`` — normalise both sides here first.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _last_event_at(esig_req):
    """Return the occurred_at of the most recent provider event applied to this
    request, or None if none has landed yet.

    ``apply_webhook_event`` stamps ``viewed_at``/``signed_at``/``declined_at``
    (and ``sent_at`` at send time) with the provider event's ``occurred_at``, so
    the greatest of these is the correct reference for the out-of-order guard.
    Comparing an incoming event against ``updated_at`` instead would use OUR
    processing time — a delayed/retried earlier event bumps ``updated_at`` to
    "now" and would then wrongly reject a genuine later transition.
    """
    stamps = [esig_req.sent_at, esig_req.viewed_at, esig_req.signed_at, esig_req.declined_at]
    stamps = [_as_utc(s) for s in stamps if s is not None]
    return max(stamps) if stamps else None


@esignature_webhooks_bp.post("/webhooks/esignature/<int:integration_id>")
@csrf.exempt
def esignature_webhook(integration_id: int):
    from app.services.integration_service import IntegrationService
    from app.services.timesheet_signoff_service import TimesheetSignoffService

    integration = Integration.query.get(integration_id)
    if not integration or not integration.is_active:
        abort(404)

    connector = IntegrationService.get_connector(integration)
    if not connector:
        _log.error(
            "Webhook received for integration %s but no connector registered",
            integration_id,
        )
        abort(404)

    raw_body = request.get_data()
    headers = dict(request.headers)

    if not connector.verify_webhook(raw_body, headers):
        _log.warning(
            "Webhook signature verification failed for integration %s",
            integration_id,
        )
        abort(401)

    try:
        event = connector.parse_webhook(raw_body)
    except ESignatureError as exc:
        _log.info("Unhandled webhook event for integration %s: %s", integration_id, exc)
        return "", 200
    except Exception:
        _log.exception("Failed to parse webhook payload for integration %s", integration_id)
        return "", 200

    if not event.external_id:
        _log.warning("Webhook event missing external_id; integration %s", integration_id)
        return "", 200

    esig_req = ESignatureRequest.query.filter_by(integration_id=integration_id, external_id=event.external_id).first()
    if not esig_req:
        _log.info(
            "Webhook references unknown external_id=%s on integration %s; skipping",
            event.external_id,
            integration_id,
        )
        return "", 200

    if esig_req.status in _TERMINAL_STATUSES and event.status == esig_req.status:
        return "", 200

    last_event_at = _last_event_at(esig_req)
    if event.occurred_at and last_event_at and _as_utc(event.occurred_at) < last_event_at:
        _log.info(
            "Webhook event is older than the last applied provider event (esig %s); skipping",
            esig_req.id,
        )
        return "", 200

    TimesheetSignoffService.apply_webhook_event(esig_req, event)
    return "", 200
