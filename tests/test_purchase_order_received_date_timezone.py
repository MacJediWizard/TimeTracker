"""Regression test: PurchaseOrder.received_date defaults on the app clock.

mark_as_received() fell back to datetime.utcnow().date() (naive UTC) for
received_date, which is a business-calendar column (db.Date). On a server whose
UTC day trails the configured business timezone, receiving a PO stamped it a day
early. The default now routes through local_now().date() (the app clock).

The api_v1 receive/create endpoints had the same naive-clock fallback; this
exercises the shared model default that both paths converge on.
"""

from datetime import date

import pytest
from freezegun import freeze_time

pytestmark = [pytest.mark.integration]

from app import db
from app.models import Settings
from app.models.purchase_order import PurchaseOrder


def _set_app_timezone(name):
    settings = Settings.get_settings()
    settings.timezone = name
    db.session.commit()


def test_received_date_defaults_to_business_today(app, user):
    with app.app_context():
        _set_app_timezone("Asia/Tokyo")
        with freeze_time("2026-07-15 22:00:00"):  # 2026-07-16 07:00 in Asia/Tokyo
            # Transient PO (no items) — mark_as_received stamps received_date and
            # skips the stock-movement loop since self.items is empty.
            po = PurchaseOrder(
                po_number="PO-TZ-1",
                supplier_id=1,
                order_date=date(2026, 7, 16),
                created_by=user.id,
            )
            po.mark_as_received()

        # Business today in Tokyo is 2026-07-16; a UTC clock reads 2026-07-15.
        assert po.received_date == date(2026, 7, 16)
