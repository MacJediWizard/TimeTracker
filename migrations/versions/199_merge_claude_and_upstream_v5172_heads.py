"""Merge the fork's Claude head with upstream's v5.17.2 head into one.

185_merge_claude_usage_and_upstream_heads (the fork's Claude-usage branch tip)
and 198_add_oauth_applications (the tip of upstream's chain through v5.17.2) were
left as two independent Alembic heads after merging upstream v5.17.2 into the
fork, which breaks `flask db upgrade`. This no-op merge rejoins them into a
single head without renumbering either branch.

Revision ID: 199_merge_claude_and_upstream_v5172_heads
Revises: 185_merge_claude_usage_and_upstream_heads, 198_add_oauth_applications
"""

revision = "199_merge_claude_and_upstream_v5172_heads"
down_revision = (
    "185_merge_claude_usage_and_upstream_heads",
    "198_add_oauth_applications",
)
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
