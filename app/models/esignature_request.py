"""ESignatureRequest model — the provider-agnostic bridge between a
TimeTracker entity (currently ``TimesheetSignoffRequest``; later quotes,
contracts, etc.) and an e-signature provider submission.

Status flows from the connector's webhook events. Audit-trail capture is
minimal (external_id, audit_certificate_path, document_hash) because the
provider (e.g. DocuSeal) generates the legal Certificate of Completion
and we just store pointers to it."""

import enum
from datetime import datetime

from sqlalchemy import Enum as SQLEnum

from app import db


class ESignatureStatus(str, enum.Enum):
    DRAFT = "draft"
    SENT = "sent"
    VIEWED = "viewed"
    SIGNED = "signed"
    DECLINED = "declined"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ESignatureRequest(db.Model):
    """One request to an e-signature provider. Polymorphic via
    ``(target_type, target_id)`` so any TimeTracker entity can be the
    subject of a signature request without a schema change."""

    __tablename__ = "esignature_requests"

    id = db.Column(db.Integer, primary_key=True)
    integration_id = db.Column(
        db.Integer,
        db.ForeignKey("integrations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_type = db.Column(db.String(64), nullable=False)
    target_id = db.Column(db.String(64), nullable=False)

    external_id = db.Column(db.String(64), nullable=True, index=True)
    status = db.Column(
        SQLEnum(
            ESignatureStatus,
            values_callable=lambda x: [e.value for e in x],
            name="esignature_status",
        ),
        nullable=False,
        default=ESignatureStatus.DRAFT,
        index=True,
    )
    provider_url = db.Column(db.String(512), nullable=True)

    sent_at = db.Column(db.DateTime, nullable=True)
    viewed_at = db.Column(db.DateTime, nullable=True)
    signed_at = db.Column(db.DateTime, nullable=True)
    declined_at = db.Column(db.DateTime, nullable=True)
    decline_reason = db.Column(db.Text, nullable=True)

    signed_document_path = db.Column(db.String(512), nullable=True)
    audit_certificate_path = db.Column(db.String(512), nullable=True)
    document_hash = db.Column(db.String(64), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    integration = db.relationship("Integration")

    __table_args__ = (db.Index("ix_esignature_target", "target_type", "target_id"),)

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            ESignatureStatus.SIGNED,
            ESignatureStatus.DECLINED,
            ESignatureStatus.EXPIRED,
            ESignatureStatus.CANCELLED,
            ESignatureStatus.FAILED,
        )

    def to_dict(self) -> dict:
        status = (
            self.status.value
            if isinstance(self.status, ESignatureStatus)
            else str(self.status)
        )
        return {
            "id": self.id,
            "integration_id": self.integration_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "external_id": self.external_id,
            "status": status,
            "provider_url": self.provider_url,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "viewed_at": self.viewed_at.isoformat() if self.viewed_at else None,
            "signed_at": self.signed_at.isoformat() if self.signed_at else None,
            "declined_at": self.declined_at.isoformat() if self.declined_at else None,
            "decline_reason": self.decline_reason,
            "signed_document_path": self.signed_document_path,
            "audit_certificate_path": self.audit_certificate_path,
            "document_hash": self.document_hash,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<ESignatureRequest {self.id} {self.target_type}:{self.target_id} "
            f"status={self.status}>"
        )
