from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


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
    codename_color: str | None = None  # hex, derived from codename via codenames.color_for
    name: str
    description: str | None = None
    model_family: str
    scopes: list[str] | None = None
    is_public: bool
    experimental: bool = False
    published_at: datetime
    updated_at: datetime
    variant_runtimes: list[str] = Field(default_factory=list)
    # Included on Summary so the /models list page can render metric pills
    # without a second round-trip per row. Same blob as Detail.
    training_metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _fill_codename_color(self):
        if self.codename and not self.codename_color:
            # Lazy import to avoid pulling the color table into module init.
            from app.services.codenames import color_for
            self.codename_color = color_for(self.codename)
        return self

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
    experimental: bool = False


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
    experimental: bool | None = None
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
