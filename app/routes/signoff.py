"""Signoff actions surfaced from the workforce dashboard.

Routes:
- ``POST /workforce/periods/<period_id>/signoff/send`` — create a
  ``TimesheetSignoffRequest`` and dispatch it via the configured
  e-signature connector. Cancels any active row for the same scope
  first (resend-after-decline pattern).
- ``GET  /workforce/signoffs/<request_id>/signed-pdf`` — stream the
  locally-stored signed PDF.
- ``GET  /workforce/signoffs/<request_id>/coc`` — stream the locally-
  stored Certificate of Completion.
- ``POST /workforce/signoffs/<request_id>/cancel`` — cancel an active
  signoff.

Layer 2 (the connector + service) does the heavy lifting. These routes
are thin glue + permission/ownership checks."""

from __future__ import annotations

import logging
from datetime import date as _date
from pathlib import Path

from flask import Blueprint, abort, flash, redirect, request, send_file, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from app import db
from app.integrations.esignature.base import ESignatureError
from app.models.client import Client
from app.models.esignature_request import ESignatureRequest
from app.models.timesheet_period import TimesheetPeriod
from app.models.timesheet_signoff_request import (
    TimesheetSignoffRequest,
    TimesheetSignoffStatus,
)
from app.models.timesheet_signoff_template import TimesheetSignoffTemplate
from app.services.timesheet_signoff_service import TimesheetSignoffService

signoff_bp = Blueprint("signoff", __name__)
_log = logging.getLogger(__name__)


def _parse_date(value: str | None, fallback: _date | None) -> _date | None:
    if not value:
        return fallback
    try:
        return _date.fromisoformat(value)
    except ValueError:
        return fallback


def _can_act_on_period(period: TimesheetPeriod) -> bool:
    if current_user.is_admin:
        return True
    if period.user_id == current_user.id:
        return True
    return False


@signoff_bp.post("/workforce/periods/<int:period_id>/signoff/send")
@login_required
def send_signoff(period_id: int):
    period = TimesheetPeriod.query.get_or_404(period_id)
    if not _can_act_on_period(period):
        abort(403)

    form = request.form
    client_id = form.get("client_id")
    signer_email = (form.get("signer_email") or "").strip()
    signer_name = (form.get("signer_name") or "").strip() or None
    template_id = form.get("template_id")

    if not client_id or not signer_email:
        flash(_("Client and signer email are required"), "error")
        return redirect(url_for("workforce.dashboard"))

    try:
        client_id_int = int(client_id)
    except (TypeError, ValueError):
        flash(_("Invalid client"), "error")
        return redirect(url_for("workforce.dashboard"))

    client = Client.query.get(client_id_int)
    if not client:
        flash(_("Client not found"), "error")
        return redirect(url_for("workforce.dashboard"))

    template = None
    if template_id:
        try:
            template = TimesheetSignoffTemplate.query.get(int(template_id))
        except (TypeError, ValueError):
            template = None
    if not template or template.archived_at:
        template = TimesheetSignoffService.resolve_template_for_client(client)
    if not template:
        flash(
            _(
                "No signoff template is configured. Create one in "
                "Admin → Signoff Templates first."
            ),
            "error",
        )
        return redirect(url_for("workforce.dashboard"))

    TimesheetSignoffService.cancel_active_signoff(
        engineer_user_id=period.user_id,
        client_id=client_id_int,
        period_start=period.period_start,
        period_end=period.period_end,
    )

    signoff = TimesheetSignoffRequest(
        timesheet_period_id=period.id,
        client_id=client_id_int,
        engineer_user_id=period.user_id,
        period_start=period.period_start,
        period_end=period.period_end,
        signer_email=signer_email,
        signer_name=signer_name,
        template_id=template.id,
        status=TimesheetSignoffStatus.DRAFT,
        created_by=current_user.id,
    )
    db.session.add(signoff)
    db.session.flush()

    try:
        TimesheetSignoffService.send_for_signoff(signoff)
    except ESignatureError as exc:
        db.session.rollback()
        flash(
            _("Could not send for signoff: %(error)s", error=str(exc)),
            "error",
        )
        return redirect(url_for("workforce.dashboard"))
    except Exception as exc:
        db.session.rollback()
        _log.exception("Unexpected error sending signoff for period %s", period_id)
        flash(
            _("Could not send for signoff: %(error)s", error=str(exc)),
            "error",
        )
        return redirect(url_for("workforce.dashboard"))

    flash(
        _(
            "Sent timesheet for approval to %(email)s",
            email=signer_email,
        ),
        "success",
    )
    return redirect(url_for("workforce.dashboard"))


@signoff_bp.post("/workforce/signoffs/<int:request_id>/cancel")
@login_required
def cancel_signoff(request_id: int):
    signoff = TimesheetSignoffRequest.query.get_or_404(request_id)
    period = TimesheetPeriod.query.get(signoff.timesheet_period_id)
    if period and not _can_act_on_period(period):
        abort(403)
    if signoff.cancelled_at is not None:
        flash(_("Already cancelled"), "info")
        return redirect(url_for("workforce.dashboard"))

    TimesheetSignoffService.cancel_active_signoff(
        engineer_user_id=signoff.engineer_user_id,
        client_id=signoff.client_id,
        period_start=signoff.period_start,
        period_end=signoff.period_end,
    )
    flash(_("Signoff cancelled"), "success")
    return redirect(url_for("workforce.dashboard"))


@signoff_bp.get("/workforce/signoffs/<int:request_id>/signed-pdf")
@login_required
def download_signed_pdf(request_id: int):
    signoff = TimesheetSignoffRequest.query.get_or_404(request_id)
    period = TimesheetPeriod.query.get(signoff.timesheet_period_id)
    if period and not _can_act_on_period(period):
        abort(403)

    esig = (
        ESignatureRequest.query.get(signoff.esignature_request_id)
        if signoff.esignature_request_id
        else None
    )
    if not esig or not esig.signed_document_path:
        abort(404)
    path = Path(esig.signed_document_path)
    if not path.is_file():
        abort(404)
    return send_file(
        path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=(
            f"timesheet-{signoff.period_start}-{signoff.period_end}-signed.pdf"
        ),
    )


@signoff_bp.get("/workforce/signoffs/<int:request_id>/coc")
@login_required
def download_coc(request_id: int):
    signoff = TimesheetSignoffRequest.query.get_or_404(request_id)
    period = TimesheetPeriod.query.get(signoff.timesheet_period_id)
    if period and not _can_act_on_period(period):
        abort(403)

    esig = (
        ESignatureRequest.query.get(signoff.esignature_request_id)
        if signoff.esignature_request_id
        else None
    )
    if not esig or not esig.audit_certificate_path:
        abort(404)
    path = Path(esig.audit_certificate_path)
    if not path.is_file():
        abort(404)
    return send_file(
        path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=(
            f"timesheet-{signoff.period_start}-{signoff.period_end}-coc.pdf"
        ),
    )
