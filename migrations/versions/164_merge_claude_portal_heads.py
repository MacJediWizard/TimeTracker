"""merge fork claude-workflow head with upstream invoice-group/portal head

After syncing upstream (v5.8.5 / v5.8.6), the migration graph forked into two
heads: our fork's ``162_merge_claude_workflow_heads`` and upstream's
``163_deleted_usernames_and_portal_only`` (via ``162_add_invoice_group_time_entries_setting``).
This empty merge migration reunites them into a single head so alembic can
continue linearly. Both branches already applied their own schema changes; this
migration is a no-op.

Revision ID: 164_merge_claude_portal_heads
Revises: 162_merge_claude_workflow_heads, 163_deleted_usernames_and_portal_only
Create Date: 2026-07-01

"""

# revision identifiers, used by Alembic.
revision = "164_merge_claude_portal_heads"
down_revision = (
    "162_merge_claude_workflow_heads",
    "163_deleted_usernames_and_portal_only",
)
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
