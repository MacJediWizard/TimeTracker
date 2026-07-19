"""Regression: CRM activity/communication datetimes are stored on the business clock.

DealActivity.activity_date, LeadActivity.activity_date and
ContactCommunication.communication_date are db.DateTime columns whose default is
local_now (NAIVE app-local). A user-entered datetime-local value must be stored on
the same clock as that default — matching the established timer-edit convention
(utc_to_local(parse_local_datetime(...)).replace(tzinfo=None)) — not as aware-UTC.

Also covers the contacts crash: create_communication previously called
parse_local_datetime(comm_date_str) with a single arg (its signature is
(date_str, time_str)), raising TypeError on every real submission.
"""

import pytest
from freezegun import freeze_time

from app import db
from app.models import Contact, ContactCommunication, Deal, DealActivity, Lead, LeadActivity, Settings
from app.utils.timezone import parse_local_naive_from_string

pytestmark = [pytest.mark.integration]

# 2026-07-15 22:00 UTC is already 2026-07-16 07:00 in Asia/Tokyo — a different
# calendar day and hour, so a UTC-vs-app-clock mistake is unmistakable.
_CROSS_MIDNIGHT_UTC = "2026-07-15 22:00:00"


def _set_app_timezone(name):
    settings = Settings.get_settings()
    settings.timezone = name
    db.session.commit()


@pytest.mark.integration
def test_parse_local_naive_returns_naive_app_local(app):
    _set_app_timezone("Asia/Tokyo")

    # User enters 2026-07-16 07:00 on the app's (Tokyo) clock.
    result = parse_local_naive_from_string("2026-07-16T07:00")

    assert result is not None
    # Must be NAIVE, matching columns whose default is local_now.
    assert result.tzinfo is None
    # Must preserve the app-local wall clock the user entered — NOT the UTC 22:00
    # (the old aware-UTC behavior would have yielded 2026-07-15 22:00).
    assert (result.year, result.month, result.day) == (2026, 7, 16)
    assert (result.hour, result.minute) == (7, 0)


@pytest.mark.integration
def test_parse_local_naive_empty_or_invalid_returns_none(app):
    _set_app_timezone("Asia/Tokyo")

    assert parse_local_naive_from_string("") is None
    assert parse_local_naive_from_string(None) is None
    assert parse_local_naive_from_string("not-a-datetime") is None


@pytest.mark.integration
def test_create_communication_does_not_crash_and_stores_business_clock(authenticated_client, test_client, user):
    """Old code raised TypeError (single-arg parse_local_datetime) -> no row created.

    New code stores a naive business-clock ContactCommunication.
    """
    _set_app_timezone("Asia/Tokyo")

    contact = Contact(client_id=test_client.id, first_name="Ada", last_name="Lovelace", created_by=user.id)
    db.session.add(contact)
    db.session.commit()
    contact_id = contact.id

    with freeze_time(_CROSS_MIDNIGHT_UTC):
        resp = authenticated_client.post(
            f"/contacts/{contact_id}/communications/create",
            data={
                "type": "call",
                "direction": "outbound",
                "status": "completed",
                "subject": "Intro call",
                "communication_date": "2026-07-16T07:00",
            },
            follow_redirects=False,
        )

    # A successful create redirects (302); the old TypeError path re-rendered the form (200).
    assert resp.status_code == 302

    comm = ContactCommunication.query.filter_by(contact_id=contact_id).first()
    assert comm is not None, "communication row should have been created (old code crashed and created none)"
    assert comm.communication_date is not None
    # Stored on the business clock: naive, and the app-local wall time the user entered.
    assert comm.communication_date.tzinfo is None
    assert (comm.communication_date.year, comm.communication_date.month, comm.communication_date.day) == (2026, 7, 16)
    assert (comm.communication_date.hour, comm.communication_date.minute) == (7, 0)


@pytest.mark.integration
def test_create_deal_activity_stores_business_clock(authenticated_client, user):
    """DealActivity.activity_date must be stored naive on the app clock, not aware-UTC."""
    _set_app_timezone("Asia/Tokyo")

    deal = Deal(name="Acme expansion", created_by=user.id)
    db.session.add(deal)
    db.session.commit()
    deal_id = deal.id

    with freeze_time(_CROSS_MIDNIGHT_UTC):
        resp = authenticated_client.post(
            f"/deals/{deal_id}/activities/create",
            data={"type": "call", "status": "completed", "activity_date": "2026-07-16T07:00"},
            follow_redirects=False,
        )

    assert resp.status_code == 302
    activity = DealActivity.query.filter_by(deal_id=deal_id).first()
    assert activity is not None
    assert activity.activity_date.tzinfo is None
    assert (activity.activity_date.year, activity.activity_date.month, activity.activity_date.day) == (2026, 7, 16)
    assert (activity.activity_date.hour, activity.activity_date.minute) == (7, 0)


@pytest.mark.integration
def test_create_lead_activity_stores_business_clock(authenticated_client, user):
    """LeadActivity.activity_date must be stored naive on the app clock, not aware-UTC."""
    _set_app_timezone("Asia/Tokyo")

    lead = Lead(first_name="Grace", last_name="Hopper", created_by=user.id)
    db.session.add(lead)
    db.session.commit()
    lead_id = lead.id

    with freeze_time(_CROSS_MIDNIGHT_UTC):
        resp = authenticated_client.post(
            f"/leads/{lead_id}/activities/create",
            data={"type": "note", "status": "completed", "activity_date": "2026-07-16T07:00"},
            follow_redirects=False,
        )

    assert resp.status_code == 302
    activity = LeadActivity.query.filter_by(lead_id=lead_id).first()
    assert activity is not None
    assert activity.activity_date.tzinfo is None
    assert (activity.activity_date.year, activity.activity_date.month, activity.activity_date.day) == (2026, 7, 16)
    assert (activity.activity_date.hour, activity.activity_date.minute) == (7, 0)
