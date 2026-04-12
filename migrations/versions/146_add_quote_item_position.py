"""Add position column to quote_items for line order

Revision ID: 146_add_quote_item_position
Revises: 145_add_quotes_requires_approval
Create Date: 2026-04-12

Idempotent: safe if column already exists.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision = "146_add_quote_item_position"
down_revision = "145_add_quotes_requires_approval"
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

    if not _has_column(inspector, "quote_items", "position"):
        op.add_column(
            "quote_items",
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        )

    # Backfill: stable order per quote (by id) -> 0, 1, 2, ...
    connection = op.get_bind()
    quote_ids = connection.execute(text("SELECT DISTINCT quote_id FROM quote_items ORDER BY quote_id")).fetchall()
    for (quote_id,) in quote_ids:
        rows = connection.execute(
            text("SELECT id FROM quote_items WHERE quote_id = :qid ORDER BY id"),
            {"qid": quote_id},
        ).fetchall()
        for pos, (item_id,) in enumerate(rows):
            connection.execute(
                text("UPDATE quote_items SET position = :pos WHERE id = :iid"),
                {"pos": pos, "iid": item_id},
            )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_table(inspector, "quote_items"):
        return

    if _has_column(inspector, "quote_items", "position"):
        op.drop_column("quote_items", "position")
