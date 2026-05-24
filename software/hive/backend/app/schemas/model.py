from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DetectionModelVariantDetail(BaseModel):
    id: UUID
    runtime: str
    file_name: str
    file_size: int
    sha256: str
    format_meta: dict[str, Any] | None = None
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class DetectionModelSummary(BaseModel):
    id: UUID
    owner_id: UUID | None = None
    slug: str
    version: int
    codename: str | None = None
    name: str
    description: str | None = None
    model_family: str
    scopes: list[str] | None = None
    is_public: bool
    published_at: datetime
    updated_at: datetime
    variant_runtimes: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class DetectionModelDetail(DetectionModelSummary):
    training_metadata: dict[str, Any] | None = None
    variants: list[DetectionModelVariantDetail] = Field(default_factory=list)


class DetectionModelListResponse(BaseModel):
    items: list[DetectionModelSummary]
    total: int
    page: int
    page_size: int
    pages: int


class DetectionModelCreateRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=120)
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    model_family: str = Field(..., min_length=1, max_length=50)
    scopes: list[str] | None = None
    training_metadata: dict[str, Any] | None = None
    is_public: bool = True


class DetectionModelCreateResponse(BaseModel):
    id: UUID
    slug: str
    version: int
    codename: str | None = None


class DetectionModelUpdateRequest(BaseModel):
    """Patch existing model fields. All optional — only provided keys update."""
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    scopes: list[str] | None = None
    training_metadata: dict[str, Any] | None = None
    is_public: bool | None = None
    codename: str | None = Field(
        default=None, min_length=1, max_length=40,
        description="Codename override. Must be unique across all models.",
    )


class DetectionModelVariantUploadResponse(BaseModel):
    id: UUID
    runtime: str
    file_name: str
    file_size: int
    sha256: str
