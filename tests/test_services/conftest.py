"""Shared fixtures for service-layer tests.

Service methods (TimeTrackingService, ProjectService, InvoiceService, ...)
call ``db.session`` directly — commit/rollback/refresh — which requires an
active Flask application context. These tests mock the repositories but do
not request the ``app`` fixture, so without this they raise
``RuntimeError: Working outside of application context``.

The global ``app`` fixture already yields *inside* ``app.app_context()``, so
depending on it (autouse) gives every test in this directory a live context.
We depend on it rather than pushing a second ``app.app_context()`` to avoid
creating a second scoped session that would detach fixture-created objects.
"""

import pytest


@pytest.fixture(autouse=True)
def _service_app_context(app):
    """Provide an active app context to every service-layer test."""
    yield


@pytest.fixture
def other_user(app):
    """A second non-admin user, distinct from the `user` fixture.

    Used by ownership/access-denied tests that need a different user id than
    the one owning the entity under test.
    """
    from app import db
    from app.models import User

    existing = User.query.filter_by(username="otheruser").first()
    if existing:
        return existing

    user = User(username="otheruser", role="user", email="otheruser@example.com")
    user.is_active = True
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    db.session.refresh(user)
    return user
