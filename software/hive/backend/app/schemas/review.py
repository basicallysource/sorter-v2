from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ReviewCreate(BaseModel):
    decision: str
    notes: str | None = None


class ReviewResponse(BaseModel):
    id: UUID
    sample_id: UUID
    reviewer_id: UUID
    reviewer_display_name: str | None = None
    decision: str
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReviewHistoryResponse(BaseModel):
    reviews: list[ReviewResponse]
    sample_id: UUID
    review_status: str
