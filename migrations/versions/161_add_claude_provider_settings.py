"""Add Claude API provider settings (SOW auto-provisioning).

Adds a dedicated Claude/Anthropic provider configuration block, independent of
the existing AI helper (Ollama / OpenAI-compatible) settings. Used by the
SOW -> project/kanban auto-provisioning feature.

Revision ID: 161_add_claude_provider_settings
Revises: 160_merge_signoff_quote_heads
Create Date: 2026-06-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "161_add_claude_provider_settings"
down_revision = "160_merge_signoff_quote_heads"
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
        ("claude_enabled", sa.Column("claude_enabled", sa.Boolean(), nullable=True)),
        (
            "claude_api_key",
            sa.Column("claude_api_key", sa.String(length=500), nullable=True),
        ),
        (
            "claude_model",
            sa.Column("claude_model", sa.String(length=120), nullable=True),
        ),
        (
            "claude_effort",
            sa.Column("claude_effort", sa.String(length=20), nullable=True),
        ),
        (
            "claude_timeout_seconds",
            sa.Column("claude_timeout_seconds", sa.Integer(), nullable=True),
        ),
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
        "claude_timeout_seconds",
        "claude_effort",
        "claude_model",
        "claude_api_key",
        "claude_enabled",
    ):
        if _has_column(inspector, "settings", name):
            op.drop_column("settings", name)
