"""Tests for LDAP authentication service and login integration."""

from __future__ import annotations

import re
import tempfile
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.models import User


@pytest.fixture
def ldap_app_config(app_config):
    cfg = dict(app_config)
    cfg["AUTH_METHOD"] = "ldap"
    cfg["LDAP_ENABLED"] = True
    cfg["LDAP_HOST"] = "ldap.test"
    cfg["LDAP_PORT"] = 389
    cfg["LDAP_USE_SSL"] = False
    cfg["LDAP_USE_TLS"] = False
    cfg["LDAP_BIND_DN"] = "cn=svc,dc=example,dc=com"
    cfg["LDAP_BIND_PASSWORD"] = "svc-secret"
    cfg["LDAP_BASE_DN"] = "dc=example,dc=com"
    cfg["LDAP_USER_DN"] = "ou=users"
    cfg["LDAP_USER_OBJECT_CLASS"] = "inetOrgPerson"
    cfg["LDAP_USER_LOGIN_ATTR"] = "uid"
    cfg["LDAP_USER_EMAIL_ATTR"] = "mail"
    cfg["LDAP_USER_FNAME_ATTR"] = "givenName"
    cfg["LDAP_USER_LNAME_ATTR"] = "sn"
    cfg["LDAP_GROUP_DN"] = "ou=groups"
    cfg["LDAP_GROUP_OBJECT_CLASS"] = "groupOfNames"
    cfg["LDAP_ADMIN_GROUP"] = ""
    cfg["LDAP_REQUIRED_GROUP"] = ""
    cfg["LDAP_TLS_CA_CERT_FILE"] = ""
    cfg["LDAP_TIMEOUT"] = 10
    return cfg


