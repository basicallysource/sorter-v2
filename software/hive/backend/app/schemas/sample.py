from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, field_validator


class SampleResponse(BaseModel):
    id: UUID
    machine_id: UUID
    upload_session_id: UUID
    local_sample_id: str
    source_role: str | None
    capture_reason: str | None
    captured_at: datetime | None
    image_width: int | None
    image_height: int | None
    detection_algorithm: str | None
    detection_bboxes: list | None
    detection_count: int | None
    detection_score: float | None
    sample_payload: dict | None
    extra_metadata: dict | None
    review_status: str
    review_count: int
    accepted_count: int
    rejected_count: int
    uploaded_at: datetime
    resolved_at: datetime | None
    # The current viewer's own review decision, populated by the router via a
    # batch lookup so we don't N+1 the SampleReview table per row. Null means
    # the viewer hasn't reviewed this sample yet.
    my_review_decision: str | None = None
    # Exposure stats — populated at upload + via the backfill script for
    # older rows. Null for samples that haven't been backfilled yet.
    luminance_mean: float | None = None
    clipped_low_ratio: float | None = None
    clipped_high_ratio: float | None = None

    model_config = {"from_attributes": True}


class SampleListResponse(BaseModel):
    items: list[SampleResponse]
    total: int
    page: int
    page_size: int
    pages: int


class SampleMachineOwner(BaseModel):
    id: UUID
    display_name: str | None = None
    avatar_url: str | None = None


class SampleMachineSummary(BaseModel):
    id: UUID
    name: str
    owner: SampleMachineOwner | None = None

    @field_validator("owner", mode="before")
    @classmethod
    def _coerce_owner(cls, value: Any) -> Any:
        if value is None or isinstance(value, (SampleMachineOwner, dict)):
            return value
        return {
            "id": getattr(value, "id", None),
            "display_name": getattr(value, "display_name", None),
            "avatar_url": getattr(value, "avatar_url", None),
        }


class SampleDetailResponse(SampleResponse):
    has_full_frame: bool = False
    has_overlay: bool = False
    machine: SampleMachineSummary | None = None

    @field_validator("machine", mode="before")
    @classmethod
    def _coerce_machine(cls, value: Any) -> Any:
        """Bridge SQLAlchemy Machine -> SampleMachineSummary.

        Otherwise ``model_validate(sample)`` walks ``sample.machine`` (a Machine row) and
        pydantic can't tell that maps to the summary schema. Mirrors MachineResponse.owner.
        """
        if value is None or isinstance(value, (SampleMachineSummary, dict)):
            return value
        return {
            "id": getattr(value, "id", None),
            "name": getattr(value, "name", None),
            "owner": getattr(value, "owner", None),
        }


class SavedAnnotationBody(BaseModel):
    id: str | None = None
    purpose: str | None = None
    value: str | None = None


class SavedAnnotationRecord(BaseModel):
    id: str
    source: Literal["primary", "candidate", "manual"]
    shape_type: str
    geometry: dict[str, Any] | None = None
    bodies: list[SavedAnnotationBody] = []


class SampleAnnotationsPayload(BaseModel):
    version: Literal["hive-annotorious-v1"] = "hive-annotorious-v1"
    updated_at: datetime | None = None
    updated_by_display_name: str | None = None
    annotations: list[SavedAnnotationRecord]


class SaveSampleAnnotationsRequest(BaseModel):
    version: Literal["hive-annotorious-v1"] = "hive-annotorious-v1"
    annotations: list[SavedAnnotationRecord]


class SaveSampleAnnotationsResponse(BaseModel):
    ok: bool
    annotation_count: int
    data: SampleAnnotationsPayload


class SampleClassificationPayload(BaseModel):
    version: Literal["hive-classification-v1"] = "hive-classification-v1"
    updated_at: datetime | None = None
    updated_by_display_name: str | None = None
    part_id: str | None = None
    item_name: str | None = None
    color_id: str | None = None
    color_name: str | None = None


class SaveSampleClassificationRequest(BaseModel):
    part_id: str | None = None
    item_name: str | None = None
    color_id: str | None = None
    color_name: str | None = None


class SaveSampleClassificationResponse(BaseModel):
    ok: bool
    cleared: bool = False
    data: SampleClassificationPayload | None = None


class BatchDeleteSamplesRequest(BaseModel):
    """Filter spec mirroring the /api/samples query params.

    Always interpreted as 'samples I own' on the server side — the client
    cannot widen the deletion to other users' rigs. Optional knobs:
      - ``dry_run`` returns just the count without deleting (used by the
        confirmation dialog to show how many will be removed).
      - ``max_delete`` is a soft cap; if the matched set exceeds it the
        endpoint refuses with a 400 so the operator narrows the filter
        before pressing the button.
    """

    machine_id: str | None = None
    source_role: str | None = None
    capture_reason: str | None = None
    review_status: str | None = None
    kind: str | None = None  # 'regular' | 'condition' | None
    max_age_hours: int | None = None
    dry_run: bool = False
    max_delete: int = 5000


class BatchDeleteSamplesResponse(BaseModel):
    ok: bool
    matched: int
    deleted: int
    dry_run: bool
    capped: bool = False


class BatchArchiveSamplesRequest(BaseModel):
    """Admin-only soft-delete. Same filter spec as BatchDeleteSamplesRequest
    but the target set is the *full library* (no ownership constraint) —
    admins manage the global content surface.
    """

    machine_id: str | None = None
    source_role: str | None = None
    capture_reason: str | None = None
    review_status: str | None = None
    kind: str | None = None
    max_age_hours: int | None = None
    archived: str | None = None  # 'active' | 'archived' | 'all' (for unarchive flow)
    dry_run: bool = False
    max_archive: int = 20000


class BatchArchiveSamplesResponse(BaseModel):
    ok: bool
    matched: int
    archived: int
    dry_run: bool
    capped: bool = False
