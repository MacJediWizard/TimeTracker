"""Regression test: InvoiceService.create_invoice defaults issue_date on the app clock.

InvoiceService is the primary invoice-creation path. It passed an explicit
``issue_date=issue_date or date.today()`` into the repository, which *overrode*
the model's own app-clock default — so every invoice created without an explicit
issue_date was stamped on the naive OS/UTC clock. On a server whose UTC day
trails the configured business timezone, a brand-new invoice was dated a day
early. The default now uses ``local_now().date()`` (the app business clock).
"""

from datetime import date, timedelta

import pytest
from freezegun import freeze_time

pytestmark = [pytest.mark.integration]

from app import db
from app.models import Settings
from app.services import InvoiceService

_CROSS_MIDNIGHT_UTC = "2026-07-15 22:00:00"  # 2026-07-16 07:00 in Asia/Tokyo


def _set_app_timezone(name):
    settings = Settings.get_settings()
    settings.timezone = name
    db.session.commit()


def test_create_invoice_defaults_issue_date_to_business_today(app, test_project, test_user):
    with app.app_context():
        _set_app_timezone("Asia/Tokyo")
        with freeze_time(_CROSS_MIDNIGHT_UTC):
            result = InvoiceService().create_invoice(
                project_id=test_project.id,
                client_id=test_project.client_id,
                client_name="TZ Client",
                due_date=date(2026, 8, 15),
                created_by=test_user.id,
                # issue_date intentionally omitted -> service default kicks in
            )

        assert result["success"] is True
        # Business today in Tokyo is 2026-07-16; a UTC/OS clock reads 2026-07-15.
        assert result["invoice"].issue_date == date(2026, 7, 16)
