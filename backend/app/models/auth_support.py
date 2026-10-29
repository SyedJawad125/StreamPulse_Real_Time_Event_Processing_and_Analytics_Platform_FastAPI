# app/models/auth_support.py
"""Supporting tables: revoked JWTs (logout) and HTTP idempotency records."""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


class RevokedToken(Base):
    """JWT denylist. Rows are purged once the token would have expired anyway."""

    __tablename__ = "revoked_tokens"

    jti = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_revoked_tokens_expires_at", "expires_at"),)


class IdempotencyRecord(Base):
    """Stored response for an `Idempotency-Key` header (request-level idempotency)."""

    __tablename__ = "idempotency_records"

    id = Column(BigInteger, primary_key=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False)
    key = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False)
    response_status = Column(Integer, nullable=False)
    response_body = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("api_key_id", "key", name="uq_idempotency_records_api_key_id_key"),
        Index("ix_idempotency_records_created_at", "created_at"),
    )
