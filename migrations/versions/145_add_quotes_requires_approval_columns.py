"""Add requires_approval and approval_level to quotes

Revision ID: 145_add_quotes_requires_approval
Revises: 144_api_idempotency_keys
Create Date: 2026-04-12

Idempotent: safe if columns already exist (partial upgrades).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "145_add_quotes_requires_approval"
down_revision = "144_api_idempotency_keys"
branch_labels = None
depends_on = None


def _has_table(inspector, name: str) -> bool:
    try:
        return name in inspector.get_table_names()
    except Exception:
        return False


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    try:
        return column_name in {c["name"] for c in inspector.get_columns(table_name)}
    except Exception:
        return False


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_table(inspector, "quotes"):
        return

    quotes_columns = {c["name"] for c in inspector.get_columns("quotes")}

    if "requires_approval" not in quotes_columns:
        op.add_column(
            "quotes",
            sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    if "approval_level" not in quotes_columns:
        op.add_column(
            "quotes",
            sa.Column("approval_level", sa.Integer(), nullable=False, server_default="1"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_table(inspector, "quotes"):
        return

    if _has_column(inspector, "quotes", "approval_level"):
        op.drop_column("quotes", "approval_level")

    if _has_column(inspector, "quotes", "requires_approval"):
        op.drop_column("quotes", "requires_approval")
