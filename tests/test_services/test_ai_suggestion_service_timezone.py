"""Regression tests: AISuggestionService._suggest_by_deadlines.

Two defects fixed together in the timezone-window sweep:

1. AttributeError — the code computed ``task.due_date.date()`` but Task.due_date
   is a ``db.Date`` (a ``datetime.date``, which has no ``.date()``). Any task
   inside the deadline window raised AttributeError, crashing suggestions.

2. Wrong clock — the "upcoming deadline" horizon used ``datetime.utcnow()`` while
   due dates are business-calendar dates. Anchoring the horizon and the
   days-until-deadline math on the app clock (``local_now``) keeps them correct
   when the server's UTC day differs from the business timezone.

Freezing at an instant where Tokyo and UTC differ by a calendar day exercises
both: old code raises AttributeError; new code returns a correct suggestion.
"""

from datetime import timedelta

import pytest
from freezegun import freeze_time

pytestmark = [pytest.mark.integration]

from app import db
from app.models import Settings, Task
from app.models.time_entry import local_now
from app.services.ai_suggestion_service import AISuggestionService

_CROSS_MIDNIGHT_UTC = "2026-07-15 22:00:00"  # 2026-07-16 07:00 in Asia/Tokyo


def _set_app_timezone(name):
    settings = Settings.get_settings()
    settings.timezone = name
    db.session.commit()


def test_suggest_by_deadlines_does_not_crash_and_counts_business_days(app, user, project):
    with app.app_context():
        _set_app_timezone("Asia/Tokyo")
        with freeze_time(_CROSS_MIDNIGHT_UTC):
            due = local_now().date() + timedelta(days=2)  # Tokyo 2026-07-18
            task = Task(
                project_id=project.id,
                name="Ship the sweep",
                due_date=due,
                assigned_to=user.id,
                created_by=user.id,
                status="in_progress",
            )
            db.session.add(task)
            db.session.commit()

            # On the pre-fix code this raised AttributeError (date has no .date()).
            suggestions = AISuggestionService()._suggest_by_deadlines(user.id)

        deadline = [s for s in suggestions if s.get("type") == "deadline" and s.get("task_id") == task.id]
        assert deadline, "expected a deadline suggestion for the upcoming task"
        # 2026-07-18 minus business-today 2026-07-16 == 2 days on the app clock.
        # A UTC anchor (2026-07-15) would read 3 days.
        assert deadline[0]["reason"] == "Deadline in 2 days"
        assert deadline[0]["urgency"] == "high"
