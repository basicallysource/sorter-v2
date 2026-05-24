"""TeacherPrompt — per-zone, per-adapter-kind prompt template that the admin can edit.

Rows are looked up by (zone, kind). When a row is missing the call site falls back to
the hardcoded default baked into the adapter, so the table is purely additive — empty
table behaves identically to pre-feature code.

Chat-kind prompts may contain ``{width}`` / ``{height}`` placeholders that the resolver
substitutes per image at call time. Perceptron-kind prompts are static instructions and
should not use placeholders.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.models import Base


class TeacherPrompt(Base):
    __tablename__ = "teacher_prompts"

    id: UUID = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    zone: str = Column(String, nullable=False)
    kind: str = Column(String, nullable=False)  # 'chat' | 'perceptron'
    content: str = Column(Text, nullable=False)
    updated_at: datetime = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by_id: UUID | None = Column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (UniqueConstraint("zone", "kind", name="uq_teacher_prompts_zone_kind"),)
