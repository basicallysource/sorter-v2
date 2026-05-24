from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ReviewCreate(BaseModel):
    decision: str
    notes: str | None = None


class ConditionTagRequest(BaseModel):
    """Human-tagged condition-sample judgement.

    Mirrors the cond_primary analysis schema so the writer can take the
    fields straight through. Flag values are booleans; the frontend sends
    only the flags the operator actually toggled on (omitted == false).
    """

    composition: str = Field(..., description="single_part | compound_part | multi_part | empty_or_not_lego | uncertain")
    condition: str = Field(..., description="clean_ok | minor_wear | dirty | damaged | scratched | broken | trash_candidate | uncertain")
    flags: dict[str, bool] = Field(default_factory=dict)
    visible_evidence: str | None = None
    part_count_estimate: int | None = None
    issues: list[str] = Field(default_factory=list)


class ConditionTagResponse(BaseModel):
    sample_id: UUID
    analysis: dict[str, Any]
    review_status: str
    written_by: UUID


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
