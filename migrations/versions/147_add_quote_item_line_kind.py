"""Add line_kind and optional fields to quote_items (issue #585)

Revision ID: 147_add_quote_item_line_kind
Revises: 146_add_quote_item_position
Create Date: 2026-04-12

Idempotent: safe if columns already exist.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision = "147_add_quote_item_line_kind"
down_revision = "146_add_quote_item_position"
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

    if not _has_table(inspector, "quote_items"):
        return

    if not _has_column(inspector, "quote_items", "line_kind"):
        op.add_column(
            "quote_items",
            sa.Column("line_kind", sa.String(length=20), nullable=False, server_default="item"),
        )

    if not _has_column(inspector, "quote_items", "display_name"):
        op.add_column("quote_items", sa.Column("display_name", sa.String(length=200), nullable=True))

    if not _has_column(inspector, "quote_items", "category"):
        op.add_column("quote_items", sa.Column("category", sa.String(length=50), nullable=True))

    if not _has_column(inspector, "quote_items", "line_date"):
        op.add_column("quote_items", sa.Column("line_date", sa.Date(), nullable=True))

    if not _has_column(inspector, "quote_items", "sku"):
        op.add_column("quote_items", sa.Column("sku", sa.String(length=100), nullable=True))

    connection = op.get_bind()
    connection.execute(text("UPDATE quote_items SET line_kind = 'item' WHERE line_kind IS NULL OR line_kind = ''"))


def downgrade():
    bind = op.get_bind()

    for col in ("sku", "line_date", "category", "display_name", "line_kind"):
        inspector = inspect(bind)
        if not _has_table(inspector, "quote_items"):
            return
        if _has_column(inspector, "quote_items", col):
            op.drop_column("quote_items", col)
