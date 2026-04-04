from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ProfileOwnerResponse(BaseModel):
    id: UUID
    display_name: str | None
    github_login: str | None = None
    avatar_url: str | None = None


class SortingProfileConditionResponse(BaseModel):
    id: str
    field: str
    op: str
    value: Any


class SortingProfileRuleResponse(BaseModel):
    id: str
    name: str
    match_mode: str = "all"
    conditions: list[SortingProfileConditionResponse] = Field(default_factory=list)
    children: list["SortingProfileRuleResponse"] = Field(default_factory=list)
    disabled: bool = False


class SortingProfileFallbackModeResponse(BaseModel):
    rebrickable_categories: bool = False
    bricklink_categories: bool = False
    by_color: bool = False


class SortingProfileForkSourceResponse(BaseModel):
    profile_id: UUID
    profile_name: str
    version_number: int | None = None


class SortingProfileVersionSummaryResponse(BaseModel):
    id: UUID
    version_number: int
    label: str | None
    change_note: str | None
    is_published: bool
    compiled_hash: str
    compiled_part_count: int
    coverage_ratio: float | None
    created_at: datetime


class SortingProfileVersionResponse(SortingProfileVersionSummaryResponse):
    name: str
    description: str | None
    default_category_id: str
    rules: list[SortingProfileRuleResponse]
    fallback_mode: SortingProfileFallbackModeResponse
    compiled_stats: dict[str, Any] | None = None
    categories: dict[str, dict[str, str]] = Field(default_factory=dict)


class SortingProfileSummaryResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    visibility: str
    tags: list[str] = Field(default_factory=list)
    latest_version_number: int
    latest_published_version_number: int | None
    library_count: int
    fork_count: int
    created_at: datetime
    updated_at: datetime
    owner: ProfileOwnerResponse
    source: SortingProfileForkSourceResponse | None = None
    saved_in_library: bool = False
    is_owner: bool = False
    latest_version: SortingProfileVersionSummaryResponse | None = None
    latest_published_version: SortingProfileVersionSummaryResponse | None = None


class SortingProfileDetailResponse(SortingProfileSummaryResponse):
    versions: list[SortingProfileVersionSummaryResponse] = Field(default_factory=list)
    current_version: SortingProfileVersionResponse | None = None


class SortingProfileCreateRequest(BaseModel):
    name: str
    description: str | None = None
    visibility: str = "private"
    tags: list[str] = Field(default_factory=list)


class SortingProfileUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    visibility: str | None = None
    tags: list[str] | None = None


class SortingProfileVersionCreateRequest(BaseModel):
    name: str
    description: str | None = None
    default_category_id: str = "misc"
    rules: list[SortingProfileRuleResponse] = Field(default_factory=list)
    fallback_mode: SortingProfileFallbackModeResponse = Field(default_factory=SortingProfileFallbackModeResponse)
    change_note: str | None = None
    label: str | None = None
    publish: bool = False


class SortingProfilePreviewRequest(BaseModel):
    name: str = "Untitled Profile"
    description: str | None = None
    default_category_id: str = "misc"
    rules: list[SortingProfileRuleResponse] = Field(default_factory=list)
    fallback_mode: SortingProfileFallbackModeResponse = Field(default_factory=SortingProfileFallbackModeResponse)


class SortingProfileForkRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    add_to_library: bool = True


class SortingProfileAiRequest(BaseModel):
    message: str
    version_id: UUID | None = None
    selected_rule_id: str | None = None


class SortingProfileAiApplyRequest(BaseModel):
    label: str | None = None
    change_note: str | None = None
    publish: bool = False


class AiToolTraceItem(BaseModel):
    tool: str
    input: dict[str, Any]
    output_summary: str


class SortingProfileAiMessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    model: str | None
    version_id: UUID | None
    applied_version_id: UUID | None
    selected_rule_id: str | None
    usage: dict[str, Any] | None = None
    proposal: dict[str, Any] | None = None
    tool_trace: list[AiToolTraceItem] = []
    applied_at: datetime | None
    created_at: datetime


class SortingProfileCatalogSyncResponse(BaseModel):
    started: bool = True


class SortingProfileArtifactResponse(BaseModel):
    artifact: dict[str, Any]


class MachineProfileAssignmentResponse(BaseModel):
    machine_id: UUID
    profile: SortingProfileSummaryResponse | None = None
    desired_version: SortingProfileVersionSummaryResponse | None = None
    active_version: SortingProfileVersionSummaryResponse | None = None
    artifact_hash: str | None = None
    last_error: str | None = None
    last_synced_at: datetime | None = None
    last_activated_at: datetime | None = None


class MachineProfileAssignmentUpdateRequest(BaseModel):
    profile_id: UUID
    version_id: UUID


class MachineProfileActivationRequest(BaseModel):
    version_id: UUID
    artifact_hash: str | None = None


class MachineProfileLibraryResponse(BaseModel):
    machine_id: UUID
    machine_name: str
    assignment: MachineProfileAssignmentResponse | None = None
    profiles: list[SortingProfileSummaryResponse] = Field(default_factory=list)


SortingProfileRuleResponse.model_rebuild()
