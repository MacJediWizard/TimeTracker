"""Regression test for the DocuSeal webhook CSRF exemption
(app/routes/esignature_webhooks.py).

Inbound provider webhooks carry no CSRF token — they authenticate via the
connector's HMAC verification, not a browser session. Without ``@csrf.exempt``
the global CSRFProtect rejects the POST with 400 *before* the view runs, so the
HMAC check never happens and DocuSeal callbacks silently fail in any deployment
with ``WTF_CSRF_ENABLED=true`` (the production default).

The test suite disables CSRF by default (TestingConfig), so we flip it on for
this test to prove the exempt route is reached: a POST with no CSRF token must
NOT be rejected with a CSRF 400 — it should fall through to the handler and get
401 (bad/absent HMAC signature) or 404 (unknown integration), never 400.
"""

import pytest

from app import db
from app.models.integration import Integration

pytestmark = [pytest.mark.integration, pytest.mark.security]


@pytest.fixture
def csrf_on(app):
    """Genuinely wire CSRF protection onto the test app.

    The test app is built with WTF_CSRF_ENABLED=False, so create_app() skips
    ``csrf.init_app(app)`` entirely (app/__init__.py) — merely flipping the config
    flag at runtime does nothing because the before_request guard was never
    registered. We register it here. The ``app`` fixture is function-scoped and
    has not served a request yet, so init_app() is still allowed and the wiring is
    discarded with the app when the test ends.
    """
    from app import csrf

    app.config["WTF_CSRF_ENABLED"] = True
    csrf.init_app(app)
    yield


def _csrf_rejected(resp):
    """True when the response is a CSRFProtect rejection (what the bug produced)."""
    if resp.status_code != 400:
        return False
    body = resp.get_data(as_text=True) or ""
    return "csrf" in body.lower()


def test_webhook_active_integration_not_csrf_blocked(app, client, admin_user, csrf_on):
    """With CSRF enforced, a tokenless webhook POST to a real integration reaches
    the HMAC check (401), instead of being turned away by CSRF (400)."""
    with app.app_context():
        integration = Integration(name="DocuSeal", provider="docuseal", user_id=admin_user.id)
        integration.is_active = True
        db.session.add(integration)
        db.session.commit()
        integration_id = integration.id

    resp = client.post(
        f"/webhooks/esignature/{integration_id}",
        json={"event_type": "form.completed", "data": {}},
    )
    assert not _csrf_rejected(resp), f"webhook POST was rejected by CSRF ({resp.status_code}); @csrf.exempt missing"
    # HMAC fails (no/invalid signature) -> 401; a connector that cannot be built -> 404.
    assert resp.status_code in (401, 404)


def test_webhook_unknown_integration_not_csrf_blocked(app, client, csrf_on):
    """Even for a missing integration the request must reach the view's 404 path,
    proving CSRF did not short-circuit it first."""
    resp = client.post(
        "/webhooks/esignature/99999999",
        json={"event_type": "form.completed", "data": {}},
    )
    assert not _csrf_rejected(resp)
    assert resp.status_code == 404


def test_csrf_control_nonexempt_route_is_blocked(app, client, csrf_on):
    """Control: with CSRF wired on, a tokenless POST to a NON-exempt route
    (signoff cancel) IS rejected with a CSRF 400. This proves the harness is
    genuinely enforcing CSRF, so the two 'not blocked' assertions above are
    meaningful rather than passing because CSRF is silently inert."""
    resp = client.post("/workforce/signoffs/1/cancel")
    assert _csrf_rejected(resp), f"expected a CSRF 400 on a non-exempt route, got {resp.status_code}"
