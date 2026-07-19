"""Tests for ``TimesheetSignoffService.reconcile_stuck_requests`` — the
function the 15-minute cron calls. We test the function directly so the
scheduler is out of scope (the cron-trigger registration in
``app/utils/scheduled_tasks.py`` is just a thin wrapper)."""

import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import db
from app.integrations.esignature.base import ESignatureWebhookEvent
from app.models.esignature_request import ESignatureRequest, ESignatureStatus
from app.models.integration import Integration, IntegrationCredential
from app.services.timesheet_signoff_service import TimesheetSignoffService


@pytest.fixture
def recon_setup(app):
    with app.app_context():
        integration = Integration(name="DocuSeal", provider="docuseal", is_global=True, is_active=True)
        db.session.add(integration)
        db.session.flush()
        cred = IntegrationCredential(
            integration_id=integration.id,
            extra_data={
                "DOCUSEAL_BASE_URL": "https://docuseal.example.com",
                "DOCUSEAL_API_KEY": "k",
                "DOCUSEAL_WEBHOOK_SECRET": "whsec_x",
            },
        )
        db.session.add(cred)
        db.session.commit()
        return integration.id


def _stuck_esig(
    integration_id: int, *, external_id: str, status: ESignatureStatus, age_minutes: int
) -> ESignatureRequest:
    """Insert an ESignatureRequest whose sent_at is `age_minutes` ago."""
    sent_at = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    esig = ESignatureRequest(
        integration_id=integration_id,
        target_type="TimesheetSignoffRequest",
        target_id="999",
        external_id=external_id,
        status=status,
        sent_at=sent_at.replace(tzinfo=None),
    )
    db.session.add(esig)
    db.session.commit()
    return esig


def test_reconcile_no_stuck_returns_zero(app, recon_setup):
    """Empty queue → reconciler is a no-op."""
    with app.app_context():
        touched = TimesheetSignoffService.reconcile_stuck_requests()
        assert touched == 0


def test_reconcile_skips_fresh_rows(app, recon_setup):
    """A SENT row that's only 1 minute old is too fresh for reconciliation."""
    with app.app_context():
        _stuck_esig(
            recon_setup,
            external_id="fresh",
            status=ESignatureStatus.SENT,
            age_minutes=1,
        )
        touched = TimesheetSignoffService.reconcile_stuck_requests()
        assert touched == 0


def test_reconcile_skips_complete_signed_row(app, recon_setup):
    """A SIGNED row that already has its signed PDF + hash is fully terminal
    and must never be picked up — neither the status re-fetch (SENT/VIEWED only)
    nor the artefact-recovery pass (which targets only rows with NULL artefacts)."""
    with app.app_context():
        esig = _stuck_esig(
            recon_setup,
            external_id="complete",
            status=ESignatureStatus.SIGNED,
            age_minutes=120,  # way past the 5-min cutoff
        )
        esig.signed_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=120)
        esig.signed_document_path = "/data/uploads/esignatures/1/signed.pdf"
        esig.document_hash = "a" * 64
        db.session.commit()

        touched = TimesheetSignoffService.reconcile_stuck_requests()
        assert touched == 0


def test_reconcile_picks_up_stuck_and_applies(app, recon_setup):
    """SENT for 30 min + connector reports SIGNED → reconciler invokes
    apply_webhook_event with the fresh status."""
    with app.app_context():
        _stuck_esig(
            recon_setup,
            external_id="stuck-1",
            status=ESignatureStatus.SENT,
            age_minutes=30,
        )

        with (
            patch.object(
                TimesheetSignoffService,
                "_connector_for_integration",
                return_value=SimpleNamespace(
                    get_status=lambda eid: ESignatureStatus.SIGNED,
                ),
            ),
            patch.object(TimesheetSignoffService, "apply_webhook_event") as mock_apply,
        ):
            touched = TimesheetSignoffService.reconcile_stuck_requests()

        assert touched == 1
        mock_apply.assert_called_once()
        args = mock_apply.call_args
        event_arg = args[0][1] if len(args[0]) > 1 else args.kwargs.get("event")
        assert isinstance(event_arg, ESignatureWebhookEvent)
        assert event_arg.status == ESignatureStatus.SIGNED


def test_reconcile_no_op_when_status_unchanged(app, recon_setup):
    """Connector reports the same status the local row already has →
    apply_webhook_event is NOT called (avoid no-op DB writes)."""
    with app.app_context():
        _stuck_esig(
            recon_setup,
            external_id="same",
            status=ESignatureStatus.SENT,
            age_minutes=30,
        )

        with (
            patch.object(
                TimesheetSignoffService,
                "_connector_for_integration",
                return_value=SimpleNamespace(
                    get_status=lambda eid: ESignatureStatus.SENT,
                ),
            ),
            patch.object(TimesheetSignoffService, "apply_webhook_event") as mock_apply,
        ):
            touched = TimesheetSignoffService.reconcile_stuck_requests()

        assert touched == 0
        mock_apply.assert_not_called()


