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

from flask import Blueprint, abort, request

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


@esignature_webhooks_bp.post("/webhooks/esignature/<int:integration_id>")
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

    if event.occurred_at and esig_req.updated_at and event.occurred_at < esig_req.updated_at:
        _log.info(
            "Webhook event is older than local state (esig %s); skipping",
            esig_req.id,
        )
        return "", 200

    TimesheetSignoffService.apply_webhook_event(esig_req, event)
    return "", 200
