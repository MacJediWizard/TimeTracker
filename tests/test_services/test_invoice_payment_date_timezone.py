"""Regression test: Invoice.payment_date defaults on the app business clock.

``Invoice.payment_date`` is a ``db.Date`` column — a business-calendar sibling of
``issue_date``/``due_date`` (payment_gateway_service already stamps it with
``now_in_app_timezone().date()``). The repository's ``mark_as_paid`` and the model's
deprecated ``record_payment`` used ``date.today()`` / ``datetime.utcnow().date()``,
so on a server whose UTC/OS day trails the configured business timezone an invoice
paid just after local midnight was dated a day early. Both now default to
``local_now().date()`` (the app business clock).
"""

from datetime import date

import pytest
from freezegun import freeze_time

pytestmark = [pytest.mark.integration]

from app import db
from app.models import Settings
from app.repositories import InvoiceRepository
from app.services import InvoiceService

_CROSS_MIDNIGHT_UTC = "2026-07-15 22:00:00"  # 2026-07-16 07:00 in Asia/Tokyo


def _set_app_timezone(name):
    settings = Settings.get_settings()
    settings.timezone = name
    db.session.commit()


def test_mark_as_paid_defaults_payment_date_to_business_today(app, test_project, test_user):
    with app.app_context():
        _set_app_timezone("Asia/Tokyo")
        result = InvoiceService().create_invoice(
            project_id=test_project.id,
            client_id=test_project.client_id,
            client_name="TZ Client",
            due_date=date(2026, 8, 15),
            created_by=test_user.id,
        )
        assert result["success"] is True
        invoice_id = result["invoice"].id

        with freeze_time(_CROSS_MIDNIGHT_UTC):
            # payment_date intentionally omitted -> repository default kicks in.
            invoice = InvoiceRepository().mark_as_paid(invoice_id)

        # Business today in Tokyo is 2026-07-16; a UTC/OS clock reads 2026-07-15.
        assert invoice.payment_date == date(2026, 7, 16)


def test_record_payment_defaults_payment_date_to_business_today(app, test_project, test_user):
    with app.app_context():
        _set_app_timezone("Asia/Tokyo")
        result = InvoiceService().create_invoice(
            project_id=test_project.id,
            client_id=test_project.client_id,
            client_name="TZ Client",
            due_date=date(2026, 8, 15),
            created_by=test_user.id,
        )
        assert result["success"] is True
        invoice = result["invoice"]

        with freeze_time(_CROSS_MIDNIGHT_UTC):
            # payment_date intentionally omitted -> model default kicks in.
            invoice.record_payment(amount=invoice.total_amount)

        assert invoice.payment_date == date(2026, 7, 16)
