"""Idempotency keys for API write deduplication (e.g. mobile retries)."""

from datetime import datetime

from app import db


class ApiIdempotencyKey(db.Model):
    """Stores completed idempotent API responses per token + scope + key hash."""

    __tablename__ = "api_idempotency_keys"

    id = db.Column(db.Integer, primary_key=True)
    api_token_id = db.Column(db.Integer, db.ForeignKey("api_tokens.id", ondelete="CASCADE"), nullable=False, index=True)
    scope = db.Column(db.String(128), nullable=False)
    key_hash = db.Column(db.String(64), nullable=False)
    response_status = db.Column(db.Integer, nullable=False)
    response_body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint("api_token_id", "scope", "key_hash", name="uq_api_idempotency_token_scope_key"),
    )
