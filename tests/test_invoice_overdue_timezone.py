"""Regression test: Invoice.is_overdue / days_overdue use the app clock.

due_date is a business date the user picks. is_overdue used to compare it
against datetime.utcnow().date(). On a server whose app timezone is behind
UTC, utcnow().date() rolls to "tomorrow" late in the local evening, so an
invoice due *today* was reported overdue (and one genuinely overdue was
counted a day early). The comparison must use the app-local date.

Asia/Tokyo would hide this (ahead of UTC); we pin America/Los_Angeles and
freeze at an instant where UTC has already ticked to the next calendar day
while Los Angeles has not.
"""

from datetime import datetime, timedelta

import pytest
from freezegun import freeze_time

from app import db
from app.models import Settings
from app.models.invoice import Invoice
from app.models.time_entry import local_now

# 05:00 UTC on 2026-07-16 is 22:00 on 2026-07-15 in Los Angeles (UTC-7, PDT):
# UTC is on the 16th, the app-local day is still the 15th.
_UTC_AHEAD_OF_LOCAL = "2026-07-16 05:00:00"


def _set_app_timezone(name):
    settings = Settings.get_settings()
    settings.timezone = name
    db.session.commit()


def _transient_invoice(*, due_date, status="sent"):
    # is_overdue / days_overdue read only status + due_date, so a transient
    # (unsaved) invoice exercises them without any FK/DB setup. Invoice.__init__
    # does not take status (it's a Column default applied only on flush), so set
    # it explicitly — otherwise a transient invoice has status=None.
    invoice = Invoice(
        invoice_number="INV-TZ-1",
        project_id=1,
        client_name="TZ Client",
        due_date=due_date,
        created_by=1,
        client_id=1,
    )
    invoice.status = status
    return invoice


def test_invoice_due_today_is_not_overdue_on_app_clock(app):
    with app.app_context():
        _set_app_timezone("America/Los_Angeles")
        with freeze_time(_UTC_AHEAD_OF_LOCAL):
            # Due on the app-local "today" (the 15th). UTC already reads the 16th.
            invoice = _transient_invoice(due_date=local_now().date())

            # Old utcnow().date() (the 16th) would call this overdue by a day.
            assert invoice.is_overdue is False
            assert invoice.days_overdue == 0
            assert local_now().date() != datetime.utcnow().date()


def test_invoice_days_overdue_counted_on_app_clock(app):
    with app.app_context():
        _set_app_timezone("America/Los_Angeles")
        with freeze_time(_UTC_AHEAD_OF_LOCAL):
            invoice = _transient_invoice(due_date=local_now().date() - timedelta(days=3))

            # Exactly 3 on the app clock; old utcnow().date() would report 4.
            assert invoice.is_overdue is True
            assert invoice.days_overdue == 3
