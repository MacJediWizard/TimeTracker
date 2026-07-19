"""Regression tests: PomodoroService must stamp TimeEntry on the app clock.

TimeEntry.start_time / end_time are stored as naive datetimes in the app's
configured business timezone (via app.models.time_entry.local_now). The
Pomodoro service used to write them with datetime.utcnow(), so on any
deployment whose app timezone differs from UTC the entry landed in the wrong
calendar-day bucket — corrupting every downstream report that groups by day.

These tests pin the app timezone to Asia/Tokyo and freeze the clock at an
instant where Tokyo and UTC are on different calendar days, then assert the
TimeEntry the service creates carries the Tokyo-local timestamp (matching
every other TimeEntry the app writes) rather than the UTC one.
"""

from datetime import datetime

import pytest
from freezegun import freeze_time

pytestmark = [pytest.mark.integration]

from app import db
from app.models import Settings, TimeEntry
from app.models.time_entry import local_now
from app.services.pomodoro_service import PomodoroService

# 22:00 UTC on 2026-07-15 is 07:00 on 2026-07-16 in Tokyo (UTC+9): the app-local
# calendar day (the 16th) differs from both the UTC and OS-local day (the 15th).
_CROSS_MIDNIGHT_UTC = "2026-07-15 22:00:00"


def _set_app_timezone(name):
    settings = Settings.get_settings()
    settings.timezone = name
    db.session.commit()


def test_start_session_stamps_start_time_on_app_clock(app, user, project):
    with app.app_context():
        _set_app_timezone("Asia/Tokyo")
        with freeze_time(_CROSS_MIDNIGHT_UTC):
            result = PomodoroService().start_session(user_id=user.id, project_id=project.id)
            assert result["success"] is True

            entry = TimeEntry.query.filter_by(user_id=user.id).one()
            # The entry must sit on the Tokyo calendar day (the 16th) — the same
            # clock every other TimeEntry uses — not the UTC/OS day (the 15th).
            assert entry.start_time.date() == local_now().date()
            assert entry.start_time.date() != datetime.utcnow().date()


def test_end_session_stamps_end_time_on_app_clock(app, user, project):
    with app.app_context():
        _set_app_timezone("Asia/Tokyo")
        with freeze_time(_CROSS_MIDNIGHT_UTC):
            svc = PomodoroService()
            start = svc.start_session(user_id=user.id, project_id=project.id)
            session_id = start["session"]["id"]
            svc.end_session(session_id)

            entry = TimeEntry.query.filter_by(user_id=user.id).one()
            assert entry.end_time is not None
            assert entry.end_time.date() == local_now().date()
            assert entry.end_time.date() != datetime.utcnow().date()
            # Duration stays coherent: both ends stamped on the same clock.
            assert entry.duration_seconds == 0
