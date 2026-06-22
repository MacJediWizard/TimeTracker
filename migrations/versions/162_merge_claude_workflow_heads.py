"""merge claude-provider and workflow-templates heads

After syncing upstream (v5.8.3 / v5.8.4), the migration graph forked into two
heads: our fork's ``161_add_claude_provider_settings`` (SOW Claude settings) and
upstream's ``161_add_workflow_templates``. This empty merge migration reunites
them into a single head so alembic can continue linearly. Both branches already
applied their own schema changes; this migration is a no-op.

Revision ID: 162_merge_claude_workflow_heads
Revises: 161_add_claude_provider_settings, 161_add_workflow_templates
Create Date: 2026-06-22

"""

# revision identifiers, used by Alembic.
revision = "162_merge_claude_workflow_heads"
down_revision = ("161_add_claude_provider_settings", "161_add_workflow_templates")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
