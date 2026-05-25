"""Partial unique index ``uq_signoff_active`` behaviour — proves the
resend-after-decline pattern works.

Constraint: at most one ``timesheet_signoff_requests`` row per
``(engineer_user_id, client_id, period_start, period_end)`` where
``cancelled_at IS NULL``. Cancelled rows persist for audit history."""

from datetime import date, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.client import Client
from app.models.timesheet_signoff_request import (
    TimesheetSignoffRequest,
    TimesheetSignoffStatus,
)
from app.models.timesheet_signoff_template import TimesheetSignoffTemplate
from app.models.user import User


@pytest.fixture
def signoff_setup(app):
    """Minimal fixtures for the constraint test — one user, one client,
    one template."""
    with app.app_context():
        engineer = User(username="engineer-1", email="eng@example.com")
        admin = User(username="admin-1", email="admin@example.com")
        db.session.add_all([engineer, admin])
        client_obj = Client(name="Acme Test Co")
        db.session.add(client_obj)
        db.session.flush()
        template = TimesheetSignoffTemplate(
            name="constraint-test-template",
            columns_to_show=["time", "duration", "project", "task", "notes"],
        )
        db.session.add(template)
        db.session.commit()
        return {
            "engineer_id": engineer.id,
            "admin_id": admin.id,
            "client_id": client_obj.id,
            "template_id": template.id,
        }


def _build(scope, **overrides) -> TimesheetSignoffRequest:
    defaults = dict(
        timesheet_period_id=None,
        client_id=scope["client_id"],
        engineer_user_id=scope["engineer_id"],
        period_start=date(2026, 5, 4),
        period_end=date(2026, 5, 8),
        signer_email="signer@example.com",
        signer_name="Pat Signer",
        template_id=scope["template_id"],
        status=TimesheetSignoffStatus.DRAFT,
        created_by=scope["admin_id"],
    )
    defaults.update(overrides)
    return TimesheetSignoffRequest(**defaults)


def test_first_active_signoff_inserts(app, signoff_setup):
    with app.app_context():
        signoff = _build(signoff_setup)
        db.session.add(signoff)
        db.session.commit()
        assert signoff.id is not None
        assert signoff.cancelled_at is None


def test_second_active_signoff_for_same_scope_blocked(app, signoff_setup):
    with app.app_context():
        db.session.add(_build(signoff_setup))
        db.session.commit()
        db.session.add(_build(signoff_setup))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_cancel_then_insert_succeeds(app, signoff_setup):
    """The resend-after-decline workflow: cancel the active row, insert
    a fresh one for the same scope — partial index only counts active."""
    with app.app_context():
        first = _build(signoff_setup)
        db.session.add(first)
        db.session.commit()

        first.cancelled_at = datetime.utcnow()
        first.status = TimesheetSignoffStatus.CANCELLED
        db.session.commit()

        second = _build(signoff_setup)
        db.session.add(second)
        db.session.commit()

        assert second.id is not None
        assert second.id != first.id

        # Both rows persist — cancelled one stays for audit
        rows = (
            TimesheetSignoffRequest.query.filter_by(
                engineer_user_id=signoff_setup["engineer_id"],
                client_id=signoff_setup["client_id"],
                period_start=date(2026, 5, 4),
                period_end=date(2026, 5, 8),
            )
            .order_by(TimesheetSignoffRequest.id.asc())
            .all()
        )
        assert len(rows) == 2
        assert rows[0].cancelled_at is not None
        assert rows[1].cancelled_at is None


def test_different_periods_dont_conflict(app, signoff_setup):
    with app.app_context():
        db.session.add(_build(signoff_setup, period_end=date(2026, 5, 8)))
        db.session.add(
            _build(
                signoff_setup,
                period_start=date(2026, 5, 11),
                period_end=date(2026, 5, 15),
            )
        )
        db.session.commit()


def test_different_clients_dont_conflict(app, signoff_setup):
    """Same engineer, same period, different clients — independent
    signoffs (per design decision #4)."""
    with app.app_context():
        other_client = Client(name="Beta Test Co")
        db.session.add(other_client)
        db.session.flush()
        db.session.add(_build(signoff_setup))
        db.session.add(_build(signoff_setup, client_id=other_client.id))
        db.session.commit()
