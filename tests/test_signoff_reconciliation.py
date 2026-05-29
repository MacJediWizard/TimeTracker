"""Tests for ``TimesheetSignoffService.reconcile_stuck_requests`` — the
function the 15-minute cron calls. We test the function directly so the
scheduler is out of scope (the cron-trigger registration in
``app/utils/scheduled_tasks.py`` is just a thin wrapper)."""

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


def test_reconcile_skips_terminal_status(app, recon_setup):
    """A SIGNED/DECLINED row should never be picked up — the query
    filter excludes terminal statuses."""
    with app.app_context():
        _stuck_esig(
            recon_setup,
            external_id="terminal",
            status=ESignatureStatus.SIGNED,
            age_minutes=120,  # way past the 5-min cutoff
        )
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
