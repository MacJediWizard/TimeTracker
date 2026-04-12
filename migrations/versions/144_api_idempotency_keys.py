"""Add api_idempotency_keys for safe API write retries

Revision ID: 144_api_idempotency_keys
Revises: 143_add_task_custom_fields
Create Date: 2026-04-05
"""

import sqlalchemy as sa
from alembic import op

revision = "144_api_idempotency_keys"
down_revision = "143_add_task_custom_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "api_idempotency_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("api_token_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=128), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["api_token_id"], ["api_tokens.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("api_token_id", "scope", "key_hash", name="uq_api_idempotency_token_scope_key"),
    )
    op.create_index("ix_api_idempotency_keys_created_at", "api_idempotency_keys", ["created_at"], unique=False)


def downgrade():
    op.drop_index("ix_api_idempotency_keys_created_at", table_name="api_idempotency_keys")
    op.drop_table("api_idempotency_keys")
