"""Regression test: ReportingService.get_reports_summary windows on the app clock.

The "this month vs last month" comparison in get_reports_summary anchored its
window with datetime.utcnow() (naive UTC) while TimeEntry.start_time is stored
naive in the app's business timezone (app.models.time_entry.local_now). On a
server whose UTC clock sits on an earlier calendar day than the app timezone, a
just-logged entry had start_time > utcnow and was excluded from "this month".

Pinning the app timezone to Asia/Tokyo and freezing at an instant where Tokyo
and UTC are on different calendar days makes the bug deterministic: this-month
hours are counted only when the window is computed on the app clock.
"""

from datetime import timedelta

import pytest
from freezegun import freeze_time

pytestmark = [pytest.mark.integration]

from app import db
from app.models import Settings, TimeEntry
from app.models.time_entry import local_now
from app.services import ReportingService

_CROSS_MIDNIGHT_UTC = "2026-07-15 22:00:00"  # 2026-07-16 07:00 in Asia/Tokyo


def _set_app_timezone(name):
    settings = Settings.get_settings()
    settings.timezone = name
    db.session.commit()


def test_reports_summary_this_month_uses_app_timezone(app, user, project):
    with app.app_context():
        _set_app_timezone("Asia/Tokyo")
        with freeze_time(_CROSS_MIDNIGHT_UTC):
            end = local_now()  # Tokyo 2026-07-16 07:00, past UTC midnight
            entry = TimeEntry(
                user_id=user.id,
                project_id=project.id,
                start_time=end - timedelta(minutes=30),
                end_time=end,
                duration_seconds=1800,
                billable=True,
            )
            db.session.add(entry)
            db.session.commit()

            summary = ReportingService().get_reports_summary(user_id=user.id, is_admin=False)

        # With a UTC window the entry (Tokyo 2026-07-16) sits past utcnow
        # (2026-07-15) and is dropped; on the app clock it is inside this month.
        assert summary["comparison"]["this_month"]["hours"] == pytest.approx(0.5)
