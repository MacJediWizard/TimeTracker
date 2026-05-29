"""HMAC webhook verification for DocuSeal — security-critical path.

Vectors are computed in-test against the documented spec
(``lib/webhook_urls/signatures.rb`` in docusealco/docuseal): signature
is ``{unix_timestamp}.{hex_digest}`` where the digest is HMAC-SHA256
over ``"{ts}.{body}"``, secret is the ``whsec_*`` value, and the
timestamp must be within ±5 minutes of now."""

import hashlib
import hmac
import time
from types import SimpleNamespace


from app.integrations.esignature.docuseal import DocuSealConnector

_SECRET = "whsec_test-secret-do-not-use-in-prod"
_BODY = b'{"event_type":"form.completed","timestamp":"2026-05-21T18:00:00Z","data":{"id":1}}'


def _make_signature(secret: str, body: bytes, ts: int) -> str:
    """Build a valid X-Docuseal-Signature header value for vectors."""
    payload = f"{ts}.".encode() + body
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"{ts}.{digest}"


def _connector(app, secret: str | None = _SECRET) -> DocuSealConnector:
    """Build a connector wired only with the webhook secret. Other config
    is irrelevant for verify_webhook tests."""
    extra = {}
    if secret is not None:
        extra["DOCUSEAL_WEBHOOK_SECRET"] = secret
    integration = SimpleNamespace(id=1, provider="docuseal", is_active=True)
    credentials = SimpleNamespace(extra_data=extra)
    with app.app_context():
        return DocuSealConnector(integration, credentials)


def test_verify_accepts_valid_signature(app):
    conn = _connector(app)
    ts = int(time.time())
    header = _make_signature(_SECRET, _BODY, ts)
    with app.app_context():
        assert conn.verify_webhook(_BODY, {"X-Docuseal-Signature": header}) is True


def test_verify_accepts_lowercase_header(app):
    conn = _connector(app)
    ts = int(time.time())
    header = _make_signature(_SECRET, _BODY, ts)
    with app.app_context():
        assert conn.verify_webhook(_BODY, {"x-docuseal-signature": header}) is True


def test_verify_rejects_tampered_body(app):
    conn = _connector(app)
    ts = int(time.time())
    header = _make_signature(_SECRET, _BODY, ts)
    tampered = _BODY + b"trailing"
    with app.app_context():
        assert conn.verify_webhook(tampered, {"X-Docuseal-Signature": header}) is False


def test_verify_rejects_wrong_secret(app):
    conn = _connector(app)
    ts = int(time.time())
    header = _make_signature("whsec_wrong-secret", _BODY, ts)
    with app.app_context():
        assert conn.verify_webhook(_BODY, {"X-Docuseal-Signature": header}) is False


def test_verify_rejects_stale_timestamp(app):
    conn = _connector(app)
    stale_ts = int(time.time()) - 600  # 10 minutes ago, beyond 5-min tolerance
    header = _make_signature(_SECRET, _BODY, stale_ts)
    with app.app_context():
        assert conn.verify_webhook(_BODY, {"X-Docuseal-Signature": header}) is False


def test_verify_rejects_future_timestamp(app):
    conn = _connector(app)
    future_ts = int(time.time()) + 600
    header = _make_signature(_SECRET, _BODY, future_ts)
    with app.app_context():
        assert conn.verify_webhook(_BODY, {"X-Docuseal-Signature": header}) is False


def test_verify_rejects_missing_header(app):
    conn = _connector(app)
    with app.app_context():
        assert conn.verify_webhook(_BODY, {}) is False


def test_verify_rejects_malformed_header(app):
    conn = _connector(app)
    with app.app_context():
        # No dot separator
        assert conn.verify_webhook(_BODY, {"X-Docuseal-Signature": "not-a-valid-format"}) is False
        # Non-integer timestamp
        assert conn.verify_webhook(_BODY, {"X-Docuseal-Signature": "abc.def123"}) is False


def test_verify_fails_closed_when_secret_missing(app):
    """No DOCUSEAL_WEBHOOK_SECRET configured → reject every webhook,
    even one with a syntactically valid signature."""
    conn = _connector(app, secret=None)
    ts = int(time.time())
    # Whatever signature is provided, it should be rejected
    header = _make_signature("whsec_any", _BODY, ts)
    with app.app_context():
        assert conn.verify_webhook(_BODY, {"X-Docuseal-Signature": header}) is False


def test_verify_uses_constant_time_compare(app):
    """Sanity check: we should be calling hmac.compare_digest (not ==).
    Verified by patching hmac.compare_digest and asserting it was hit."""
    conn = _connector(app)
    ts = int(time.time())
    header = _make_signature(_SECRET, _BODY, ts)

    import app.integrations.esignature.docuseal as docuseal_module

    calls = []
    real_compare = docuseal_module.hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real_compare(a, b)

    docuseal_module.hmac.compare_digest = spy
    try:
        with app.app_context():
            conn.verify_webhook(_BODY, {"X-Docuseal-Signature": header})
        assert len(calls) == 1
    finally:
        docuseal_module.hmac.compare_digest = real_compare
