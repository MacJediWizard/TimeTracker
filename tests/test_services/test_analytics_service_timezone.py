"""Regression tests: AnalyticsService dashboard windows must use the app clock.

TimeEntry timestamps are stored as naive datetimes in the app's configured
business timezone (via app.models.time_entry.local_now). AnalyticsService used
to build its "today / this week" windows with datetime.now() (naive OS-local)
and datetime.utcnow() (naive UTC). On any deployment where the server OS clock
or UTC falls on a different calendar day than the app timezone, those windows
excluded entries the user had just logged.

These tests pin the app timezone to Asia/Tokyo and freeze the clock at an
instant where Tokyo and UTC are on different calendar days, then assert that a
Tokyo-local entry is counted. They fail against the old datetime.now()/utcnow()
implementation and pass once the service uses local_now().
"""

from datetime import timedelta

import pytest
from freezegun import freeze_time

pytestmark = [pytest.mark.integration]

from app import db
from app.models import Settings, TimeEntry
from app.models.time_entry import local_now
from app.services.analytics_service import AnalyticsService

# 22:00 UTC on 2026-07-15 is 07:00 on 2026-07-16 in Tokyo (UTC+9): the app-local
# calendar day (the 16th) differs from both the UTC and OS-local day (the 15th).
_CROSS_MIDNIGHT_UTC = "2026-07-15 22:00:00"


def _set_app_timezone(name):
    # get_app_timezone() reads the singleton Settings row (Settings.query.first()),
    # which the test fixtures already seed. Mutate that row rather than adding a
    # second one, which query.first() would ignore.
    settings = Settings.get_settings()
    settings.timezone = name
    db.session.commit()


def _add_entry(user, project, *, seconds, when):
    entry = TimeEntry(
        user_id=user.id,
        project_id=project.id,
        start_time=when,
        end_time=when + timedelta(seconds=seconds),
        billable=True,
        duration_seconds=seconds,
    )
    db.session.add(entry)
    db.session.commit()
    return entry


def test_dashboard_today_hours_use_app_timezone(app, user, project):
    with app.app_context():
        _set_app_timezone("Asia/Tokyo")
        with freeze_time(_CROSS_MIDNIGHT_UTC):
            # local_now() is Tokyo-local (2026-07-16 06:30) — the same clock the
            # app uses when it writes a real entry's start_time.
            when = local_now() - timedelta(minutes=30)
            _add_entry(user, project, seconds=3600, when=when)

            stats = AnalyticsService().get_dashboard_stats(user_id=user.id)

        # The entry belongs to "today" in the app timezone; a UTC/OS-local window
        # would have placed it on the previous day and dropped it.
        assert stats["time_tracking"]["today_hours"] == pytest.approx(1.0)


def test_dashboard_top_projects_window_uses_app_timezone(app, user, project):
    with app.app_context():
        _set_app_timezone("Asia/Tokyo")
        with freeze_time(_CROSS_MIDNIGHT_UTC):
            when = local_now() - timedelta(minutes=30)
            _add_entry(user, project, seconds=3600, when=when)

            top = AnalyticsService().get_dashboard_top_projects(user_id=user.id, days=1)

        # days=1 window start is local_now().date() - 1 day; the just-logged entry
        # must fall inside it when the window is computed on the app clock.
        assert any(row["project"].id == project.id and row["hours"] == pytest.approx(1.0) for row in top)
