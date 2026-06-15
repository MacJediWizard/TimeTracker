"""merge timesheet-signoff and quote-numbering heads

Revision ID: 160_merge_signoff_quote_heads
Revises: 158_add_timesheet_signoff_feature, 159_add_quote_number_settings
Create Date: 2026-06-15 12:21:23.493856

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "160_merge_signoff_quote_heads"
down_revision = ("158_add_timesheet_signoff_feature", "159_add_quote_number_settings")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
