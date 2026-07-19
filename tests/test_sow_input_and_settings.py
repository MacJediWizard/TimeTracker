"""Coverage for SOW input extraction, the Claude test-connection endpoint, and
the admin settings-save handler for the Claude/SOW provider.

These exercise behaviour that previously had no automated tests:
  * /api/ai/sow/parse file handling — PDF (native), DOCX (server-side text),
    TXT (decoded), and the docx-unavailable guard;
  * /api/ai/sow/test — the "Test Claude connection" button;
  * /admin/settings — persistence + normalisation of the claude_* fields.

The parse route is reached through HTTP (the extraction helpers live in a module
the api package loads under a synthetic name and aren't directly importable).
ClaudeService is patched on the class object, which the route references by
identity, so no real Anthropic call is made.
"""

import io
import sys

import pytest

from app.services.claude_service import ClaudeService


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def _capture_parse(monkeypatch):
    """Patch ClaudeService.parse_sow to record how the route called it."""
    captured = {}

    def fake_parse(self, *, sow_text=None, pdf_bytes=None):
        captured["sow_text"] = sow_text
        captured["pdf_bytes"] = pdf_bytes
        return {"plan": {"client": {"name": "C"}, "project": {"name": "P"}, "tasks": []}}

    monkeypatch.setattr(ClaudeService, "parse_sow", fake_parse)
    return captured


# --- SOW input extraction (via the parse route) -------------------------------


def test_parse_pdf_upload_is_sent_natively(app, client, admin_user, monkeypatch):
    """A .pdf upload is passed to Claude as pdf_bytes, not extracted to text."""
    captured = _capture_parse(monkeypatch)
    _login(client, admin_user)
    pdf = b"%PDF-1.4 fake signed sow"
    resp = client.post(
        "/api/ai/sow/parse",
        data={"file": (io.BytesIO(pdf), "scope.pdf")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert captured["pdf_bytes"] == pdf
    assert not captured["sow_text"]


def test_parse_txt_upload_is_decoded_to_text(app, client, admin_user, monkeypatch):
    """A .txt upload is decoded server-side and passed as sow_text."""
    captured = _capture_parse(monkeypatch)
    _login(client, admin_user)
    resp = client.post(
        "/api/ai/sow/parse",
        data={"file": (io.BytesIO("Deliver a network refresh".encode("utf-8")), "scope.txt")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert captured["sow_text"] == "Deliver a network refresh"
    assert captured["pdf_bytes"] is None


def test_parse_docx_upload_is_extracted_to_text(app, client, admin_user, monkeypatch):
    """A .docx upload has its paragraph text extracted and passed as sow_text."""
    docx = pytest.importorskip("docx")  # python-docx is a declared dep; skip if not installed
    captured = _capture_parse(monkeypatch)

    document = docx.Document()
    document.add_paragraph("SOW body line one")
    document.add_paragraph("SOW body line two")
    buf = io.BytesIO()
    document.save(buf)

    _login(client, admin_user)
    resp = client.post(
        "/api/ai/sow/parse",
        data={"file": (io.BytesIO(buf.getvalue()), "scope.docx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert "SOW body line one" in captured["sow_text"]
    assert "SOW body line two" in captured["sow_text"]
    assert captured["pdf_bytes"] is None


def test_parse_docx_unavailable_returns_clear_error(app, client, admin_user, monkeypatch):
    """If python-docx is missing, a .docx upload fails with a specific error code
    rather than a generic 500."""
    monkeypatch.setitem(sys.modules, "docx", None)  # force `import docx` to raise
    _login(client, admin_user)
    resp = client.post(
        "/api/ai/sow/parse",
        data={"file": (io.BytesIO(b"PK fake docx"), "scope.docx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 500
    assert resp.get_json()["error_code"] == "docx_unavailable"


# --- Test-connection endpoint -------------------------------------------------


def test_sow_test_connection_admin_ok(app, client, admin_user, monkeypatch):
    monkeypatch.setattr(
        ClaudeService,
        "test_connection",
        lambda self: {"ok": True, "model": "claude-opus-4-8"},
    )
    _login(client, admin_user)
    resp = client.post("/api/ai/sow/test")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_sow_test_connection_forbidden_for_regular_user(app, client, user):
    _login(client, user)
    resp = client.post("/api/ai/sow/test")
    assert resp.status_code == 403


# --- Admin settings-save handler ----------------------------------------------


def test_settings_save_persists_and_normalises_claude_fields(app, client, admin_user):
    """POSTing the settings form stores the claude_* fields with the same
    normalisation/clamping the UI relies on."""
    from app.models.settings import Settings

    _login(client, admin_user)
    resp = client.post(
        "/admin/settings",
        data={
            "claude_enabled_mode": "true",
            "claude_model": "claude-opus-4-8",
            "claude_effort": "max",  # max is Opus-only -> must survive
            "claude_timeout_seconds": "99999",  # must clamp to 600
            "claude_api_key": "sk-ant-secret-value",
        },
        content_type="application/x-www-form-urlencoded",
    )
    assert resp.status_code in (200, 302)

    with app.app_context():
        cfg = Settings.get_settings().get_claude_config(include_secrets=True)
        assert cfg["enabled"] is True
        assert cfg["model"] == "claude-opus-4-8"
        assert cfg["effort"] == "max"
        assert cfg["timeout_seconds"] == 600
        assert cfg["api_key"] == "sk-ant-secret-value"
        assert cfg["api_key_set"] is True


def test_claude_api_key_is_a_registered_secret_field():
    """Regression: claude_api_key must be a recognised secret field.

    The admin settings handler calls set_secret("claude_api_key", ...) whenever a
    key is entered or the clear-key box is ticked. set_secret raises ValueError
    (not AttributeError) for unregistered fields, and the handler only guards
    AttributeError -- so a missing registration 500s the whole settings page on
    the one action needed to enable the tool.
    """
    from app.models.settings import Settings

    assert "claude_api_key" in Settings._SECRET_FIELDS
    s = Settings()
    s.set_secret("claude_api_key", "sk-ant-roundtrip")  # must not raise
    assert s.get_secret("claude_api_key") == "sk-ant-roundtrip"
