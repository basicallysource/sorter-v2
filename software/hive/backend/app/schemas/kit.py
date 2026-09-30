from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.profile import ProfileOwnerResponse


class KitPartInput(BaseModel):
    """One line of a kit. `part` is a Rebrickable part number or a BrickLink
    ID; `color_id` a Rebrickable color ID, or `bricklink_color_id` a BrickLink
    one. Leave both colors out and any color counts toward the line."""

    part: str = Field(..., min_length=1, max_length=64)
    quantity: int = Field(..., ge=1, le=100000)
    color_id: int | None = None
    bricklink_color_id: int | None = None


class KitCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    image_url: str | None = None
    visibility: str = "private"
    parts: list[KitPartInput] = Field(default_factory=list, max_length=5000)


class KitUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    image_url: str | None = None
    visibility: str | None = None
    # Replaces every line when given.
    parts: list[KitPartInput] | None = Field(default=None, max_length=5000)


class KitFromSetRequest(BaseModel):
    set_num: str = Field(..., min_length=1, max_length=40)
    include_spares: bool = False
    name: str | None = None


class KitFromBricklinkCsvRequest(BaseModel):
    csv_content: str
    filename: str | None = None
    name: str | None = None


class KitPartResponse(BaseModel):
    part_num: str
    part_source: str
    bricklink_id: str | None = None
    part_name: str | None = None
    img_url: str | None = None
    # The part's photo, when img_url is a render in the line's color that may not exist.
    fallback_img_url: str | None = None
    # null for any color
    color_id: int | None = None
    bricklink_color_id: int | None = None
    color_name: str | None = None
    rgb: str | None = None
    quantity: int


class KitSummaryResponse(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    image_url: str | None = None
    source: str
    set_num: str | None = None
    set_meta: dict[str, Any] | None = None
    visibility: str
    line_count: int
    total_quantity: int
    any_color_lines: int
    owner: ProfileOwnerResponse
    is_owner: bool
    created_at: datetime
    updated_at: datetime


class KitResponse(KitSummaryResponse):
    parts: list[KitPartResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # Profiles whose latest version collects this kit.
    used_by: list[dict[str, Any]] = Field(default_factory=list)
