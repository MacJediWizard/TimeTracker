"""Regression tests: Invoice.issue_date defaults on the app business clock.

Two related defects fixed in the timezone-window sweep:

1. Import-time evaluation — the column default was ``datetime.utcnow().date``.
   ``datetime.utcnow()`` ran once at class-definition time, so the bound ``.date``
   method returned the process-start date forever; every invoice created via the
   DB default inherited the day the app booted instead of today.

2. Wrong clock — ``__init__`` fell back to ``datetime.utcnow().date()`` (naive
   UTC) for a business-calendar date. On a server whose UTC day trails the app
   timezone, a new invoice was stamped a day early.

Both now route through ``_default_issue_date()`` (a per-call callable on the app
clock).
"""

from datetime import date, timedelta

import pytest
from freezegun import freeze_time

pytestmark = [pytest.mark.integration]

from app import db
from app.models import Settings
from app.models.invoice import Invoice
from app.models.time_entry import local_now

_CROSS_MIDNIGHT_UTC = "2026-07-15 22:00:00"  # 2026-07-16 07:00 in Asia/Tokyo


def _set_app_timezone(name):
    settings = Settings.get_settings()
    settings.timezone = name
    db.session.commit()


def test_invoice_issue_date_defaults_to_business_today(app):
    with app.app_context():
        _set_app_timezone("Asia/Tokyo")
        with freeze_time(_CROSS_MIDNIGHT_UTC):
            # Transient instance: __init__ stamps issue_date, no commit needed.
            inv = Invoice(
                invoice_number="INV-TZ-1",
                project_id=1,
                client_name="Acme",
                due_date=local_now().date() + timedelta(days=30),
                created_by=1,
                client_id=1,
            )
        # Business today in Tokyo is 2026-07-16; a UTC clock reads 2026-07-15.
        assert inv.issue_date == date(2026, 7, 16)


def test_default_issue_date_is_evaluated_per_call(app):
    """The column default must re-read the clock on every insert, not bind once."""
    from app.models.invoice import _default_issue_date

    with app.app_context():
        _set_app_timezone("Asia/Tokyo")
        with freeze_time("2030-01-02 12:00:00"):
            assert _default_issue_date() == date(2030, 1, 2)
        with freeze_time("2031-06-07 12:00:00"):
            assert _default_issue_date() == date(2031, 6, 7)
