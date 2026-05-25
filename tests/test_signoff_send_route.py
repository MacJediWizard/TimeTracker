"""Tests for the workforce-page signoff routes in
``app/routes/signoff.py``:

- ``POST /workforce/periods/<id>/signoff/send``
- ``POST /workforce/signoffs/<id>/cancel``
- ``GET  /workforce/signoffs/<id>/signed-pdf``
- ``GET  /workforce/signoffs/<id>/coc``
"""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import db
from app.models.client import Client
from app.models.esignature_request import ESignatureRequest, ESignatureStatus
from app.models.timesheet_period import TimesheetPeriod, TimesheetPeriodStatus
from app.models.timesheet_signoff_request import (
    TimesheetSignoffRequest,
    TimesheetSignoffStatus,
)
from app.models.timesheet_signoff_template import TimesheetSignoffTemplate


def _login_admin(client, admin_user):
    return client.post(
        "/login",
        data={"username": admin_user.username, "password": "password123"},
        follow_redirects=True,
    )


def _login_regular(client, user):
    return client.post(
        "/login",
        data={"username": user.username, "password": "password123"},
        follow_redirects=True,
    )


@pytest.fixture
def send_setup(app, admin_user):
    """A period + a client + a default template — the minimum for a
    signoff send call."""
    with app.app_context():
        period = TimesheetPeriod(
            user_id=admin_user.id,
            period_type="weekly",
            period_start=date(2026, 5, 4),
            period_end=date(2026, 5, 8),
            status=TimesheetPeriodStatus.DRAFT,
        )
        db.session.add(period)
        client_obj = Client(name="Acme Send Test")
        client_obj.signoff_email = "pm@example.com"
        db.session.add(client_obj)
        template = TimesheetSignoffTemplate(
            name="send-default",
            is_default=True,
            columns_to_show=["time", "duration", "project", "task", "notes"],
        )
        db.session.add(template)
        db.session.commit()
        return {
            "period_id": period.id,
            "client_id": client_obj.id,
            "template_id": template.id,
        }


def test_send_requires_login(client, send_setup):
    resp = client.post(
        f"/workforce/periods/{send_setup['period_id']}/signoff/send",
        data={},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 401, 403)


