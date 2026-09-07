"""
Regression tests for the attachment-download IDOR fix.

Before the fix, the three attachment-download routes were only guarded by
@login_required, so ANY authenticated user could enumerate attachment_id and
exfiltrate any client's / project's / comment's attachment. The fix adds a
scope check (app.utils.scope_filter) before the file is served:

  - GET /clients/attachments/<id>/download   -> user_can_access_client
  - GET /projects/attachments/<id>/download  -> user_can_access_project
  - GET /comments/attachments/<id>/download  -> access on parent project/task/quote

These tests prove a scope-restricted (subcontractor) user gets 403 on a
foreign attachment, while an authorized user (admin, or the owner of an
assigned project) is not blocked.
"""

import pytest

from app.models import (
    Client,
    ClientAttachment,
    Comment,
    CommentAttachment,
    Project,
    ProjectAttachment,
)

pytestmark = [pytest.mark.integration, pytest.mark.security]


def _login(test_client, username, password="password123"):
    """Log a user in through the real /login endpoint (mirrors conftest helpers)."""
    from flask import current_app

    login_data = {"username": username, "password": password}
    headers = {}
    try:
        if current_app.config.get("WTF_CSRF_ENABLED"):
            resp = test_client.get("/auth/csrf-token")
            token = (resp.get_json() or {}).get("csrf_token") if resp.is_json else ""
            login_data["csrf_token"] = token or ""
            headers["X-CSRFToken"] = token or ""
    except Exception:
        pass
    return test_client.post("/login", data=login_data, headers=headers or None, follow_redirects=True)


@pytest.fixture
def real_file(tmp_path):
    """A real file on disk; its ABSOLUTE path is stored as file_path so the
    handler's os.path.join(root, '..', file_path) resolves straight to it."""
    p = tmp_path / "secret_attachment.txt"
    p.write_bytes(b"top secret client data")
    return str(p)


@pytest.fixture
def foreign_client(db_session):
    """A client the scope_restricted_user is NOT assigned to."""
    c = Client(name="Foreign Corp")
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def foreign_project(db_session, foreign_client):
    """A project under the foreign client (out of the scoped user's scope)."""
    proj = Project(name="Foreign Project", client_id=foreign_client.id, status="active")
    db_session.add(proj)
    db_session.commit()
    return proj


# ---------------------------------------------------------------------------
# Project attachment
# ---------------------------------------------------------------------------


def test_project_attachment_download_blocked_for_out_of_scope_user(
    client, db_session, scope_restricted_user, admin_user, foreign_project, real_file
):
    att = ProjectAttachment(
        project_id=foreign_project.id,
        filename="secret.txt",
        original_filename="secret.txt",
        file_path=real_file,
        file_size=22,
        uploaded_by=admin_user.id,
        mime_type="text/plain",
    )
    db_session.add(att)
    db_session.commit()

    _login(client, scope_restricted_user.username)
    resp = client.get(f"/projects/attachments/{att.id}/download")
    assert resp.status_code == 403, "out-of-scope user must be denied the foreign project attachment"


def test_project_attachment_download_allowed_for_admin(client, db_session, admin_user, foreign_project, real_file):
    att = ProjectAttachment(
        project_id=foreign_project.id,
        filename="secret.txt",
        original_filename="secret.txt",
        file_path=real_file,
        file_size=22,
        uploaded_by=admin_user.id,
        mime_type="text/plain",
    )
    db_session.add(att)
    db_session.commit()

    _login(client, admin_user.username)
    resp = client.get(f"/projects/attachments/{att.id}/download")
    assert resp.status_code == 200
    assert b"top secret client data" in resp.data


def test_project_attachment_download_allowed_for_assigned_project(
    client, db_session, scope_restricted_user, admin_user, project, real_file
):
    """The scoped user CAN download an attachment on a project under their assigned client."""
    att = ProjectAttachment(
        project_id=project.id,
        filename="ok.txt",
        original_filename="ok.txt",
        file_path=real_file,
        file_size=22,
        uploaded_by=admin_user.id,
        mime_type="text/plain",
    )
    db_session.add(att)
    db_session.commit()

    _login(client, scope_restricted_user.username)
    resp = client.get(f"/projects/attachments/{att.id}/download")
    assert resp.status_code != 403, "guard must NOT block access to an in-scope project attachment"


# ---------------------------------------------------------------------------
# Client attachment
# ---------------------------------------------------------------------------


def test_client_attachment_download_blocked_for_out_of_scope_user(
    client, db_session, scope_restricted_user, admin_user, foreign_client, real_file
):
    att = ClientAttachment(
        client_id=foreign_client.id,
        filename="secret.txt",
        original_filename="secret.txt",
        file_path=real_file,
        file_size=22,
        uploaded_by=admin_user.id,
        mime_type="text/plain",
    )
    db_session.add(att)
    db_session.commit()

    _login(client, scope_restricted_user.username)
    resp = client.get(f"/clients/attachments/{att.id}/download")
    assert resp.status_code == 403, "out-of-scope user must be denied the foreign client attachment"


def test_client_attachment_download_allowed_for_admin(client, db_session, admin_user, foreign_client, real_file):
    att = ClientAttachment(
        client_id=foreign_client.id,
        filename="secret.txt",
        original_filename="secret.txt",
        file_path=real_file,
        file_size=22,
        uploaded_by=admin_user.id,
        mime_type="text/plain",
    )
    db_session.add(att)
    db_session.commit()

    _login(client, admin_user.username)
    resp = client.get(f"/clients/attachments/{att.id}/download")
    assert resp.status_code == 200
    assert b"top secret client data" in resp.data


# ---------------------------------------------------------------------------
# Comment attachment (parent = project)
# ---------------------------------------------------------------------------


def test_comment_attachment_download_blocked_for_out_of_scope_user(
    client, db_session, scope_restricted_user, admin_user, foreign_project, real_file
):
    comment = Comment(content="internal note", user_id=admin_user.id, project_id=foreign_project.id)
    db_session.add(comment)
    db_session.commit()

    att = CommentAttachment(
        comment_id=comment.id,
        filename="secret.txt",
        original_filename="secret.txt",
        file_path=real_file,
        file_size=22,
        uploaded_by=admin_user.id,
        mime_type="text/plain",
    )
    db_session.add(att)
    db_session.commit()

    _login(client, scope_restricted_user.username)
    resp = client.get(f"/comments/attachments/{att.id}/download")
    assert resp.status_code == 403, "out-of-scope user must be denied the foreign comment attachment"


def test_comment_attachment_download_allowed_for_admin(client, db_session, admin_user, foreign_project, real_file):
    comment = Comment(content="internal note", user_id=admin_user.id, project_id=foreign_project.id)
    db_session.add(comment)
    db_session.commit()

    att = CommentAttachment(
        comment_id=comment.id,
        filename="secret.txt",
        original_filename="secret.txt",
        file_path=real_file,
        file_size=22,
        uploaded_by=admin_user.id,
        mime_type="text/plain",
    )
    db_session.add(att)
    db_session.commit()

    _login(client, admin_user.username)
    resp = client.get(f"/comments/attachments/{att.id}/download")
    assert resp.status_code == 200
    assert b"top secret client data" in resp.data
