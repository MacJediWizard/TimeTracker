"""Add users.auth_provider for local / oidc / ldap.

Revision ID: 153_add_user_auth_provider
Revises: 152_add_user_totp_2fa
Create Date: 2026-04-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "153_add_user_auth_provider"
down_revision = "152_add_user_totp_2fa"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    try:
        return column_name in {c["name"] for c in inspector.get_columns(table_name)}
    except Exception:
        return False


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "users" not in inspector.get_table_names():
        return

    if not _has_column(inspector, "users", "auth_provider"):
        op.add_column(
            "users",
            sa.Column(
                "auth_provider",
                sa.String(length=20),
                nullable=False,
                server_default="local",
            ),
        )
    try:
        op.alter_column("users", "auth_provider", server_default=None)
    except Exception:
        pass


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "users" not in inspector.get_table_names():
        return
    if _has_column(inspector, "users", "auth_provider"):
        op.drop_column("users", "auth_provider")
