"""Token-auth (API v1) tests for SOW auto-provisioning."""

import io

from app import db
from app.models import ApiToken, Project
from app.services.claude_service import ClaudeService


def _plan():
    return {
        "client": {"name": "Acme Corp", "email": "ops@acme.test"},
        "project": {"name": "Network Refresh", "billable": True, "hourly_rate": 175},
        "tasks": [{"name": "Site survey", "status": "todo", "priority": "high"}],
    }


def _token_for(user, scopes="write:ai"):
    token, plain = ApiToken.create_token(user_id=user.id, name="SOW Test Token", scopes=scopes)
    db.session.add(token)
    db.session.commit()
    return plain


def test_v1_sow_provision_with_admin_token(app, client, admin_user):
    plain = _token_for(admin_user)
    headers = {"Authorization": f"Bearer {plain}", "Content-Type": "application/json"}
    resp = client.post("/api/v1/ai/sow/provision", json={"plan": _plan()}, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["project"]["name"] == "Network Refresh"
    assert Project.query.filter_by(name="Network Refresh").count() == 1


def test_v1_sow_provision_requires_plan(app, client, admin_user):
    plain = _token_for(admin_user)
    headers = {"Authorization": f"Bearer {plain}", "Content-Type": "application/json"}
    resp = client.post("/api/v1/ai/sow/provision", json={}, headers=headers)
    assert resp.status_code == 400


def test_v1_sow_provision_forbidden_for_regular_user(app, client, user):
    plain = _token_for(user)
    headers = {"Authorization": f"Bearer {plain}", "Content-Type": "application/json"}
    resp = client.post("/api/v1/ai/sow/provision", json={"plan": _plan()}, headers=headers)
    assert resp.status_code == 403


def test_v1_sow_provision_requires_token(app, client):
    resp = client.post("/api/v1/ai/sow/provision", json={"plan": _plan()})
    assert resp.status_code in (401, 403)


def _capture_parse(monkeypatch):
    captured = {}

    def fake_parse(self, *, sow_text=None, pdf_bytes=None, user_id=None):
        captured["sow_text"] = sow_text
        captured["pdf_bytes"] = pdf_bytes
        captured["user_id"] = user_id
        return {"plan": _plan(), "provider": {"model": "claude-opus-4-8"}}

    monkeypatch.setattr(ClaudeService, "parse_sow", fake_parse)
    return captured


def test_v1_sow_parse_accepts_pdf_upload(app, client, admin_user, monkeypatch):
    """v1 parse now has parity with the cookie route: a .pdf multipart upload
    is forwarded to Claude as native pdf_bytes, not flattened to text."""
    captured = _capture_parse(monkeypatch)
    plain = _token_for(admin_user)
    pdf = b"%PDF-1.4 fake signed sow"
    resp = client.post(
        "/api/v1/ai/sow/parse",
        data={"file": (io.BytesIO(pdf), "scope.pdf")},
        content_type="multipart/form-data",
        headers={"Authorization": f"Bearer {plain}"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    assert captured["pdf_bytes"] == pdf
    assert not captured["sow_text"]
    assert captured["user_id"] == admin_user.id


def test_v1_sow_parse_accepts_txt_upload(app, client, admin_user, monkeypatch):
    captured = _capture_parse(monkeypatch)
    plain = _token_for(admin_user)
    resp = client.post(
        "/api/v1/ai/sow/parse",
        data={"file": (io.BytesIO(b"Plain text SOW body"), "scope.txt")},
        content_type="multipart/form-data",
        headers={"Authorization": f"Bearer {plain}"},
    )
    assert resp.status_code == 200
    assert captured["sow_text"] == "Plain text SOW body"
    assert captured["pdf_bytes"] is None


def test_v1_sow_parse_accepts_json_text(app, client, admin_user, monkeypatch):
    captured = _capture_parse(monkeypatch)
    plain = _token_for(admin_user)
    resp = client.post(
        "/api/v1/ai/sow/parse",
        json={"sow_text": "Acme network refresh"},
        headers={"Authorization": f"Bearer {plain}"},
    )
    assert resp.status_code == 200
    assert captured["sow_text"] == "Acme network refresh"
