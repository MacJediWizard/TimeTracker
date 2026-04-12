"""
Resolve client and actor user for integration sync (especially global integrations).

Per-user integrations use integration.user_id. Global integrations use, in order:
1. INTEGRATION_SYNC_USER_ID (numeric user id)
2. First active user with role admin
3. First active user

Projects are created under a dedicated client (default name "Integration imports"),
overridable via INTEGRATION_IMPORT_CLIENT_NAME.

External system linkage is stored in Project.custom_fields / Task.custom_fields under
the key "integration": {"source": "<provider>", "ref": "<stable id>"}.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_IMPORT_CLIENT_NAME = "Integration imports"


def _import_client_name() -> str:
    raw = (os.getenv("INTEGRATION_IMPORT_CLIENT_NAME") or "").strip()
    return raw or DEFAULT_IMPORT_CLIENT_NAME


def get_or_create_integration_import_client():
    """Return the shared Client used for imported integration projects; flush only (caller commits)."""
    from app import db
    from app.models import Client

    name = _import_client_name()
    c = Client.query.filter_by(name=name).first()
    if c:
        return c
    c = Client(name=name)
    db.session.add(c)
    db.session.flush()
    return c


def resolve_integration_actor_user_id(integration) -> Optional[int]:
    """
    User id to use for Task.created_by and similar when syncing.
    """
    from app.models import User

    if integration is not None and getattr(integration, "user_id", None) is not None:
        return integration.user_id

    env_raw = (os.getenv("INTEGRATION_SYNC_USER_ID") or "").strip()
    if env_raw.isdigit():
        uid = int(env_raw)
        from app import db

        u = db.session.get(User, uid)
        if u and getattr(u, "is_active", True):
            return uid
        logger.warning("INTEGRATION_SYNC_USER_ID=%s is missing or inactive", env_raw)

    admin = User.query.filter_by(role="admin", is_active=True).order_by(User.id).first()
    if admin:
        return admin.id

    any_user = User.query.filter_by(is_active=True).order_by(User.id).first()
    return any_user.id if any_user else None


def require_sync_context(integration) -> Tuple[int, int]:
    """
    Returns (actor_user_id, import_client_id).
    Raises ValueError with a clear message if no actor user exists.
    """
    uid = resolve_integration_actor_user_id(integration)
    if uid is None:
        raise ValueError(
            "No active user found to attribute imported tasks to. "
            "Create a user or set INTEGRATION_SYNC_USER_ID to a valid user id."
        )
    client = get_or_create_integration_import_client()
    return uid, client.id


def find_project_by_integration_ref(client_id: int, source: str, ref: str):
    from app.models import Project

    for p in Project.query.filter_by(client_id=client_id).all():
        cf = p.custom_fields if p.custom_fields is not None else {}
        block = cf.get("integration") if isinstance(cf, dict) else {}
        if isinstance(block, dict) and block.get("source") == source and block.get("ref") == ref:
            return p
    return None


def ensure_project_integration_fields(
    project,
    *,
    source: str,
    ref: str,
    display_name: str,
    description: Optional[str] = None,
) -> None:
    """Attach integration marker to project custom_fields (mutates in place)."""
    cf: Dict[str, Any] = dict(project.custom_fields) if isinstance(project.custom_fields, dict) else {}
    cf["integration"] = {"source": source, "ref": ref}
    project.custom_fields = cf
    if display_name and project.name != display_name:
        project.name = display_name
    if description is not None:
        project.description = description


def find_task_by_integration_ref(project_id: int, ref: str, source: Optional[str] = None):
    """Match task by integration ref. If ``source`` is set, require the same integration source."""
    from app.models import Task

    for t in Task.query.filter_by(project_id=project_id).all():
        cf = t.custom_fields if t.custom_fields is not None else {}
        block = cf.get("integration") if isinstance(cf, dict) else {}
        if not isinstance(block, dict) or block.get("ref") != ref:
            continue
        if source is not None and block.get("source") != source:
            continue
        return t
    return None


def set_task_integration_ref(task, *, source: str, ref: str, extra: Optional[Dict[str, Any]] = None) -> None:
    cf: Dict[str, Any] = dict(task.custom_fields) if isinstance(task.custom_fields, dict) else {}
    block: Dict[str, Any] = {"source": source, "ref": ref}
    if extra:
        block.update(extra)
    cf["integration"] = block
    task.custom_fields = cf


def sync_result_item_count(sync_result: Optional[Dict[str, Any]]) -> int:
    """Normalize synced_count vs synced_items from connector sync_data return values."""
    if not sync_result or not isinstance(sync_result, dict):
        return 0
    for key in ("synced_count", "synced_items"):
        v = sync_result.get(key)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
    return 0
