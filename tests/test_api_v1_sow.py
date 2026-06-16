"""Token-auth (API v1) tests for SOW auto-provisioning."""

from app import db
from app.models import ApiToken, Project


def _plan():
    return {
        "client": {"name": "Acme Corp", "email": "ops@acme.test"},
        "project": {"name": "Network Refresh", "billable": True, "hourly_rate": 175},
        "tasks": [{"name": "Site survey", "status": "todo", "priority": "high"}],
    }


def _token_for(user, scopes="write:ai"):
    token, plain = ApiToken.create_token(
        user_id=user.id, name="SOW Test Token", scopes=scopes
    )
    db.session.add(token)
    db.session.commit()
    return plain


def test_v1_sow_provision_with_admin_token(app, client, admin_user):
    plain = _token_for(admin_user)
    headers = {"Authorization": f"Bearer {plain}", "Content-Type": "application/json"}
    resp = client.post(
        "/api/v1/ai/sow/provision", json={"plan": _plan()}, headers=headers
    )
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
    resp = client.post(
        "/api/v1/ai/sow/provision", json={"plan": _plan()}, headers=headers
    )
    assert resp.status_code == 403


def test_v1_sow_provision_requires_token(app, client):
    resp = client.post("/api/v1/ai/sow/provision", json={"plan": _plan()})
    assert resp.status_code in (401, 403)
