"""Per-user Claude API usage / cost log.

Append-only record of each billable Claude call made by the SOW feature: which
user triggered it, the operation and model, the token counts reported by the
Anthropic API, and the estimated USD cost. Kept separate from AuditLog because
it is metering data (aggregated for cost reporting), not an entity change trail.
"""

from __future__ import annotations

from app import db
from app.utils.timezone import now_in_app_timezone


class ClaudeUsageLog(db.Model):
    __tablename__ = "claude_usage_logs"

    id = db.Column(db.Integer, primary_key=True)

    # Who triggered the call (SET NULL so usage history survives user deletion).
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    operation = db.Column(db.String(30), nullable=False, index=True)  # 'parse_sow' | 'test_connection'
    model = db.Column(db.String(50), nullable=False)

    input_tokens = db.Column(db.Integer, nullable=False, default=0)
    output_tokens = db.Column(db.Integer, nullable=False, default=0)
    cost_usd = db.Column(db.Numeric(12, 6), nullable=False, default=0)

    created_at = db.Column(db.DateTime, nullable=False, default=now_in_app_timezone, index=True)

    user = db.relationship("User", backref=db.backref("claude_usage_logs", lazy="dynamic"), foreign_keys=[user_id])

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<ClaudeUsageLog {self.operation} {self.model} in={self.input_tokens} out={self.output_tokens}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "operation": self.operation,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": float(self.cost_usd or 0),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
