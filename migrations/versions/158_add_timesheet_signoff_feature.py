"""add timesheet signoff feature (branding_assets, templates, signoff requests, e-signature bridge)

Revision ID: 158_add_timesheet_signoff_feature
Revises: 157_add_project_client_created_by
Create Date: 2026-05-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "158_add_timesheet_signoff_feature"
down_revision = "157_add_project_client_created_by"
branch_labels = None
depends_on = None


def _inspector():
    return inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return any(c["name"] == column for c in _inspector().get_columns(table))


def _has_index(table: str, index_name: str) -> bool:
    if not _has_table(table):
        return False
    return any(idx["name"] == index_name for idx in _inspector().get_indexes(table))


def upgrade():
    if not _has_table("branding_assets"):
        op.create_table(
            "branding_assets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("kind", sa.String(length=20), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("file_path", sa.String(length=512), nullable=False),
            sa.Column("mime_type", sa.String(length=64), nullable=True),
            sa.Column("original_filename", sa.String(length=255), nullable=True),
            sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
            sa.Column(
                "uploaded_by",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "uploaded_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
        )
    if not _has_index("branding_assets", "ix_branding_assets_kind"):
        op.create_index("ix_branding_assets_kind", "branding_assets", ["kind"])

    if not _has_table("timesheet_signoff_templates"):
        op.create_table(
            "timesheet_signoff_templates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=120), nullable=False, unique=True),
            sa.Column(
                "is_default",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
            sa.Column("intro_markdown", sa.Text(), nullable=True),
            sa.Column("terms_markdown", sa.Text(), nullable=True),
            sa.Column("columns_to_show", sa.JSON(), nullable=False),
            sa.Column(
                "show_billable",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "show_daily_totals",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "signature_block_label",
                sa.String(length=80),
                nullable=False,
                server_default="Approved by Project Manager",
            ),
            sa.Column(
                "primary_color_hex",
                sa.String(length=7),
                nullable=False,
                server_default="#c41e3a",
            ),
            sa.Column(
                "accent_color_hex",
                sa.String(length=7),
                nullable=False,
                server_default="#1a1a1a",
            ),
            sa.Column(
                "logo_asset_id",
                sa.Integer(),
                sa.ForeignKey("branding_assets.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "logo_position",
                sa.String(length=10),
                nullable=False,
                server_default="left",
            ),
            sa.Column(
                "logo_max_height_pt",
                sa.Float(),
                nullable=False,
                server_default=sa.text("32.0"),
            ),
            sa.Column(
                "logo_opacity",
                sa.Float(),
                nullable=False,
                server_default=sa.text("1.0"),
            ),
            sa.Column("body_font_name", sa.String(length=80), nullable=True),
            sa.Column(
                "body_font_regular_asset_id",
                sa.Integer(),
                sa.ForeignKey("branding_assets.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "body_font_bold_asset_id",
                sa.Integer(),
                sa.ForeignKey("branding_assets.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "body_font_italic_asset_id",
                sa.Integer(),
                sa.ForeignKey("branding_assets.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "body_font_bold_italic_asset_id",
                sa.Integer(),
                sa.ForeignKey("branding_assets.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("display_font_name", sa.String(length=80), nullable=True),
            sa.Column(
                "display_font_regular_asset_id",
                sa.Integer(),
                sa.ForeignKey("branding_assets.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "display_font_bold_asset_id",
                sa.Integer(),
                sa.ForeignKey("branding_assets.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
    if not _has_index("timesheet_signoff_templates", "ix_signoff_templates_default"):
        op.create_index(
            "ix_signoff_templates_default",
            "timesheet_signoff_templates",
            ["is_default"],
        )

    if not _has_column("clients", "signoff_email"):
        op.add_column(
            "clients",
            sa.Column("signoff_email", sa.String(length=255), nullable=True),
        )
    if not _has_column("clients", "signoff_template_id"):
        with op.batch_alter_table("clients") as batch:
            batch.add_column(
                sa.Column(
                    "signoff_template_id",
                    sa.Integer(),
                    sa.ForeignKey(
                        "timesheet_signoff_templates.id",
                        ondelete="SET NULL",
                        name="fk_clients_signoff_template_id",
                    ),
                    nullable=True,
                )
            )

    if not _has_table("esignature_requests"):
        op.create_table(
            "esignature_requests",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "integration_id",
                sa.Integer(),
                sa.ForeignKey("integrations.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("target_type", sa.String(length=64), nullable=False),
            sa.Column("target_id", sa.String(length=64), nullable=False),
            sa.Column("external_id", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("provider_url", sa.String(length=512), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("viewed_at", sa.DateTime(), nullable=True),
            sa.Column("signed_at", sa.DateTime(), nullable=True),
            sa.Column("declined_at", sa.DateTime(), nullable=True),
            sa.Column("decline_reason", sa.Text(), nullable=True),
            sa.Column("signed_document_path", sa.String(length=512), nullable=True),
            sa.Column("audit_certificate_path", sa.String(length=512), nullable=True),
            sa.Column("document_hash", sa.String(length=64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
    if not _has_index("esignature_requests", "ix_esignature_external_id"):
        op.create_index(
            "ix_esignature_external_id", "esignature_requests", ["external_id"]
        )
    if not _has_index("esignature_requests", "ix_esignature_target"):
        op.create_index(
            "ix_esignature_target",
            "esignature_requests",
            ["target_type", "target_id"],
        )
    if not _has_index("esignature_requests", "ix_esignature_status"):
        op.create_index("ix_esignature_status", "esignature_requests", ["status"])

    if not _has_table("timesheet_signoff_requests"):
        op.create_table(
            "timesheet_signoff_requests",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "timesheet_period_id",
                sa.Integer(),
                sa.ForeignKey("timesheet_periods.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "client_id",
                sa.Integer(),
                sa.ForeignKey("clients.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "engineer_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("signer_email", sa.String(length=255), nullable=False),
            sa.Column("signer_name", sa.String(length=255), nullable=True),
            sa.Column(
                "template_id",
                sa.Integer(),
                sa.ForeignKey("timesheet_signoff_templates.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column(
                "esignature_request_id",
                sa.Integer(),
                sa.ForeignKey("esignature_requests.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("total_hours_seconds", sa.Integer(), nullable=True),
            sa.Column(
                "created_by",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("signed_at", sa.DateTime(), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        )

    if not _has_index("timesheet_signoff_requests", "ix_signoff_requests_status"):
        op.create_index(
            "ix_signoff_requests_status",
            "timesheet_signoff_requests",
            ["status"],
        )
    if not _has_index("timesheet_signoff_requests", "ix_signoff_requests_client"):
        op.create_index(
            "ix_signoff_requests_client",
            "timesheet_signoff_requests",
            ["client_id"],
        )
    if not _has_index("timesheet_signoff_requests", "ix_signoff_requests_period"):
        op.create_index(
            "ix_signoff_requests_period",
            "timesheet_signoff_requests",
            ["period_start", "period_end"],
        )
    if not _has_index("timesheet_signoff_requests", "uq_signoff_active"):
        op.execute(
            "CREATE UNIQUE INDEX uq_signoff_active "
            "ON timesheet_signoff_requests "
            "(engineer_user_id, client_id, period_start, period_end) "
            "WHERE cancelled_at IS NULL"
        )


def downgrade():
    if _has_table("timesheet_signoff_requests"):
        op.drop_table("timesheet_signoff_requests")
    if _has_table("esignature_requests"):
        op.drop_table("esignature_requests")
    if _has_column("clients", "signoff_template_id"):
        with op.batch_alter_table("clients") as batch:
            batch.drop_column("signoff_template_id")
    if _has_column("clients", "signoff_email"):
        with op.batch_alter_table("clients") as batch:
            batch.drop_column("signoff_email")
    if _has_table("timesheet_signoff_templates"):
        op.drop_table("timesheet_signoff_templates")
    if _has_table("branding_assets"):
        op.drop_table("branding_assets")
