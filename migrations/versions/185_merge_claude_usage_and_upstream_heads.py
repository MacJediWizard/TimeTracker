"""Merge the fork's Claude-usage head with upstream's 184 head into one.

171_add_claude_usage_log (the fork's Claude usage-metering table) and
184_merge_183_heads (the tip of upstream's 171->184 chain) were both authored
off 170_add_kanban_board_templates as independent branches, leaving two Alembic
heads after the upstream v5.13.4 merge and breaking `flask db upgrade`. This
no-op merge rejoins them into a single head without renumbering either branch.

Revision ID: 185_merge_claude_usage_and_upstream_heads
Revises: 171_add_claude_usage_log, 184_merge_183_heads
"""

revision = "185_merge_claude_usage_and_upstream_heads"
down_revision = (
    "171_add_claude_usage_log",
    "184_merge_183_heads",
)
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