def test_reconcile_continues_after_per_row_exception(app, recon_setup):
    """Exception in one row's connector call must not stop the loop —
    the reconciler logs and moves on."""
    with app.app_context():
        _stuck_esig(
            recon_setup,
            external_id="boom",
            status=ESignatureStatus.SENT,
            age_minutes=30,
        )
        _stuck_esig(
            recon_setup,
            external_id="ok",
            status=ESignatureStatus.SENT,
            age_minutes=30,
        )

        call_count = {"n": 0}

        def status_or_explode(eid):
            call_count["n"] += 1
            if eid == "boom":
                raise RuntimeError("connector temporarily down")
            return ESignatureStatus.SIGNED

        with (
            patch.object(
                TimesheetSignoffService,
                "_connector_for_integration",
                return_value=SimpleNamespace(get_status=status_or_explode),
            ),
            patch.object(TimesheetSignoffService, "apply_webhook_event") as mock_apply,
        ):
            # Should not raise
            touched = TimesheetSignoffService.reconcile_stuck_requests()

        # One succeeded, one raised — caller sees the survivor count
        assert call_count["n"] == 2
        assert mock_apply.call_count == 1
        assert touched == 1


# --- Signed-artefact recovery -------------------------------------------------
# apply_webhook_event commits status=SIGNED even when _capture_signed_artefacts
# swallows a transient download failure, leaving signed_document_path +
# document_hash NULL. The status-based reconcile above only re-fetches
# SENT/VIEWED, so without a dedicated recovery pass the signed PDF + sha256
# (part of the e-signature audit trail) would be orphaned forever.


def _signed_orphan_esig(integration_id: int, *, external_id: str, signed_minutes_ago: int) -> ESignatureRequest:
    """A SIGNED row whose artefacts never landed (NULL path + hash)."""
    signed_at = datetime.now(timezone.utc) - timedelta(minutes=signed_minutes_ago)
    esig = ESignatureRequest(
        integration_id=integration_id,
        target_type="TimesheetSignoffRequest",
        target_id="999",
        external_id=external_id,
        status=ESignatureStatus.SIGNED,
        sent_at=signed_at.replace(tzinfo=None) - timedelta(minutes=5),
        signed_at=signed_at.replace(tzinfo=None),
    )
    db.session.add(esig)
    db.session.commit()
    return esig


def test_reconcile_recovers_signed_row_missing_artefacts(app, recon_setup, tmp_path):
    """SIGNED row with NULL artefacts + a now-working connector → the signed
    PDF is downloaded, stored, and hashed on the next reconcile."""
    with app.app_context():
        app.config["UPLOAD_FOLDER"] = str(tmp_path)
        esig = _signed_orphan_esig(recon_setup, external_id="orphan", signed_minutes_ago=30)
        esig_id = esig.id
        pdf_bytes = b"%PDF-1.4 signed timesheet"

        with patch.object(
            TimesheetSignoffService,
            "_connector_for_integration",
            return_value=SimpleNamespace(
                download_signed_document=lambda eid: pdf_bytes,
                download_audit_certificate=lambda eid: None,
            ),
        ):
            touched = TimesheetSignoffService.reconcile_stuck_requests()

        assert touched == 1
        refreshed = ESignatureRequest.query.get(esig_id)
        assert refreshed.signed_document_path is not None
        assert refreshed.document_hash == hashlib.sha256(pdf_bytes).hexdigest()


def test_reconcile_recovery_download_failure_leaves_null_and_no_count(app, recon_setup, tmp_path):
    """If the download fails again, artefacts stay NULL, the row is NOT counted,
    and no exception escapes — so the next cron run will retry it."""
    with app.app_context():
        app.config["UPLOAD_FOLDER"] = str(tmp_path)
        esig = _signed_orphan_esig(recon_setup, external_id="still-down", signed_minutes_ago=30)
        esig_id = esig.id

        def explode(eid):
            raise RuntimeError("provider still down")

        with patch.object(
            TimesheetSignoffService,
            "_connector_for_integration",
            return_value=SimpleNamespace(
                download_signed_document=explode,
                download_audit_certificate=lambda eid: None,
            ),
        ):
            touched = TimesheetSignoffService.reconcile_stuck_requests()

        assert touched == 0
        refreshed = ESignatureRequest.query.get(esig_id)
        assert refreshed.signed_document_path is None
        assert refreshed.document_hash is None


def test_reconcile_skips_fresh_signed_orphan(app, recon_setup, tmp_path):
    """A row signed <5 min ago is too fresh — a signed webhook may still be
    mid-capture, so recovery must not race it."""
    with app.app_context():
        app.config["UPLOAD_FOLDER"] = str(tmp_path)
        _signed_orphan_esig(recon_setup, external_id="fresh-signed", signed_minutes_ago=1)

        with patch.object(
            TimesheetSignoffService,
            "_connector_for_integration",
            return_value=SimpleNamespace(
                download_signed_document=lambda eid: b"unused",
                download_audit_certificate=lambda eid: None,
            ),
        ):
            touched = TimesheetSignoffService.reconcile_stuck_requests()

        assert touched == 0
