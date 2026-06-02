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
