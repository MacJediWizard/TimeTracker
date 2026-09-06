"""SOW auto-provisioning.

Takes a confirmed ``SowPlan`` (produced by ``ClaudeService.parse_sow``) and
provisions a Client (find-or-create), a Project, default Kanban columns, and the
Tasks — reusing the existing service-layer create paths so all validation, events,
and audit hooks fire normally.

The whole provisioning is effectively atomic: if any step fails after the project
is created, the project is deleted (Task/TimeEntry cascade with it) so a misparse
never leaves a half-built project behind.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from app import db
from app.models import Client, KanbanColumn
from app.repositories import ClientRepository
from app.services.llm_service import AIServiceError
from app.services.project_service import ProjectService
from app.services.task_service import TaskService
from app.utils.db import safe_commit

logger = logging.getLogger(__name__)


def _clean_str(value: Any) -> str:
    """Coerce an incoming plan field to a stripped string.

    Plan JSON comes straight from the client (the review UI or an API caller), so
    a field the schema expects to be a string may arrive as a number, list, or
    dict. Returning "" for any non-string keeps a malformed plan on the clean
    validation_error path instead of raising AttributeError -> 500.
    """
    return value.strip() if isinstance(value, str) else ""


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_date(value: Any) -> Optional[date]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.strip()[:10]).date()
    except ValueError:
        return None


class SowProvisioningService:
    """Provision a project + kanban + tasks from a confirmed SOW plan."""

    def __init__(self):
        self.client_repo = ClientRepository()
        self.project_service = ProjectService()
        self.task_service = TaskService()

    def provision(self, plan: Dict[str, Any], *, created_by: int) -> Dict[str, Any]:
        if not isinstance(plan, dict):
            raise AIServiceError("Invalid SOW plan.", "validation_error", 400)

        client_data = plan.get("client") or {}
        project_data = plan.get("project") or {}
        tasks_data = plan.get("tasks") or []

        client_name = _clean_str(client_data.get("name"))
        project_name = _clean_str(project_data.get("name"))
        if not client_name:
            raise AIServiceError("SOW plan is missing a client name.", "validation_error", 400)
        if not project_name:
            raise AIServiceError("SOW plan is missing a project name.", "validation_error", 400)

        client, client_created = self._find_or_create_client(client_data, client_name, created_by=created_by)

        project = None
        try:
            result = self.project_service.create_project(
                name=project_name,
                client_id=client.id,
                created_by=created_by,
                description=(_clean_str(project_data.get("description")) or None),
                billable=bool(project_data.get("billable", True)),
                hourly_rate=_to_float(project_data.get("hourly_rate")),
                code=(_clean_str(project_data.get("code")) or None),
                budget_amount=_to_float(project_data.get("budget_amount")),
            )
            if not result.get("success"):
                raise AIServiceError(
                    result.get("message") or "Could not create project.",
                    result.get("error") or "project_create_failed",
                    400,
                )
            project = result["project"]
            self._store_project_dates(project, project_data)
            KanbanColumn.initialize_default_columns(project_id=project.id)
            created_tasks = self._create_tasks(tasks_data, project_id=project.id, created_by=created_by)
        except Exception:
            # Effectively-atomic: undo the project (tasks/entries cascade) and, if we
            # created the client just for this SOW, the client too — so a misparse or a
            # mid-provision failure never leaves a half-built project or an orphan client.
            if project is not None:
                self._rollback_project(project)
            if client_created:
                self._rollback_client(client)
            raise

        return {
            "ok": True,
            "client": {"id": client.id, "name": client.name},
            "project": {"id": project.id, "name": project.name, "code": project.code},
            "task_count": len(created_tasks),
            "tasks": created_tasks,
        }

    def _find_or_create_client(self, client_data: Dict[str, Any], name: str, *, created_by: int) -> tuple[Client, bool]:
        """Return ``(client, created)``.

        ``created`` is True only when a new row was persisted, so the caller can roll
        back a SOW-created client on a later failure without deleting a pre-existing
        one it merely matched by name.
        """
        existing = self.client_repo.get_by_name(name)
        if existing:
            return existing, False
        client = Client(
            name=name,
            contact_person=(_clean_str(client_data.get("contact_person")) or None),
            email=(_clean_str(client_data.get("email")) or None),
            default_hourly_rate=_to_float(client_data.get("default_hourly_rate")),
            created_by=created_by,
        )
        db.session.add(client)
        if not safe_commit("sow_create_client", {"name": name}):
            raise AIServiceError("Could not create client from SOW.", "client_create_failed", 400)
        return client, True

    def _store_project_dates(self, project, project_data: Dict[str, Any]) -> None:
        start_date = _to_date(project_data.get("start_date"))
        end_date = _to_date(project_data.get("end_date"))
        if not start_date and not end_date:
            return
        custom = dict(project.custom_fields or {})
        if start_date:
            custom["sow_start_date"] = start_date.isoformat()
        if end_date:
            custom["sow_end_date"] = end_date.isoformat()
        project.custom_fields = custom
        if not safe_commit("sow_store_project_dates", {"project_id": project.id}):
            raise AIServiceError("Could not store project dates.", "project_update_failed", 400)

    def _create_tasks(
        self, tasks_data: List[Dict[str, Any]], *, project_id: int, created_by: int
    ) -> List[Dict[str, Any]]:
        valid_statuses = set(KanbanColumn.get_valid_status_keys(project_id=project_id) or ())
        created: List[Dict[str, Any]] = []
        for item in tasks_data:
            if not isinstance(item, dict):
                continue
            name = _clean_str(item.get("name"))
            if not name:
                continue
            status = _clean_str(item.get("status")) or "todo"
            if valid_statuses and status not in valid_statuses:
                status = "todo"
            result = self.task_service.create_task(
                name=name,
                project_id=project_id,
                created_by=created_by,
                description=(_clean_str(item.get("description")) or None),
                priority=(_clean_str(item.get("priority")) or "medium"),
                due_date=_to_date(item.get("due_date")),
                estimated_hours=_to_float(item.get("estimated_hours")),
                status=status,
                tags=(_clean_str(item.get("tags")) or None),
            )
            if not result.get("success"):
                raise AIServiceError(
                    result.get("message") or f"Could not create task '{name}'.",
                    result.get("error") or "task_create_failed",
                    400,
                )
            task = result["task"]
            created.append(
                {
                    "id": task.id,
                    "name": task.name,
                    "status": task.status,
                    "priority": task.priority,
                }
            )
        return created

    def _rollback_project(self, project) -> None:
        try:
            db.session.delete(project)
            safe_commit("sow_rollback_project", {"project_id": getattr(project, "id", None)})
        except Exception:  # pragma: no cover - best-effort cleanup
            db.session.rollback()
            logger.exception("Failed to roll back SOW project after provisioning error")

    def _rollback_client(self, client) -> None:
        try:
            db.session.delete(client)
            safe_commit("sow_rollback_client", {"client_id": getattr(client, "id", None)})
        except Exception:  # pragma: no cover - best-effort cleanup
            db.session.rollback()
            logger.exception("Failed to roll back SOW client after provisioning error")
