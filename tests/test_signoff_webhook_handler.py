"""Inbound webhook handler behaviour for ``/webhooks/esignature/<id>``.

Tests cover the security + idempotency paths the handler implements:
- 404 when no Integration matches the path
- 401 when HMAC verify_webhook returns False
- 200 noop when external_id is unknown (so the provider stops retrying)
- 200 noop when local state is already at the same terminal status
- 200 + service call on the happy path
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import db
from app.models.esignature_request import ESignatureRequest, ESignatureStatus
from app.models.integration import Integration, IntegrationCredential


@pytest.fixture
def docuseal_integration(app):
    """An active DocuSeal Integration row with credentials wired."""
    with app.app_context():
        integration = Integration(
            name="DocuSeal",
            provider="docuseal",
            is_global=True,
            is_active=True,
        )
        db.session.add(integration)
        db.session.flush()
        cred = IntegrationCredential(
            integration_id=integration.id,
            extra_data={
                "DOCUSEAL_BASE_URL": "https://docuseal.example.com",
                "DOCUSEAL_API_KEY": "test-key",
                "DOCUSEAL_WEBHOOK_SECRET": "whsec_test",
            },
        )
        db.session.add(cred)
        db.session.commit()
        return integration.id


def test_returns_404_when_integration_missing(client):
    resp = client.post("/webhooks/esignature/99999", data=b"{}")
    assert resp.status_code == 404


def test_returns_401_when_signature_invalid(client, docuseal_integration):
    resp = client.post(
        f"/webhooks/esignature/{docuseal_integration}",
        data=b'{"event_type":"form.completed"}',
        headers={"X-Docuseal-Signature": "0.deadbeef"},
    )
    assert resp.status_code == 401


def test_returns_200_for_unknown_external_id(client, app, docuseal_integration):
    """Provider must NOT retry for submissions we don't know about
    (already archived locally, or never ours). Handler returns 200."""
    with patch("app.services.integration_service.IntegrationService.get_connector") as mock_get:
        mock_conn = SimpleNamespace(
            verify_webhook=lambda body, headers: True,
            parse_webhook=lambda body: SimpleNamespace(
                external_id="42424242",
                status=ESignatureStatus.SIGNED,
                occurred_at=None,
                decline_reason=None,
                signer_email=None,
                raw_payload=None,
            ),
        )
        mock_get.return_value = mock_conn
        resp = client.post(
            f"/webhooks/esignature/{docuseal_integration}",
            data=b"{}",
            headers={"X-Docuseal-Signature": "fake"},
        )
    assert resp.status_code == 200


def test_returns_200_when_already_terminal_same_status(client, app, docuseal_integration):
    """Duplicate webhook (already-signed event for an already-signed row)
    must be idempotent — return 200, do not call the service."""
    with app.app_context():
        esig = ESignatureRequest(
            integration_id=docuseal_integration,
            target_type="TimesheetSignoffRequest",
            target_id="1",
            external_id="dup-1",
            status=ESignatureStatus.SIGNED,
        )
        db.session.add(esig)
        db.session.commit()

    with (
        patch("app.services.integration_service.IntegrationService.get_connector") as mock_get,
        patch("app.services.timesheet_signoff_service.TimesheetSignoffService.apply_webhook_event") as mock_apply,
    ):
        mock_get.return_value = SimpleNamespace(
            verify_webhook=lambda body, headers: True,
            parse_webhook=lambda body: SimpleNamespace(
                external_id="dup-1",
                status=ESignatureStatus.SIGNED,
                occurred_at=None,
                decline_reason=None,
                signer_email=None,
                raw_payload=None,
            ),
        )
        resp = client.post(
            f"/webhooks/esignature/{docuseal_integration}",
            data=b"{}",
            headers={"X-Docuseal-Signature": "fake"},
        )
    assert resp.status_code == 200
    mock_apply.assert_not_called()


def test_calls_service_on_happy_path(client, app, docuseal_integration):
    """Valid signature + known external_id + non-terminal status →
    service.apply_webhook_event is called exactly once."""
    with app.app_context():
        esig = ESignatureRequest(
            integration_id=docuseal_integration,
            target_type="TimesheetSignoffRequest",
            target_id="1",
            external_id="happy-1",
            status=ESignatureStatus.SENT,
        )
        db.session.add(esig)
        db.session.commit()

    with (
        patch("app.services.integration_service.IntegrationService.get_connector") as mock_get,
        patch("app.services.timesheet_signoff_service.TimesheetSignoffService.apply_webhook_event") as mock_apply,
    ):
        mock_get.return_value = SimpleNamespace(
            verify_webhook=lambda body, headers: True,
            parse_webhook=lambda body: SimpleNamespace(
                external_id="happy-1",
                status=ESignatureStatus.SIGNED,
                occurred_at=None,
                decline_reason=None,
                signer_email=None,
                raw_payload=None,
            ),
        )
        resp = client.post(
            f"/webhooks/esignature/{docuseal_integration}",
            data=b"{}",
            headers={"X-Docuseal-Signature": "fake"},
        )
    assert resp.status_code == 200
    mock_apply.assert_called_once()
