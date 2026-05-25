"""Branding asset model — uploaded logos and TTF fonts referenced by
``TimesheetSignoffTemplate``. Soft-delete only (no hard delete) so
historical signoff PDFs can be re-rendered or audited."""

from datetime import datetime

from app import db


class BrandingAsset(db.Model):
    """A reusable branding artefact (logo image or TTF font) uploaded by
    an admin and referenced by one or more signoff templates."""

    __tablename__ = "branding_assets"

    KIND_LOGO = "logo"
    KIND_FONT_TTF = "font_ttf"
    VALID_KINDS = (KIND_LOGO, KIND_FONT_TTF)

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    file_path = db.Column(db.String(512), nullable=False)
    mime_type = db.Column(db.String(64), nullable=True)
    original_filename = db.Column(db.String(255), nullable=True)
    file_size_bytes = db.Column(db.BigInteger, nullable=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    archived_at = db.Column(db.DateTime, nullable=True)

    uploader = db.relationship("User", foreign_keys=[uploaded_by])

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "file_path": self.file_path,
            "mime_type": self.mime_type,
            "original_filename": self.original_filename,
            "file_size_bytes": self.file_size_bytes,
            "uploaded_by": self.uploaded_by,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
        }

    def __repr__(self) -> str:
        return f"<BrandingAsset {self.kind}:{self.name}>"
