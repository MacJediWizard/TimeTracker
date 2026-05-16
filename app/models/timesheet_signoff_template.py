"""TimesheetSignoffTemplate — per-client (or global default) customization
of the client-facing timesheet signoff PDF. Maps to a ``SignoffTemplate``
dataclass at render time and resolves uploaded ``BrandingAsset`` rows for
logo + fonts.

Templates are soft-deleted (``archived_at``) rather than hard-deleted so
signoff requests sent in the past can always be re-rendered with the
exact branding that was used at send time."""

from datetime import datetime

from sqlalchemy import JSON

from app import db


class TimesheetSignoffTemplate(db.Model):
    __tablename__ = "timesheet_signoff_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    is_default = db.Column(db.Boolean, default=False, nullable=False, index=True)
    archived_at = db.Column(db.DateTime, nullable=True)

    intro_markdown = db.Column(db.Text, nullable=True)
    terms_markdown = db.Column(db.Text, nullable=True)
    columns_to_show = db.Column(JSON, nullable=False)
    show_billable = db.Column(db.Boolean, default=False, nullable=False)
    show_daily_totals = db.Column(db.Boolean, default=True, nullable=False)
    signature_block_label = db.Column(
        db.String(80), nullable=False, default="Approved by Project Manager"
    )

    primary_color_hex = db.Column(db.String(7), nullable=False, default="#c41e3a")
    accent_color_hex = db.Column(db.String(7), nullable=False, default="#1a1a1a")

    logo_asset_id = db.Column(
        db.Integer,
        db.ForeignKey("branding_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    logo_position = db.Column(db.String(10), nullable=False, default="left")
    logo_max_height_pt = db.Column(db.Float, nullable=False, default=32.0)
    logo_opacity = db.Column(db.Float, nullable=False, default=1.0)

    body_font_name = db.Column(db.String(80), nullable=True)
    body_font_regular_asset_id = db.Column(
        db.Integer,
        db.ForeignKey("branding_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    body_font_bold_asset_id = db.Column(
        db.Integer,
        db.ForeignKey("branding_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    body_font_italic_asset_id = db.Column(
        db.Integer,
        db.ForeignKey("branding_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    body_font_bold_italic_asset_id = db.Column(
        db.Integer,
        db.ForeignKey("branding_assets.id", ondelete="SET NULL"),
        nullable=True,
    )

    display_font_name = db.Column(db.String(80), nullable=True)
    display_font_regular_asset_id = db.Column(
        db.Integer,
        db.ForeignKey("branding_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    display_font_bold_asset_id = db.Column(
        db.Integer,
        db.ForeignKey("branding_assets.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    logo_asset = db.relationship("BrandingAsset", foreign_keys=[logo_asset_id])
    body_font_regular_asset = db.relationship(
        "BrandingAsset", foreign_keys=[body_font_regular_asset_id]
    )
    body_font_bold_asset = db.relationship(
        "BrandingAsset", foreign_keys=[body_font_bold_asset_id]
    )
    body_font_italic_asset = db.relationship(
        "BrandingAsset", foreign_keys=[body_font_italic_asset_id]
    )
    body_font_bold_italic_asset = db.relationship(
        "BrandingAsset", foreign_keys=[body_font_bold_italic_asset_id]
    )
    display_font_regular_asset = db.relationship(
        "BrandingAsset", foreign_keys=[display_font_regular_asset_id]
    )
    display_font_bold_asset = db.relationship(
        "BrandingAsset", foreign_keys=[display_font_bold_asset_id]
    )

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "is_default": self.is_default,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
            "intro_markdown": self.intro_markdown,
            "terms_markdown": self.terms_markdown,
            "columns_to_show": self.columns_to_show,
            "show_billable": self.show_billable,
            "show_daily_totals": self.show_daily_totals,
            "signature_block_label": self.signature_block_label,
            "primary_color_hex": self.primary_color_hex,
            "accent_color_hex": self.accent_color_hex,
            "logo_asset_id": self.logo_asset_id,
            "logo_position": self.logo_position,
            "logo_max_height_pt": self.logo_max_height_pt,
            "logo_opacity": self.logo_opacity,
            "body_font_name": self.body_font_name,
            "body_font_regular_asset_id": self.body_font_regular_asset_id,
            "body_font_bold_asset_id": self.body_font_bold_asset_id,
            "body_font_italic_asset_id": self.body_font_italic_asset_id,
            "body_font_bold_italic_asset_id": self.body_font_bold_italic_asset_id,
            "display_font_name": self.display_font_name,
            "display_font_regular_asset_id": self.display_font_regular_asset_id,
            "display_font_bold_asset_id": self.display_font_bold_asset_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<TimesheetSignoffTemplate {self.id}:{self.name}>"
