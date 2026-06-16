"""Tests for SOW auto-provisioning (service + endpoints)."""

import pytest

from app import db
from app.models import Client, KanbanColumn, Project, Task
from app.services.llm_service import AIServiceError
from app.services.sow_service import SowProvisioningService


def _plan(**project_overrides):
    project = {"name": "Network Refresh", "billable": True, "hourly_rate": 175}
    project.update(project_overrides)
    return {
        "client": {
            "name": "Acme Corp",
            "email": "ops@acme.test",
            "default_hourly_rate": 150,
        },
        "project": project,
        "tasks": [
            {
                "name": "Site survey",
                "status": "todo",
                "priority": "high",
                "estimated_hours": 8,
            },
            {"name": "Install switches", "status": "in_progress", "priority": "medium"},
        ],
    }


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


# --- service ------------------------------------------------------------------


def test_provision_creates_client_project_and_tasks(app, user):
    with app.app_context():
        result = SowProvisioningService().provision(
            _plan(start_date="2026-07-01", end_date="2026-09-30"), created_by=user.id
        )

        assert result["ok"] is True
        assert result["task_count"] == 2

        client = Client.query.filter_by(name="Acme Corp").one()
        project = Project.query.filter_by(name="Network Refresh").one()
        assert project.client_id == client.id
        assert project.custom_fields.get("sow_start_date") == "2026-07-01"
        assert project.custom_fields.get("sow_end_date") == "2026-09-30"

        tasks = Task.query.filter_by(project_id=project.id).all()
        assert {t.name for t in tasks} == {"Site survey", "Install switches"}
        valid = set(KanbanColumn.get_valid_status_keys(project_id=project.id))
        assert all(t.status in valid for t in tasks)


def test_provision_reuses_existing_client(app, user):
    with app.app_context():
        existing = Client(name="Acme Corp", created_by=user.id)
        db.session.add(existing)
        db.session.commit()
        existing_id = existing.id

        SowProvisioningService().provision(_plan(), created_by=user.id)

        assert Client.query.filter_by(name="Acme Corp").count() == 1
        project = Project.query.filter_by(name="Network Refresh").one()
        assert project.client_id == existing_id


def test_provision_coerces_invalid_task_status_to_todo(app, user):
    with app.app_context():
        plan = _plan()
        plan["tasks"] = [
            {"name": "Mystery task", "status": "nonsense_status", "priority": "low"}
        ]
        SowProvisioningService().provision(plan, created_by=user.id)

        task = Task.query.filter_by(name="Mystery task").one()
        assert task.status == "todo"


def test_provision_requires_client_and_project_names(app, user):
    with app.app_context():
        with pytest.raises(AIServiceError) as exc:
            SowProvisioningService().provision(
                {"client": {"name": ""}, "project": {"name": "X"}}, created_by=user.id
            )
        assert exc.value.code == "validation_error"


def test_provision_rolls_back_project_on_task_failure(app, user, monkeypatch):
    with app.app_context():
        from app.services.task_service import TaskService

        original = TaskService.create_task
        calls = {"n": 0}

        def flaky_create_task(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                return {
                    "success": False,
                    "message": "boom",
                    "error": "task_create_failed",
                }
            return original(self, *args, **kwargs)

        monkeypatch.setattr(TaskService, "create_task", flaky_create_task)

        with pytest.raises(AIServiceError):
            SowProvisioningService().provision(_plan(), created_by=user.id)

        # Project (and any partially-created tasks) must be gone.
        assert Project.query.filter_by(name="Network Refresh").first() is None
        assert Task.query.filter_by(name="Site survey").first() is None


# --- routes -------------------------------------------------------------------


def test_provision_route_forbidden_for_regular_user(app, client, user):
    _login(client, user)
    resp = client.post("/api/ai/sow/provision", json={"plan": _plan()})
    assert resp.status_code == 403


def test_parse_route_forbidden_for_regular_user(app, client, user):
    _login(client, user)
    resp = client.post("/api/ai/sow/parse", json={"sow_text": "anything"})
    assert resp.status_code == 403


def test_provision_route_allows_admin(app, client, admin_user):
    _login(client, admin_user)
    resp = client.post("/api/ai/sow/provision", json={"plan": _plan()})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["project"]["name"] == "Network Refresh"


def test_provision_route_requires_plan(app, client, admin_user):
    _login(client, admin_user)
    resp = client.post("/api/ai/sow/provision", json={})
    assert resp.status_code == 400


def test_parse_route_allows_admin_with_mocked_claude(
    app, client, admin_user, monkeypatch
):
    # api.py is loaded under a synthetic name by the api package, so patch the
    # service class itself — the route references the same class object by identity.
    from app.services.claude_service import ClaudeService

    def fake_parse(self, *, sow_text=None, pdf_bytes=None):
        return {"plan": _plan(), "provider": {"model": "claude-opus-4-8"}}

    monkeypatch.setattr(ClaudeService, "parse_sow", fake_parse)

    _login(client, admin_user)
    resp = client.post(
        "/api/ai/sow/parse", json={"sow_text": "Acme network refresh SOW..."}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["plan"]["project"]["name"] == "Network Refresh"


def test_provision_sow_page_renders(app, client, admin_user):
    _login(client, admin_user)
    resp = client.get("/projects/provision-sow")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "parseSowBtn" in html
    assert "provisionBtn" in html


def test_provision_sow_page_forbidden_for_regular_user(app, client, user):
    _login(client, user)
    resp = client.get("/projects/provision-sow")
    assert resp.status_code in (302, 403)


def test_settings_page_renders_claude_section(app, client, admin_user):
    _login(client, admin_user)
    resp = client.get("/admin/settings")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'id="section-claude"' in html
    assert 'name="claude_model"' in html
    assert 'name="claude_effort"' in html
    assert "claudeTestConnectionBtn" in html