@pytest.fixture
def ldap_app(ldap_app_config):
    from app import create_app

    unique_db_path = tempfile.gettempdir() + f"/pytest_ldap_{uuid.uuid4().hex}.sqlite"
    cfg = dict(ldap_app_config)
    cfg["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{unique_db_path}"
    application = create_app(cfg)
    with application.app_context():
        db.create_all()
        from app.models import Role

        for name in ("user", "admin"):
            if not Role.query.filter_by(name=name).first():
                db.session.add(Role(name=name))
        db.session.commit()
    yield application
    with application.app_context():
        db.drop_all()


def _mock_ldap_entry(dn: str, uid: str, mail: str, given: str = "A", sn: str = "B"):
    entry = MagicMock()
    entry.entry_dn = dn
    entry.entry_attributes_as_dict = {
        "uid": [uid],
        "mail": [mail],
        "givenName": [given],
        "sn": [sn],
    }
    return entry


@patch("app.services.ldap_service._service_connection")
@patch("app.services.ldap_service.Connection")
def test_ldap_authenticate_success(mock_conn_cls, mock_svc, ldap_app):
    svc = MagicMock()
    svc.entries = [_mock_ldap_entry("uid=test,ou=users,dc=example,dc=com", "test", "test@example.com")]
    svc.bound = True
    mock_svc.return_value = svc

    user_conn = MagicMock()
    mock_conn_cls.return_value = user_conn

    with ldap_app.app_context():
        from app.services.ldap_service import LDAPService

        u = LDAPService.authenticate("test", "secret")
        assert u is not None
        assert u.email == "test@example.com"
        assert u.auth_provider == "ldap"
        assert User.query.filter_by(email="test@example.com").first() is not None


@patch("app.services.ldap_service._service_connection")
@patch("app.services.ldap_service.Connection")
def test_ldap_authenticate_wrong_password(mock_conn_cls, mock_svc, ldap_app):
    from ldap3.core.exceptions import LDAPBindError

    svc = MagicMock()
    svc.entries = [_mock_ldap_entry("uid=test,ou=users,dc=example,dc=com", "test", "test@example.com")]
    svc.bound = True
    mock_svc.return_value = svc

    mock_conn_cls.side_effect = LDAPBindError("bad")

    with ldap_app.app_context():
        from app.services.ldap_service import LDAPService

        assert LDAPService.authenticate("test", "wrong") is None


@patch("app.services.ldap_service._user_dn_member_of_group")
@patch("app.services.ldap_service._service_connection")
@patch("app.services.ldap_service.Connection")
def test_ldap_required_group_blocks_non_member(mock_conn_cls, mock_svc, mock_member, ldap_app):
    ldap_app.config["LDAP_REQUIRED_GROUP"] = "users"
    mock_member.return_value = False

    svc = MagicMock()
    svc.entries = [_mock_ldap_entry("uid=test,ou=users,dc=example,dc=com", "test", "test@example.com")]
    svc.bound = True
    mock_svc.return_value = svc

    with ldap_app.app_context():
        from app.services.ldap_service import LDAPService

        assert LDAPService.authenticate("test", "secret") is None


@patch("app.services.ldap_service._service_connection")
@patch("app.services.ldap_service.Connection")
def test_ldap_admin_group_grants_admin(mock_conn_cls, mock_svc, ldap_app):
    ldap_app.config["LDAP_ADMIN_GROUP"] = "admins"

    svc1 = MagicMock()
    svc1.entries = [_mock_ldap_entry("uid=adm,ou=users,dc=example,dc=com", "adm", "adm@example.com")]
    svc1.bound = True
    svc2 = MagicMock()
    svc2.bound = True
    mock_svc.side_effect = [svc1, svc2]

    with patch("app.services.ldap_service._user_dn_member_of_group", return_value=True):
        mock_conn_cls.return_value = MagicMock()
        with ldap_app.app_context():
            from app.services.ldap_service import LDAPService

            u = LDAPService.authenticate("adm", "pw")
            assert u is not None
            assert u.role == "admin"


@patch("app.services.ldap_service._service_connection")
@patch("app.services.ldap_service.Connection")
def test_ldap_syncs_attributes_on_relogin(mock_conn_cls, mock_svc, ldap_app):
    svc1 = MagicMock()
    svc1.entries = [_mock_ldap_entry("uid=u1,ou=users,dc=example,dc=com", "u1", "sync@example.com", "Old", "Name")]
    svc1.bound = True
    mock_svc.return_value = svc1
    mock_conn_cls.return_value = MagicMock()

    with ldap_app.app_context():
        from app.services.ldap_service import LDAPService

        u1 = LDAPService.authenticate("u1", "pw")
        assert u1.full_name == "Old Name"

    svc2 = MagicMock()
    svc2.entries = [_mock_ldap_entry("uid=u1,ou=users,dc=example,dc=com", "u1", "sync@example.com", "New", "Name")]
    svc2.bound = True
    mock_svc.return_value = svc2

    with ldap_app.app_context():
        from app.services.ldap_service import LDAPService

        u2 = LDAPService.authenticate("u1", "pw")
        assert u2.full_name == "New Name"


@patch("app.services.ldap_service._service_connection")
def test_ldap_exception_returns_none(mock_svc, ldap_app):
    from ldap3.core.exceptions import LDAPException

    mock_svc.side_effect = LDAPException("network")

    with ldap_app.app_context():
        from app.services.ldap_service import LDAPService

        assert LDAPService.authenticate("x", "y") is None


def test_login_route_ldap_success(client, app):
    app.config["AUTH_METHOD"] = "ldap"
    app.config["LDAP_ENABLED"] = True

    with app.app_context():
        from app.models import Role

        for name in ("user", "admin"):
            if not Role.query.filter_by(name=name).first():
                db.session.add(Role(name=name))
        db.session.commit()
        u = User(username="ldapuser", role="user", email="ldapuser@example.com")
        u.auth_provider = "ldap"
        u.set_password("unused")
        u.is_active = True
        ro = Role.query.filter_by(name="user").first()
        if ro:
            u.roles.append(ro)
        db.session.add(u)
        db.session.commit()

    def fake_authenticate(username, password):
        if username == "ldapuser" and password == "ok":
            with app.app_context():
                return User.query.filter_by(username="ldapuser").first()
        return None

    with patch("app.services.ldap_service.LDAPService.authenticate", staticmethod(fake_authenticate)):
        resp = client.post(
            "/login",
            data={"username": "ldapuser", "password": "ok"},
            follow_redirects=False,
        )
    assert resp.status_code in (302, 303)


def test_login_route_ldap_failure_generic_message(client, app):
    app.config["AUTH_METHOD"] = "ldap"
    app.config["LDAP_ENABLED"] = True

    with patch("app.services.ldap_service.LDAPService.authenticate", staticmethod(lambda u, p: None)):
        resp = client.post(
            "/login",
            data={"username": "nouser", "password": "bad"},
            follow_redirects=False,
        )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    m = re.search(r'data-toast-message="([^"]*)"', body)
    assert m, "expected flash toast in response"
    assert m.group(1) == "Invalid username or password"
    assert "ldap" not in m.group(1).lower()