def test_send_missing_client_redirects_with_flash(client, admin_user, send_setup):
    _login_admin(client, admin_user)
    resp = client.post(
        f"/workforce/periods/{send_setup['period_id']}/signoff/send",
        data={"signer_email": "p@e.com"},  # missing client_id
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    assert "/workforce" in resp.headers.get("Location", "")


def test_send_missing_email_redirects_with_flash(client, admin_user, send_setup):
    _login_admin(client, admin_user)
    resp = client.post(
        f"/workforce/periods/{send_setup['period_id']}/signoff/send",
        data={"client_id": str(send_setup["client_id"])},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)


def test_send_unknown_period_404(client, admin_user):
    _login_admin(client, admin_user)
    resp = client.post(
        "/workforce/periods/999999/signoff/send",
        data={"client_id": "1", "signer_email": "x@x.com"},
    )
    assert resp.status_code == 404


def test_send_happy_path_creates_request_and_calls_service(
    app, client, admin_user, send_setup
):
    """Service is stubbed; we verify the route inserts the
    TimesheetSignoffRequest in DRAFT, then calls send_for_signoff."""
    _login_admin(client, admin_user)

    captured = {}

    def fake_send(signoff):
        captured["id"] = signoff.id
        captured["client_id"] = signoff.client_id
        captured["template_id"] = signoff.template_id
        captured["signer_email"] = signoff.signer_email
        signoff.status = TimesheetSignoffStatus.SENT
        signoff.sent_at = datetime.utcnow()
        db.session.commit()
        return SimpleNamespace(id=42)

    with patch(
        "app.services.timesheet_signoff_service.TimesheetSignoffService.send_for_signoff",
        side_effect=fake_send,
    ):
        resp = client.post(
            f"/workforce/periods/{send_setup['period_id']}/signoff/send",
            data={
                "client_id": str(send_setup["client_id"]),
                "signer_email": "pm@example.com",
                "signer_name": "PM Test",
            },
            follow_redirects=False,
        )

    assert resp.status_code in (302, 303)
    assert "id" in captured
    assert captured["client_id"] == send_setup["client_id"]
    assert captured["template_id"] == send_setup["template_id"]
    assert captured["signer_email"] == "pm@example.com"


def test_send_with_specific_template_id(app, client, admin_user, send_setup):
    """Admin can override the default template at send time."""
    with app.app_context():
        other = TimesheetSignoffTemplate(
            name="alt-template", columns_to_show=["time", "duration"]
        )
        db.session.add(other)
        db.session.commit()
        other_id = other.id

    _login_admin(client, admin_user)
    captured = {}

    def fake_send(signoff):
        captured["template_id"] = signoff.template_id
        signoff.status = TimesheetSignoffStatus.SENT
        signoff.sent_at = datetime.utcnow()
        db.session.commit()

    with patch(
        "app.services.timesheet_signoff_service.TimesheetSignoffService.send_for_signoff",
        side_effect=fake_send,
    ):
        client.post(
            f"/workforce/periods/{send_setup['period_id']}/signoff/send",
            data={
                "client_id": str(send_setup["client_id"]),
                "signer_email": "pm@example.com",
                "template_id": str(other_id),
            },
        )

    assert captured["template_id"] == other_id


def test_cancel_marks_row_cancelled(app, client, admin_user, send_setup):
    with app.app_context():
        signoff = TimesheetSignoffRequest(
            timesheet_period_id=send_setup["period_id"],
            client_id=send_setup["client_id"],
            engineer_user_id=admin_user.id,
            period_start=date(2026, 5, 4),
            period_end=date(2026, 5, 8),
            signer_email="pm@example.com",
            template_id=send_setup["template_id"],
            status=TimesheetSignoffStatus.SENT,
            created_by=admin_user.id,
        )
        db.session.add(signoff)
        db.session.commit()
        sid = signoff.id

    _login_admin(client, admin_user)
    resp = client.post(f"/workforce/signoffs/{sid}/cancel", follow_redirects=False)
    assert resp.status_code in (302, 303)
    with app.app_context():
        refreshed = TimesheetSignoffRequest.query.get(sid)
        assert refreshed.cancelled_at is not None


def test_download_signed_pdf_returns_404_when_file_missing(
    app, client, admin_user, send_setup
):
    """Local artefact file gone (or never captured) → 404."""
    with app.app_context():
        esig = ESignatureRequest(
            integration_id=1,
            target_type="TimesheetSignoffRequest",
            target_id="1",
            external_id="ext-x",
            status=ESignatureStatus.SIGNED,
            signed_document_path="/tmp/does-not-exist-on-disk.pdf",
        )
        db.session.add(esig)
        db.session.flush()
        signoff = TimesheetSignoffRequest(
            timesheet_period_id=send_setup["period_id"],
            client_id=send_setup["client_id"],
            engineer_user_id=admin_user.id,
            period_start=date(2026, 5, 4),
            period_end=date(2026, 5, 8),
            signer_email="pm@example.com",
            template_id=send_setup["template_id"],
            status=TimesheetSignoffStatus.SIGNED,
            created_by=admin_user.id,
            esignature_request_id=esig.id,
        )
        db.session.add(signoff)
        db.session.commit()
        sid = signoff.id

    _login_admin(client, admin_user)
    resp = client.get(f"/workforce/signoffs/{sid}/signed-pdf")
    assert resp.status_code == 404


def test_download_coc_returns_404_when_unset(app, client, admin_user, send_setup):
    """No audit_certificate_path on the ESignatureRequest → 404."""
    with app.app_context():
        esig = ESignatureRequest(
            integration_id=1,
            target_type="TimesheetSignoffRequest",
            target_id="1",
            external_id="ext-y",
            status=ESignatureStatus.SIGNED,
        )
        db.session.add(esig)
        db.session.flush()
        signoff = TimesheetSignoffRequest(
            timesheet_period_id=send_setup["period_id"],
            client_id=send_setup["client_id"],
            engineer_user_id=admin_user.id,
            period_start=date(2026, 5, 4),
            period_end=date(2026, 5, 8),
            signer_email="pm@example.com",
            template_id=send_setup["template_id"],
            status=TimesheetSignoffStatus.SIGNED,
            created_by=admin_user.id,
            esignature_request_id=esig.id,
        )
        db.session.add(signoff)
        db.session.commit()
        sid = signoff.id

    _login_admin(client, admin_user)
    resp = client.get(f"/workforce/signoffs/{sid}/coc")
    assert resp.status_code == 404
