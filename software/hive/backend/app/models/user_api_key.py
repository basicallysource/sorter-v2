import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base, JSON_VARIANT


class UserApiKey(Base):
    __tablename__ = "user_api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    token_prefix = Column(String, nullable=False)
    token_hash = Column(String, nullable=False, unique=True)
    scopes = Column(JSON_VARIANT, nullable=True)
    # Optional machine whitelist (list of machine UUID strings). Null = no
    # constraint. When set, the key can only touch machine-owned data (samples,
    # pieces, crops) belonging to these machines — enforced in
    # services/access_window.py for every role, so a constrained key is always
    # strictly less powerful than its owner.
    machine_ids = Column(JSON_VARIANT, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")

    __table_args__ = (
        Index("ix_user_api_keys_user_id", "user_id"),
        Index("ix_user_api_keys_token_hash", "token_hash"),
    )
