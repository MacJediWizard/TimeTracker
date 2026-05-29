"""Tests for the admin template editor at ``/admin/signoff-templates``
plus the branding-asset upload endpoint."""

import io

from app import db
from app.models.branding_asset import BrandingAsset
from app.models.timesheet_signoff_template import TimesheetSignoffTemplate


def _login_admin(client, admin_user):
    return client.post(
        "/login",
        data={"username": admin_user.username, "password": "password123"},
        follow_redirects=True,
    )


def _login_regular(client, user):
    return client.post(
        "/login",
        data={"username": user.username, "password": "password123"},
        follow_redirects=True,
    )


def test_list_requires_login(client):
    resp = client.get("/admin/signoff-templates", follow_redirects=False)
    assert resp.status_code in (302, 401, 403)


def test_list_denied_to_regular_user(client, user):
    _login_regular(client, user)
    resp = client.get("/admin/signoff-templates", follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_list_ok_for_admin(client, admin_user):
    _login_admin(client, admin_user)
    resp = client.get("/admin/signoff-templates")
    assert resp.status_code == 200


def test_list_shows_existing_templates(app, client, admin_user):
    with app.app_context():
        db.session.add(
            TimesheetSignoffTemplate(
                name="visible-template",
                columns_to_show=["time", "duration"],
            )
        )
        db.session.commit()

    _login_admin(client, admin_user)
    resp = client.get("/admin/signoff-templates")
    assert resp.status_code == 200
    assert b"visible-template" in resp.data


def test_new_form_renders(client, admin_user):
    _login_admin(client, admin_user)
    resp = client.get("/admin/signoff-templates/new")
    assert resp.status_code == 200


def test_create_template_happy_path(app, client, admin_user):
    _login_admin(client, admin_user)
    resp = client.post(
        "/admin/signoff-templates/new",
        data={
            "name": "happy-template",
            "primary_color_hex": "#c41e3a",
            "accent_color_hex": "#1a1a1a",
            "columns_to_show": ["time", "duration", "project"],
            "show_billable": "on",
            "show_daily_totals": "on",
            "signature_block_label": "Client Approval",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    with app.app_context():
        row = TimesheetSignoffTemplate.query.filter_by(name="happy-template").first()
        assert row is not None
        assert row.primary_color_hex == "#c41e3a"
        assert row.show_billable is True


def test_create_template_missing_name_rerenders(client, admin_user):
    _login_admin(client, admin_user)
    resp = client.post(
        "/admin/signoff-templates/new",
        data={"name": "", "primary_color_hex": "#c41e3a"},
        follow_redirects=False,
    )
    # Form re-renders with error (200 OK)
    assert resp.status_code == 200


def test_update_template(app, client, admin_user):
    with app.app_context():
        t = TimesheetSignoffTemplate(name="to-update", columns_to_show=["time"])
        db.session.add(t)
        db.session.commit()
        tid = t.id

    _login_admin(client, admin_user)
    resp = client.post(
        f"/admin/signoff-templates/{tid}",
        data={
            "name": "updated-name",
            "primary_color_hex": "#0066cc",
            "accent_color_hex": "#1a1a1a",
            "columns_to_show": ["time", "duration"],
            "signature_block_label": "Approved",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    with app.app_context():
        refreshed = TimesheetSignoffTemplate.query.get(tid)
        assert refreshed.name == "updated-name"
        assert refreshed.primary_color_hex == "#0066cc"


def test_archive_then_restore(app, client, admin_user):
    with app.app_context():
        t = TimesheetSignoffTemplate(name="archive-me", columns_to_show=["time"])
        db.session.add(t)
        db.session.commit()
        tid = t.id

    _login_admin(client, admin_user)
    client.post(f"/admin/signoff-templates/{tid}/archive")
    with app.app_context():
        assert TimesheetSignoffTemplate.query.get(tid).archived_at is not None

    client.post(f"/admin/signoff-templates/{tid}/restore")
    with app.app_context():
        assert TimesheetSignoffTemplate.query.get(tid).archived_at is None


def test_preview_returns_pdf(app, client, admin_user):
    with app.app_context():
        t = TimesheetSignoffTemplate(
            name="preview-me",
            columns_to_show=["time", "duration", "project", "task", "notes"],
        )
        db.session.add(t)
        db.session.commit()
        tid = t.id

    _login_admin(client, admin_user)
    resp = client.get(f"/admin/signoff-templates/{tid}/preview")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data.startswith(b"%PDF-")


def test_upload_logo_creates_asset(app, client, admin_user):
    _login_admin(client, admin_user)
    # Minimal valid PNG (1x1 transparent)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xfc\xff"
        b"\xff?\x00\x05\xfe\x02\xfe\xdc\xcc\x59\xe7\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    resp = client.post(
        "/admin/branding-assets/upload",
        data={
            "kind": "logo",
            "name": "test-logo",
            "file": (io.BytesIO(png_bytes), "test.png"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["kind"] == "logo"
    assert body["original_filename"] == "test.png"

    with app.app_context():
        asset = BrandingAsset.query.get(body["id"])
        assert asset is not None
        assert asset.kind == "logo"


def test_upload_rejects_bad_extension(client, admin_user):
    _login_admin(client, admin_user)
    resp = client.post(
        "/admin/branding-assets/upload",
        data={
            "kind": "logo",
            "name": "evil",
            "file": (io.BytesIO(b"#!/bin/sh\nrm -rf /\n"), "evil.sh"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_upload_rejects_invalid_kind(client, admin_user):
    _login_admin(client, admin_user)
    resp = client.post(
        "/admin/branding-assets/upload",
        data={
            "kind": "executable",
            "name": "x",
            "file": (io.BytesIO(b"\x00"), "x.bin"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
