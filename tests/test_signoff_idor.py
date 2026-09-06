"""Regression tests for the signoff-action IDOR fix (app/routes/signoff.py).

Before the fix, the three per-request routes guarded access with::

    period = TimesheetPeriod.query.get(signoff.timesheet_period_id)
    if period and not _can_act_on_period(period):
        abort(403)

``timesheet_period_id`` is nullable (ondelete=SET NULL), so once the parent
period was deleted the guard's ``if period`` short-circuited to *allow* — ANY
authenticated user could then cancel a foreign signoff or download its signed
PDF / Certificate of Completion by enumerating request_id.

The fix (``_can_act_on_signoff``) never default-allows on a missing period: it
falls back to the signoff's own ``engineer_user_id`` ownership, so a non-owner
is blocked (403) even when the period is gone, while the owning engineer and
admins keep access.

These tests set ``timesheet_period_id=None`` to exercise exactly that path.
"""

from datetime import date

import pytest

from app import db
from app.models.client import Client
from app.models.timesheet_signoff_request import TimesheetSignoffRequest, TimesheetSignoffStatus
from app.models.timesheet_signoff_template import TimesheetSignoffTemplate

pytestmark = [pytest.mark.integration, pytest.mark.security]


def _login(client, user, password="password123"):
    return client.post(
        "/login",
        data={"username": user.username, "password": password},
        follow_redirects=True,
    )


@pytest.fixture
def signoff_scaffold(app):
    """A client + default template — the minimum to build a signoff row."""
    with app.app_context():
        client_obj = Client(name="IDOR Signoff Client")
        db.session.add(client_obj)
        template = TimesheetSignoffTemplate(
            name="idor-default",
            is_default=True,
            columns_to_show=["time", "duration", "project", "task", "notes"],
        )
        db.session.add(template)
        db.session.commit()
        return {"client_id": client_obj.id, "template_id": template.id}


def _make_signoff(scaffold, *, engineer_id, created_by, status=TimesheetSignoffStatus.SENT):
    """Create a signoff whose parent period is NULL (the SET-NULL / orphan case)."""
    signoff = TimesheetSignoffRequest(
        timesheet_period_id=None,
        client_id=scaffold["client_id"],
        engineer_user_id=engineer_id,
        period_start=date(2026, 5, 4),
        period_end=date(2026, 5, 8),
        signer_email="pm@example.com",
        template_id=scaffold["template_id"],
        status=status,
        created_by=created_by,
    )
    db.session.add(signoff)
    db.session.commit()
    return signoff.id


# --- blocked for a non-owner when the period is gone --------------------------


def test_cancel_null_period_forbidden_for_non_owner(app, client, admin_user, user, signoff_scaffold):
    with app.app_context():
        sid = _make_signoff(signoff_scaffold, engineer_id=admin_user.id, created_by=admin_user.id)

    _login(client, user)  # regular user, not the engineer, not admin
    resp = client.post(f"/workforce/signoffs/{sid}/cancel", follow_redirects=False)
    assert resp.status_code == 403, "a non-owner must not cancel a foreign signoff whose period was deleted"


def test_signed_pdf_null_period_forbidden_for_non_owner(app, client, admin_user, user, signoff_scaffold):
    with app.app_context():
        sid = _make_signoff(
            signoff_scaffold, engineer_id=admin_user.id, created_by=admin_user.id, status=TimesheetSignoffStatus.SIGNED
        )

    _login(client, user)
    resp = client.get(f"/workforce/signoffs/{sid}/signed-pdf")
    assert resp.status_code == 403, "a non-owner must not download a foreign signed PDF whose period was deleted"


def test_coc_null_period_forbidden_for_non_owner(app, client, admin_user, user, signoff_scaffold):
    with app.app_context():
        sid = _make_signoff(
            signoff_scaffold, engineer_id=admin_user.id, created_by=admin_user.id, status=TimesheetSignoffStatus.SIGNED
        )

    _login(client, user)
    resp = client.get(f"/workforce/signoffs/{sid}/coc")
    assert resp.status_code == 403, "a non-owner must not download a foreign CoC whose period was deleted"


# --- still allowed for the owning engineer and admins ------------------------


def test_cancel_null_period_allowed_for_owning_engineer(app, client, user, signoff_scaffold):
    """The engineer who owns the signoff keeps access even with the period gone."""
    with app.app_context():
        sid = _make_signoff(signoff_scaffold, engineer_id=user.id, created_by=user.id)

    _login(client, user)
    resp = client.post(f"/workforce/signoffs/{sid}/cancel", follow_redirects=False)
    assert resp.status_code != 403, "the owning engineer must still be able to cancel their signoff"
    assert resp.status_code in (302, 303)


def test_cancel_null_period_allowed_for_admin(app, client, admin_user, user, signoff_scaffold):
    """Admins may always act, even on a signoff they do not own with no period."""
    with app.app_context():
        sid = _make_signoff(signoff_scaffold, engineer_id=user.id, created_by=user.id)

    _login(client, admin_user)
    resp = client.post(f"/workforce/signoffs/{sid}/cancel", follow_redirects=False)
    assert resp.status_code != 403, "an admin must still be able to cancel any signoff"
    assert resp.status_code in (302, 303)
