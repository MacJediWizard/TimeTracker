"""Regression test: ReportingService.get_time_summary windows on the app clock.

TimeEntry timestamps are stored naive in the app's business timezone (via
app.models.time_entry.local_now). get_time_summary used to default its
"this month .. now" window with datetime.now() (naive OS-local). On a server
whose OS clock sits on a different calendar day than the app timezone, a
just-logged entry fell outside the window and was dropped from the summary.

Pinning the app timezone to Asia/Tokyo and freezing at an instant where Tokyo
and UTC/OS are on different calendar days makes the bug deterministic: the
entry is counted only when the window is computed on the app clock.
"""

from datetime import timedelta

import pytest
from freezegun import freeze_time

pytestmark = [pytest.mark.integration]

from app import db
from app.models import Settings, TimeEntry
from app.models.time_entry import local_now
from app.services import ReportingService

_CROSS_MIDNIGHT_UTC = "2026-07-15 22:00:00"


def _set_app_timezone(name):
    settings = Settings.get_settings()
    settings.timezone = name
    db.session.commit()


def test_get_time_summary_default_window_uses_app_timezone(app, user, project):
    with app.app_context():
        _set_app_timezone("Asia/Tokyo")
        with freeze_time(_CROSS_MIDNIGHT_UTC):
            # Written the way the app writes real entries: on the app clock.
            end = local_now()
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

            summary = ReportingService().get_time_summary(user_id=user.id, billable_only=False)

        # With a UTC/OS-local window the entry (Tokyo 2026-07-16) would sit past
        # end_date and be dropped; on the app clock it is inside "this month".
        assert summary["total_entries"] >= 1
        assert summary["total_hours"] == pytest.approx(0.5)
