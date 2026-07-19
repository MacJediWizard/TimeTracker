"""Regression test: overtime weekly summary windows on the app clock.

get_weekly_overtime_summary seeded its window end with datetime.now().date()
(naive OS-local) while TimeEntry.start_time is stored naive in the app's
business timezone. When the OS/UTC clock is on an earlier calendar day than the
app timezone, a just-logged entry fell past end_datetime and was excluded from
the summary — silently under-counting worked (and billable/overtime) hours.

Asia/Tokyo + a frozen instant that is a different calendar day from UTC makes
the drop deterministic: the entry's hours appear only when the window end is
computed on the app clock.
"""

from datetime import timedelta

import pytest
from freezegun import freeze_time

pytestmark = [pytest.mark.integration]

from app import db
from app.models import Settings, TimeEntry
from app.models.time_entry import local_now
from app.utils.overtime import get_weekly_overtime_summary

_CROSS_MIDNIGHT_UTC = "2026-07-15 22:00:00"  # 2026-07-16 07:00 in Asia/Tokyo


def _set_app_timezone(name):
    settings = Settings.get_settings()
    settings.timezone = name
    db.session.commit()


def test_weekly_overtime_summary_window_uses_app_timezone(app, user, project):
    with app.app_context():
        _set_app_timezone("Asia/Tokyo")
        with freeze_time(_CROSS_MIDNIGHT_UTC):
            end = local_now()  # Tokyo 2026-07-16 07:00
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

            summary = get_weekly_overtime_summary(user, weeks=4)

        # With an OS-local window end (2026-07-15) the entry (Tokyo 2026-07-16)
        # is past end_datetime and excluded; on the app clock it is counted.
        total = sum(week["total_hours"] for week in summary)
        assert total == pytest.approx(0.5)
