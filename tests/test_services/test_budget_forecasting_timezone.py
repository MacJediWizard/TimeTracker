"""Regression test: budget burn-rate window on the app clock.

calculate_burn_rate (and the sibling forecast/confidence helpers) seeded their
window end with datetime.now().date() (naive OS-local) while TimeEntry.start_time
is stored naive in the app's business timezone. When the OS/UTC clock is on an
earlier calendar day than the app timezone, a just-logged billable entry fell
past end_date (func.date(start_time) > end_date) and was excluded — silently
under-reporting the project's burn rate.

Asia/Tokyo + a frozen instant that is a different calendar day from UTC makes
the drop deterministic: the entry's cost appears only when the window end is
computed on the app clock.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from freezegun import freeze_time

pytestmark = [pytest.mark.integration]

from app import db
from app.models import Project, Settings, TimeEntry
from app.models.time_entry import local_now
from app.utils.budget_forecasting import calculate_burn_rate

_CROSS_MIDNIGHT_UTC = "2026-07-15 22:00:00"  # 2026-07-16 07:00 in Asia/Tokyo


def _set_app_timezone(name):
    settings = Settings.get_settings()
    settings.timezone = name
    db.session.commit()


def test_burn_rate_window_uses_app_timezone(app, user, project):
    with app.app_context():
        _set_app_timezone("Asia/Tokyo")
        # A known billable rate so the cost is deterministic.
        project = db.session.get(Project, project.id)
        project.hourly_rate = Decimal("100")
        db.session.commit()

        with freeze_time(_CROSS_MIDNIGHT_UTC):
            end = local_now()  # Tokyo 2026-07-16 07:00
            entry = TimeEntry(
                user_id=user.id,
                project_id=project.id,
                start_time=end - timedelta(minutes=30),
                end_time=end,
                duration_seconds=3600,  # 1h -> 1h * 100 = 100
                billable=True,
            )
            db.session.add(entry)
            db.session.commit()

            result = calculate_burn_rate(project.id, days=30)

        # Window end computed on the app clock is 2026-07-16, which includes the
        # entry; a naive OS-local end (2026-07-15) would exclude it and report 0.
        assert result is not None
        assert result["end_date"] == "2026-07-16"
        assert result["period_total"] == pytest.approx(100.0)
