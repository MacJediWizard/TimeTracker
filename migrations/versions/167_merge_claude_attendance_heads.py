"""merge fork claude-portal head with upstream attendance/slack head

After syncing upstream (v5.9.0 / v5.9.1 / v5.9.2), the migration graph forked
into two heads again: our fork's ``164_merge_claude_portal_heads`` and
upstream's ``166_add_slack_user_id`` (via the new attendance-compliance and
missed-clock-in migrations ``164_add_attendance_compliance`` /
``165_add_missed_clock_in_notifications``). Both descend from
``163_deleted_usernames_and_portal_only``. This empty merge migration reunites
them into a single head so alembic can continue linearly. Both branches already
applied their own schema changes; this migration is a no-op.

Revision ID: 167_merge_claude_attendance_heads
Revises: 164_merge_claude_portal_heads, 166_add_slack_user_id
Create Date: 2026-07-14

"""

# revision identifiers, used by Alembic.
revision = "167_merge_claude_attendance_heads"
down_revision = (
    "164_merge_claude_portal_heads",
    "166_add_slack_user_id",
)
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
