"""Add AI helper settings.

Revision ID: 151_add_ai_helper_settings
Revises: 150_add_smart_notifications
Create Date: 2026-04-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "151_add_ai_helper_settings"
down_revision = "150_add_smart_notifications"
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
    if "settings" not in inspector.get_table_names():
        return

    columns = [
        ("ai_enabled", sa.Column("ai_enabled", sa.Boolean(), nullable=True)),
        ("ai_provider", sa.Column("ai_provider", sa.String(length=50), nullable=True)),
        ("ai_base_url", sa.Column("ai_base_url", sa.String(length=500), nullable=True)),
        ("ai_model", sa.Column("ai_model", sa.String(length=120), nullable=True)),
        ("ai_api_key", sa.Column("ai_api_key", sa.String(length=500), nullable=True)),
        ("ai_timeout_seconds", sa.Column("ai_timeout_seconds", sa.Integer(), nullable=True)),
        ("ai_context_limit", sa.Column("ai_context_limit", sa.Integer(), nullable=True)),
        ("ai_system_prompt", sa.Column("ai_system_prompt", sa.Text(), nullable=True)),
    ]
    for name, column in columns:
        if not _has_column(inspector, "settings", name):
            op.add_column("settings", column)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "settings" not in inspector.get_table_names():
        return

    for name in (
        "ai_system_prompt",
        "ai_context_limit",
        "ai_timeout_seconds",
        "ai_api_key",
        "ai_model",
        "ai_base_url",
        "ai_provider",
        "ai_enabled",
    ):
        if _has_column(inspector, "settings", name):
            op.drop_column("settings", name)
