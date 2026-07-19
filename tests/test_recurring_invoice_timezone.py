"""Regression tests: recurring-invoice generation runs on the app business clock.

Both the daily eligibility gate (``RecurringInvoice.should_generate_today``) and the
``issue_date`` stamped on a generated invoice used the naive OS/UTC clock. On a server
whose UTC day trails the configured business timezone, a template due *business-today*
was skipped until UTC caught up (an invoice generated a day late), and once generated it
was dated a day early. Both now use ``local_now()`` (the app business clock).
"""

from datetime import date

import pytest
from freezegun import freeze_time

pytestmark = [pytest.mark.integration]

from app import db
from app.models import RecurringInvoice, Settings
from app.services.recurring_invoice_service import RecurringInvoiceService

# UTC 2026-07-15 22:00 is 2026-07-16 07:00 in Asia/Tokyo — a different calendar day.
_CROSS_MIDNIGHT_UTC = "2026-07-15 22:00:00"


def _set_app_timezone(name):
    settings = Settings.get_settings()
    settings.timezone = name
    db.session.commit()


def test_should_generate_today_uses_business_clock(app):
    """A template due business-today must be eligible even when UTC is still yesterday."""
    with app.app_context():
        _set_app_timezone("Asia/Tokyo")
        with freeze_time(_CROSS_MIDNIGHT_UTC):
            ri = RecurringInvoice(
                name="Monthly retainer",
                project_id=1,
                client_id=1,
                frequency="monthly",
                next_run_date=date(2026, 7, 16),  # business-today in Tokyo
                created_by=1,
            )
            # Business "today" (Tokyo) == next_run_date -> generate now.
            # The old UTC clock read 2026-07-15 < next_run_date and skipped a day.
            assert ri.should_generate_today() is True


def test_generate_invoice_stamps_business_issue_date(app, recurring_invoice):
    """The generated invoice's issue_date is the business-calendar day, not the UTC day."""
    with app.app_context():
        _set_app_timezone("Asia/Tokyo")
        # Make the template eligible on the frozen business day.
        recurring_invoice.next_run_date = date(2026, 7, 16)
        recurring_invoice.is_active = True
        db.session.commit()

        with freeze_time(_CROSS_MIDNIGHT_UTC):
            invoice = RecurringInvoiceService().generate_invoice(recurring_invoice)

        assert invoice is not None
        # Business today in Tokyo is 2026-07-16; a UTC/OS clock reads 2026-07-15.
        assert invoice.issue_date == date(2026, 7, 16)
