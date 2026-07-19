"""Regression: invoice/document numbers must use the business-calendar date.

The date tokens (YYYY/MM/DD) baked into a generated number are keyed to the
app's configured timezone, not UTC. Near midnight the two calendars differ, so
a UTC clock would stamp the wrong day into the number.
"""

import pytest
from freezegun import freeze_time

from app import db
from app.models import Invoice, Settings
from app.utils.invoice_numbering import generate_next_document_number, generate_next_invoice_number

pytestmark = [pytest.mark.integration]

# 2026-07-15 22:00 UTC is already 2026-07-16 07:00 in Asia/Tokyo — a different
# calendar day, so a UTC vs app-clock mistake is visible in the number.
_CROSS_MIDNIGHT_UTC = "2026-07-15 22:00:00"


def _set_app_timezone(name):
    settings = Settings.get_settings()
    settings.timezone = name
    db.session.commit()


@pytest.mark.integration
def test_generate_invoice_number_uses_business_calendar_date(app, user, project, test_client):
    _set_app_timezone("Asia/Tokyo")
    settings = Settings.get_settings()
    settings.invoice_prefix = "RE"
    settings.invoice_number_pattern = "{PREFIX}-{YYYY}{MM}{DD}-{SEQ}"
    settings.invoice_start_number = 1
    db.session.commit()

    with freeze_time(_CROSS_MIDNIGHT_UTC):
        number = generate_next_invoice_number(Invoice)

    # Tokyo date is 2026-07-16, not the UTC 2026-07-15.
    assert "20260716" in number
    assert "20260715" not in number


@pytest.mark.integration
def test_generate_document_number_uses_business_calendar_date(app, user, project, test_client):
    _set_app_timezone("Asia/Tokyo")

    with freeze_time(_CROSS_MIDNIGHT_UTC):
        number = generate_next_document_number(
            Invoice,
            Invoice.invoice_number,
            prefix="DOC",
            pattern="{PREFIX}-{YYYY}{MM}{DD}-{SEQ}",
            start_number=1,
        )

    assert "20260716" in number
    assert "20260715" not in number
