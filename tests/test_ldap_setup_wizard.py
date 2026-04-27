"""Tests for LDAP setup wizard admin routes."""

from __future__ import annotations

from unittest.mock import patch


def test_ldap_setup_wizard_requires_login(client):
    resp = client.get("/admin/ldap/setup-wizard", follow_redirects=False)
    assert resp.status_code in (302, 401)


def test_ldap_setup_wizard_get_as_admin(admin_authenticated_client):
    resp = admin_authenticated_client.get("/admin/ldap/setup-wizard")
    assert resp.status_code == 200
    assert b"LDAP Setup Wizard" in resp.data


def test_ldap_wizard_validate_missing_host(admin_authenticated_client):
    resp = admin_authenticated_client.post(
        "/admin/ldap/setup-wizard/validate-config",
        json={"AUTH_METHOD": "ldap"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["valid"] is False
    assert any(e.get("field") == "LDAP_HOST" for e in body.get("errors", []))


def test_ldap_wizard_validate_invalid_auth_method(admin_authenticated_client):
    resp = admin_authenticated_client.post(
        "/admin/ldap/setup-wizard/validate-config",
        json={
            "LDAP_HOST": "ldap.example.com",
            "LDAP_BIND_DN": "cn=reader,dc=example,dc=com",
            "LDAP_BIND_PASSWORD": "x",
            "LDAP_BASE_DN": "dc=example,dc=com",
            "LDAP_USER_LOGIN_ATTR": "uid",
            "AUTH_METHOD": "oidc",
        },
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["valid"] is False


def test_ldap_wizard_validate_ok(admin_authenticated_client):
    resp = admin_authenticated_client.post(
        "/admin/ldap/setup-wizard/validate-config",
        json={
            "LDAP_HOST": "ldap.example.com",
            "LDAP_BIND_DN": "cn=reader,dc=example,dc=com",
            "LDAP_BIND_PASSWORD": "secret",
            "LDAP_BASE_DN": "dc=example,dc=com",
            "LDAP_USER_LOGIN_ATTR": "uid",
            "AUTH_METHOD": "all",
        },
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["valid"] is True
    assert body["errors"] == []


def test_ldap_wizard_generate_rejects_non_ldap_auth(admin_authenticated_client):
    resp = admin_authenticated_client.post(
        "/admin/ldap/setup-wizard/generate-config",
        json={
            "AUTH_METHOD": "oidc",
            "LDAP_HOST": "ldap.example.com",
            "LDAP_BIND_DN": "cn=x",
            "LDAP_BIND_PASSWORD": "p",
            "LDAP_BASE_DN": "dc=x",
        },
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_ldap_wizard_generate_success(admin_authenticated_client):
    payload = {
        "AUTH_METHOD": "ldap",
        "LDAP_HOST": "ldap.example.com",
        "LDAP_PORT": 636,
        "LDAP_USE_SSL": True,
        "LDAP_USE_TLS": False,
        "LDAP_BIND_DN": "cn=reader,dc=example,dc=com",
        "LDAP_BIND_PASSWORD": "s3cret",
        "LDAP_BASE_DN": "dc=example,dc=com",
        "LDAP_USER_DN": "ou=users",
        "LDAP_USER_OBJECT_CLASS": "inetOrgPerson",
        "LDAP_USER_LOGIN_ATTR": "uid",
        "LDAP_USER_EMAIL_ATTR": "mail",
        "LDAP_USER_FNAME_ATTR": "givenName",
        "LDAP_USER_LNAME_ATTR": "sn",
        "LDAP_GROUP_DN": "ou=groups",
        "LDAP_GROUP_OBJECT_CLASS": "groupOfNames",
        "LDAP_ADMIN_GROUP": "admins",
        "LDAP_REQUIRED_GROUP": "",
        "LDAP_TLS_CA_CERT_FILE": "",
        "LDAP_TIMEOUT": 15,
    }
    resp = admin_authenticated_client.post(
        "/admin/ldap/setup-wizard/generate-config",
        json=payload,
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert "AUTH_METHOD=ldap" in body["env_content"]
    assert "LDAP_HOST=ldap.example.com" in body["env_content"]
    assert "LDAP_USE_SSL=true" in body["env_content"]
    assert "LDAP_USE_TLS=false" in body["env_content"]
    assert "LDAP_BIND_PASSWORD=s3cret" in body["env_content"]
    assert "LDAP_PORT=636" in body["env_content"]
    assert "- LDAP_HOST=" in body["docker_compose_content"]


def test_ldap_wizard_generate_requires_host(admin_authenticated_client):
    resp = admin_authenticated_client.post(
        "/admin/ldap/setup-wizard/generate-config",
        json={
            "AUTH_METHOD": "ldap",
            "LDAP_HOST": "",
            "LDAP_BIND_DN": "cn=x",
            "LDAP_BIND_PASSWORD": "p",
            "LDAP_BASE_DN": "dc=x",
        },
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_ldap_wizard_test_connection_uses_service(admin_authenticated_client):
    fake = {"success": True, "message": "Connected successfully", "user_count": 2}
    with patch("app.services.ldap_service.LDAPService.test_connection", return_value=fake) as m:
        resp = admin_authenticated_client.post(
            "/admin/ldap/setup-wizard/test-connection",
            json={
                "LDAP_HOST": "ldap.internal",
                "LDAP_PORT": 389,
                "LDAP_BIND_DN": "cn=x,dc=y",
                "LDAP_BIND_PASSWORD": "pw",
                "LDAP_BASE_DN": "dc=y",
            },
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert resp.get_json() == fake
    assert m.called
    cfg_arg = m.call_args[0][0]
    assert cfg_arg["LDAP_HOST"] == "ldap.internal"
    assert cfg_arg["LDAP_BIND_PASSWORD"] == "pw"


def test_ldap_service_test_connection_accepts_cfg(app):
    """Explicit cfg dict is used instead of live app config when provided."""
    from app.services.ldap_service import LDAPService

    cfg = {
        "LDAP_HOST": "draft.example",
        "LDAP_PORT": 389,
        "LDAP_USE_SSL": False,
        "LDAP_USE_TLS": False,
        "LDAP_BIND_DN": "",
        "LDAP_BIND_PASSWORD": "",
        "LDAP_BASE_DN": "dc=x",
        "LDAP_USER_DN": "",
        "LDAP_USER_OBJECT_CLASS": "inetOrgPerson",
        "LDAP_TIMEOUT": 1,
    }
    with app.app_context():
        with patch("app.services.ldap_service._service_connection", return_value=None):
            result = LDAPService.test_connection(cfg)
    assert result["success"] is False
    assert "Could not create LDAP connection" in result["message"]
