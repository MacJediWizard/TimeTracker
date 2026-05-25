"""TimesheetSignoffService — orchestration for the per-engineer-per-client
signoff lifecycle.

Sits between the workforce/admin routes (layer 7) and the e-signature
integration (layer 1). Responsible for:

- Resolving which template applies to a (client, request) pair
- Mapping ORM rows to the ``SignoffData`` / ``SignoffTemplate`` dataclasses
  the renderer consumes
- Calling the connector to dispatch a submission
- Persisting the resulting ``ESignatureRequest`` and linking it back to
  the ``TimesheetSignoffRequest``
- Applying inbound webhook events to local state (status mirror,
  download signed PDF + Certificate of Completion, hash for tamper check)
- Reconciling stuck ``sent``-state requests via the cron
- Cancelling an active signoff so a resend can create a new row (the
  partial unique index on ``timesheet_signoff_requests`` only counts
  non-cancelled rows)"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import current_app
from sqlalchemy import or_

from app import db
from app.integrations.esignature.base import ESignatureError, ESignatureWebhookEvent
from app.models.branding_asset import BrandingAsset
from app.models.client import Client
from app.models.esignature_request import ESignatureRequest, ESignatureStatus
from app.models.integration import Integration
from app.models.project import Project
from app.models.time_entry import TimeEntry
from app.models.timesheet_signoff_request import TimesheetSignoffRequest, TimesheetSignoffStatus
from app.models.timesheet_signoff_template import TimesheetSignoffTemplate
from app.models.user import User
from app.utils.timesheet_signoff_pdf import SignatureAreas, SignoffData, SignoffTemplate, build_signoff_pdf

_TARGET_TYPE = "TimesheetSignoffRequest"

_ESIG_TO_LOCAL_STATUS = {
    ESignatureStatus.VIEWED: TimesheetSignoffStatus.VIEWED,
    ESignatureStatus.SIGNED: TimesheetSignoffStatus.SIGNED,
    ESignatureStatus.DECLINED: TimesheetSignoffStatus.DECLINED,
    ESignatureStatus.EXPIRED: TimesheetSignoffStatus.EXPIRED,
    ESignatureStatus.CANCELLED: TimesheetSignoffStatus.CANCELLED,
}


class TimesheetSignoffService:
    @classmethod
    def get_esignature_connector(cls):
        """Return a configured + healthy e-signature connector, or ``None``
        if no e-signature integration is active. The feature UI uses this
        check to gate the "Send for approval" action and surface a
        Configure-DocuSeal prompt when the result is ``None``."""
        integration = Integration.query.filter_by(provider="docuseal", is_active=True).first()
        if not integration:
            return None
        from app.services.integration_service import IntegrationService

        connector = IntegrationService.get_connector(integration)
        if not connector:
            return None
        try:
            if not connector.test_connection():
                return None
        except Exception:
            current_app.logger.exception("DocuSeal test_connection raised; treating as disconnected")
            return None
        return connector

    @classmethod
    def _connector_for_integration(cls, integration_id: int):
        integration = Integration.query.get(integration_id)
        if not integration:
            return None
        from app.services.integration_service import IntegrationService

        return IntegrationService.get_connector(integration)

    @classmethod
    def resolve_template_for_client(cls, client: Client) -> TimesheetSignoffTemplate | None:
        if client and client.signoff_template_id:
            template = TimesheetSignoffTemplate.query.get(client.signoff_template_id)
            if template and not template.archived_at:
                return template
        return (
            TimesheetSignoffTemplate.query.filter_by(is_default=True, archived_at=None)
            .order_by(TimesheetSignoffTemplate.id.asc())
            .first()
        )

    @classmethod
    def build_template_from_orm(cls, orm_template: TimesheetSignoffTemplate) -> SignoffTemplate:
        def asset_path(asset_id: int | None) -> str | None:
            if not asset_id:
                return None
            asset = BrandingAsset.query.get(asset_id)
            if not asset or asset.archived_at:
                return None
            return asset.file_path

        return SignoffTemplate(
            intro_markdown=orm_template.intro_markdown or "",
            terms_markdown=orm_template.terms_markdown or "",
            columns_to_show=list(orm_template.columns_to_show or []),
            show_billable=orm_template.show_billable,
            show_daily_totals=orm_template.show_daily_totals,
            signature_block_label=orm_template.signature_block_label,
            primary_color_hex=orm_template.primary_color_hex,
            accent_color_hex=orm_template.accent_color_hex,
            logo_path=asset_path(orm_template.logo_asset_id),
            logo_position=orm_template.logo_position,
            logo_max_height_pt=orm_template.logo_max_height_pt,
            logo_opacity=orm_template.logo_opacity,
            body_font_name=orm_template.body_font_name,
            body_font_regular_path=asset_path(orm_template.body_font_regular_asset_id),
            body_font_bold_path=asset_path(orm_template.body_font_bold_asset_id),
            body_font_italic_path=asset_path(orm_template.body_font_italic_asset_id),
            body_font_bold_italic_path=asset_path(orm_template.body_font_bold_italic_asset_id),
            display_font_name=orm_template.display_font_name,
            display_font_regular_path=asset_path(orm_template.display_font_regular_asset_id),
            display_font_bold_path=asset_path(orm_template.display_font_bold_asset_id),
        )

    @classmethod
    def query_entries_for_signoff(
        cls,
        *,
        engineer_user_id: int,
        client_id: int,
        period_start,
        period_end,
    ) -> list[TimeEntry]:
        period_start_dt = datetime.combine(period_start, datetime.min.time())
        period_end_dt = datetime.combine(period_end, datetime.max.time())
        return (
            TimeEntry.query.outerjoin(Project, TimeEntry.project_id == Project.id)
            .filter(
                TimeEntry.user_id == engineer_user_id,
                TimeEntry.start_time >= period_start_dt,
                TimeEntry.start_time <= period_end_dt,
                or_(
                    TimeEntry.client_id == client_id,
                    Project.client_id == client_id,
                ),
            )
            .order_by(TimeEntry.start_time.asc())
            .all()
        )

    @classmethod
    def build_data_from_request(cls, request: TimesheetSignoffRequest) -> SignoffData:
        entries = cls.query_entries_for_signoff(
            engineer_user_id=request.engineer_user_id,
            client_id=request.client_id,
            period_start=request.period_start,
            period_end=request.period_end,
        )
        client = Client.query.get(request.client_id)
        engineer = User.query.get(request.engineer_user_id)
        engineer_display = (engineer.full_name if engineer and engineer.full_name else None) or (
            engineer.username if engineer else ""
        )
        my_company = cls._resolve_company_name()
        project_names = [e.project.name for e in entries if e.project]
        engagement = max(set(project_names), key=project_names.count) if project_names else ""
        return SignoffData(
            my_company_name=my_company,
            client_name=client.name if client else "",
            engineer_name=engineer_display,
            engagement_name=engagement,
            period_start=request.period_start,
            period_end=request.period_end,
            entries=entries,
        )

    @staticmethod
    def _resolve_company_name() -> str:
        from app.models.settings import Settings

        settings = Settings.query.first()
        for attr in ("company_name", "organization_name", "site_name"):
            value = getattr(settings, attr, None) if settings else None
            if value:
                return value
        return "Company"

    @classmethod
    def send_for_signoff(cls, request: TimesheetSignoffRequest) -> ESignatureRequest:
        """Build the PDF and dispatch via the configured e-signature
        connector. Persists ``ESignatureRequest`` and updates the
        ``TimesheetSignoffRequest`` to ``sent``."""
        connector = cls.get_esignature_connector()
        if not connector:
            raise ESignatureError("No e-signature integration is connected")

        template = TimesheetSignoffTemplate.query.get(request.template_id)
        if not template:
            raise ESignatureError(f"Signoff template {request.template_id} not found")

        data = cls.build_data_from_request(request)
        signoff_template = cls.build_template_from_orm(template)
        pdf_bytes, sig_areas = build_signoff_pdf(data, signoff_template)

        request.total_hours_seconds = sum(getattr(e, "duration_seconds", 0) or 0 for e in data.entries)

        signature_fields = cls._signature_fields_from_areas(sig_areas)
        subject = (
            f"Timesheet — {data.engineer_name} — {data.client_name} — "
            f"{request.period_start} to {request.period_end}"
        )

        send_result = connector.send_for_signature(
            document_pdf=pdf_bytes,
            recipient_email=request.signer_email,
            recipient_name=request.signer_name or request.signer_email,
            subject=subject,
            external_id=str(request.id),
            signature_fields=signature_fields,
        )

        esig_req = ESignatureRequest(
            integration_id=connector.integration.id,
            target_type=_TARGET_TYPE,
            target_id=str(request.id),
            external_id=send_result.external_id,
            status=ESignatureStatus.SENT,
            provider_url=send_result.signer_url,
            sent_at=send_result.sent_at,
        )
        db.session.add(esig_req)
        db.session.flush()

        request.esignature_request_id = esig_req.id
        request.status = TimesheetSignoffStatus.SENT
        request.sent_at = send_result.sent_at
        db.session.commit()
        return esig_req

    @staticmethod
    def _signature_fields_from_areas(sig_areas: SignatureAreas) -> list[dict]:
        page = sig_areas.page_index

        def field(name: str, kind: str, area: tuple[float, float, float, float]) -> dict:
            return {
                "name": name,
                "type": kind,
                "role": "Client",
                "page": page,
                "x": area[0],
                "y": area[1],
                "w": area[2],
                "h": area[3],
            }

        return [
            field("Signature", "signature", sig_areas.signature),
            field("Date", "date", sig_areas.date),
            field("Name", "text", sig_areas.name),
            field("Title", "text", sig_areas.title),
        ]

    @classmethod
    def apply_webhook_event(
        cls,
        esig_req: ESignatureRequest,
        event: ESignatureWebhookEvent,
    ) -> None:
        """Apply a normalised webhook event to local state. Mirrors the
        status onto the parent ``TimesheetSignoffRequest`` and triggers
        artefact capture on signed events."""
        esig_req.status = event.status
        if event.status == ESignatureStatus.VIEWED:
            esig_req.viewed_at = event.occurred_at
        elif event.status == ESignatureStatus.SIGNED:
            esig_req.signed_at = event.occurred_at
        elif event.status == ESignatureStatus.DECLINED:
            esig_req.declined_at = event.occurred_at
            esig_req.decline_reason = event.decline_reason

        if event.status == ESignatureStatus.SIGNED:
            cls._capture_signed_artefacts(esig_req)

        if esig_req.target_type == _TARGET_TYPE:
            try:
                local_id = int(esig_req.target_id)
            except (TypeError, ValueError):
                local_id = None
            if local_id is not None:
                local = TimesheetSignoffRequest.query.get(local_id)
                if local:
                    local_status = _ESIG_TO_LOCAL_STATUS.get(event.status)
                    if local_status:
                        local.status = local_status
                    if event.status == ESignatureStatus.SIGNED:
                        local.signed_at = event.occurred_at

        db.session.commit()

    @classmethod
    def _capture_signed_artefacts(cls, esig_req: ESignatureRequest) -> None:
        connector = cls._connector_for_integration(esig_req.integration_id)
        if not connector:
            current_app.logger.error(
                "Cannot capture artefacts; connector for integration %s missing",
                esig_req.integration_id,
            )
            return

        upload_root = Path(current_app.config.get("UPLOAD_FOLDER", "/data/uploads"))
        esig_dir = upload_root / "esignatures" / str(esig_req.id)
        esig_dir.mkdir(parents=True, exist_ok=True)

        try:
            signed_pdf = connector.download_signed_document(esig_req.external_id)
            signed_path = esig_dir / "signed.pdf"
            signed_path.write_bytes(signed_pdf)
            esig_req.signed_document_path = str(signed_path)
            esig_req.document_hash = hashlib.sha256(signed_pdf).hexdigest()
        except Exception:
            current_app.logger.exception(
                "Failed to download signed PDF for esignature_request %s",
                esig_req.id,
            )

        try:
            coc = connector.download_audit_certificate(esig_req.external_id)
            if coc:
                coc_path = esig_dir / "audit_certificate.pdf"
                coc_path.write_bytes(coc)
                esig_req.audit_certificate_path = str(coc_path)
        except Exception:
            current_app.logger.exception(
                "Failed to download audit certificate for esignature_request %s",
                esig_req.id,
            )

    @classmethod
    def reconcile_stuck_requests(cls, *, limit: int = 100) -> int:
        """Cron entry point. Fetch any ``ESignatureRequest`` rows in a
        non-terminal state that haven't seen activity in 5+ minutes and
        re-fetch authoritative status from the provider. Returns the
        number of requests touched."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        stuck = (
            ESignatureRequest.query.filter(
                ESignatureRequest.status.in_([ESignatureStatus.SENT, ESignatureStatus.VIEWED]),
                ESignatureRequest.sent_at < cutoff,
                ESignatureRequest.external_id.isnot(None),
            )
            .limit(limit)
            .all()
        )

        touched = 0
        for esig_req in stuck:
            try:
                connector = cls._connector_for_integration(esig_req.integration_id)
                if not connector:
                    continue
                current_status = connector.get_status(esig_req.external_id)
                if current_status != esig_req.status:
                    event = ESignatureWebhookEvent(
                        external_id=esig_req.external_id,
                        status=current_status,
                        occurred_at=datetime.now(timezone.utc),
                    )
                    cls.apply_webhook_event(esig_req, event)
                    touched += 1
            except Exception:
                current_app.logger.exception("Reconcile failed for esignature_request %s", esig_req.id)
        return touched

    @classmethod
    def cancel_active_signoff(
        cls,
        *,
        engineer_user_id: int,
        client_id: int,
        period_start,
        period_end,
    ) -> TimesheetSignoffRequest | None:
        """Mark the active (non-cancelled) signoff for this scope as
        cancelled and call the provider's cancel/archive endpoint. Lets
        a fresh ``TimesheetSignoffRequest`` be inserted for the same
        scope (the partial unique index only counts non-cancelled rows).
        Returns the cancelled request, or ``None`` if no active one
        existed."""
        active = TimesheetSignoffRequest.query.filter_by(
            engineer_user_id=engineer_user_id,
            client_id=client_id,
            period_start=period_start,
            period_end=period_end,
            cancelled_at=None,
        ).first()
        if not active:
            return None

        if active.esignature_request_id:
            esig = ESignatureRequest.query.get(active.esignature_request_id)
            if esig and esig.external_id and not esig.is_terminal:
                connector = cls._connector_for_integration(esig.integration_id)
                if connector:
                    try:
                        connector.cancel(esig.external_id)
                    except Exception:
                        current_app.logger.exception(
                            "Failed to cancel provider submission %s",
                            esig.external_id,
                        )
                esig.status = ESignatureStatus.CANCELLED

        active.cancelled_at = datetime.now(timezone.utc)
        active.status = TimesheetSignoffStatus.CANCELLED
        db.session.commit()
        return active
