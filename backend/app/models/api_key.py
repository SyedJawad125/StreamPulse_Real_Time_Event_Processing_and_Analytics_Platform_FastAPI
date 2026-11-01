# app/models/api_key.py
from sqlalchemy import ARRAY, Boolean, Column, DateTime, Integer, String, Text, true

from app.database import Base
from app.models.mixins import TimeUserStampMixin


class APIKey(TimeUserStampMixin, Base):
    """Credential for an event-producing application (independent of dashboard users)."""

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)
    key_prefix = Column(String(16), unique=True, nullable=False)  # non-secret lookup handle
    key_hash = Column(String(64), nullable=False)                 # HMAC-SHA256(pepper, full key)
    customer_id = Column(String(100), nullable=True)              # tenant lock
    scopes = Column(ARRAY(Text), nullable=False)
    is_active = Column(Boolean, server_default=true(), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    rate_limit_per_minute = Column(Integer, nullable=False)
    daily_event_quota = Column(Integer, nullable=True)
