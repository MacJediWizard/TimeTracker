"""TimesheetSignoffRequest — one request to a specific client signer for
a specific engineer's time entries during a specific period. Carries the
local feature-level state; ``esignature_request_id`` bridges to the
provider-side state in ``ESignatureRequest``.

Resend after decline / expiry is "cancel old, create new" — the
partial unique index ``uq_signoff_active`` enforces at most one
non-cancelled row per (engineer, client, period_start, period_end)."""

import enum
from datetime import datetime

from sqlalchemy import Enum as SQLEnum

from app import db


class TimesheetSignoffStatus(str, enum.Enum):
    DRAFT = "draft"
    SENT = "sent"
    VIEWED = "viewed"
    SIGNED = "signed"
    DECLINED = "declined"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class TimesheetSignoffRequest(db.Model):
    __tablename__ = "timesheet_signoff_requests"

    id = db.Column(db.Integer, primary_key=True)
    timesheet_period_id = db.Column(
        db.Integer,
        db.ForeignKey("timesheet_periods.id", ondelete="SET NULL"),
        nullable=True,
    )
    client_id = db.Column(
        db.Integer,
        db.ForeignKey("clients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    engineer_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)

    signer_email = db.Column(db.String(255), nullable=False)
    signer_name = db.Column(db.String(255), nullable=True)

    template_id = db.Column(
        db.Integer,
        db.ForeignKey("timesheet_signoff_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status = db.Column(
        SQLEnum(
            TimesheetSignoffStatus,
            values_callable=lambda x: [e.value for e in x],
            name="timesheet_signoff_status",
        ),
        nullable=False,
        default=TimesheetSignoffStatus.DRAFT,
        index=True,
    )
    esignature_request_id = db.Column(
        db.Integer,
        db.ForeignKey("esignature_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    total_hours_seconds = db.Column(db.Integer, nullable=True)

    created_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    sent_at = db.Column(db.DateTime, nullable=True)
    signed_at = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)

    period = db.relationship("TimesheetPeriod", foreign_keys=[timesheet_period_id])
    client = db.relationship("Client", foreign_keys=[client_id])
    engineer = db.relationship("User", foreign_keys=[engineer_user_id])
    template = db.relationship("TimesheetSignoffTemplate")
    esignature_request = db.relationship("ESignatureRequest", foreign_keys=[esignature_request_id])
    creator = db.relationship("User", foreign_keys=[created_by])

    __table_args__ = (db.Index("ix_signoff_requests_period", "period_start", "period_end"),)

    @property
    def is_active(self) -> bool:
        return self.cancelled_at is None

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            TimesheetSignoffStatus.SIGNED,
            TimesheetSignoffStatus.DECLINED,
            TimesheetSignoffStatus.EXPIRED,
            TimesheetSignoffStatus.CANCELLED,
        )

    def to_dict(self) -> dict:
        status = self.status.value if isinstance(self.status, TimesheetSignoffStatus) else str(self.status)
        return {
            "id": self.id,
            "timesheet_period_id": self.timesheet_period_id,
            "client_id": self.client_id,
            "engineer_user_id": self.engineer_user_id,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "signer_email": self.signer_email,
            "signer_name": self.signer_name,
            "template_id": self.template_id,
            "status": status,
            "esignature_request_id": self.esignature_request_id,
            "total_hours_seconds": self.total_hours_seconds,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "signed_at": self.signed_at.isoformat() if self.signed_at else None,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<TimesheetSignoffRequest {self.id} engineer={self.engineer_user_id} "
            f"client={self.client_id} {self.period_start}..{self.period_end} "
            f"status={self.status}>"
        )
