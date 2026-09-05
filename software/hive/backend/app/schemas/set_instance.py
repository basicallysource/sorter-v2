from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SetInstanceCreateRequest(BaseModel):
    set_num: str = Field(min_length=1)
    label: str | None = None
    include_spares: bool = False
    notes: str | None = None


class SetInstanceUpdateRequest(BaseModel):
    label: str | None = None
    notes: str | None = None
    status: Literal["open", "complete"] | None = None


class SetInstancePartAdjustRequest(BaseModel):
    quantity_found: int = Field(ge=0)


class SetInstanceSetMetaResponse(BaseModel):
    name: str | None
    year: int | None
    num_parts: int | None
    img_url: str | None


class SetInstanceSummaryResponse(BaseModel):
    id: UUID
    set_source: str
    set_num: str
    label: str
    status: str
    include_spares: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime
    set_meta: SetInstanceSetMetaResponse
    part_count: int
    total_needed: int
    total_found: int
    pct: float
    progress_updated_at: datetime | None


class SetInstancePartResponse(BaseModel):
    part_num: str
    color_id: int
    part_name: str | None
    color_name: str | None
    img_url: str | None
    quantity_needed: int
    quantity_found: int
    quantity_missing: int
    updated_at: datetime | None


class SetInstanceDetailResponse(SetInstanceSummaryResponse):
    parts: list[SetInstancePartResponse]
