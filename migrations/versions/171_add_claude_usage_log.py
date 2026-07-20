"""Add claude_usage_logs table for per-user Claude API usage / cost metering.

Revision ID: 171_add_claude_usage_log
Revises: 170_add_kanban_board_templates
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "171_add_claude_usage_log"
down_revision = "170_add_kanban_board_templates"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    try:
        return table_name in inspector.get_table_names()
    except Exception:
        return False


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if _has_table(inspector, "claude_usage_logs"):
        return
    op.create_table(
        "claude_usage_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("operation", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=50), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_claude_usage_logs_user_id", "claude_usage_logs", ["user_id"])
    op.create_index("ix_claude_usage_logs_operation", "claude_usage_logs", ["operation"])
    op.create_index("ix_claude_usage_logs_created_at", "claude_usage_logs", ["created_at"])


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if not _has_table(inspector, "claude_usage_logs"):
        return
    op.drop_index("ix_claude_usage_logs_created_at", table_name="claude_usage_logs")
    op.drop_index("ix_claude_usage_logs_operation", table_name="claude_usage_logs")
    op.drop_index("ix_claude_usage_logs_user_id", table_name="claude_usage_logs")
    op.drop_table("claude_usage_logs")
