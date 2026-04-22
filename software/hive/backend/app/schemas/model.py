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


class DetectionModelVariantUploadResponse(BaseModel):
    id: UUID
    runtime: str
    file_name: str
    file_size: int
    sha256: str
