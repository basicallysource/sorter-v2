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
    # Made on save when left out.
    id: str | None = None
    field: str
    op: str
    value: Any


class SortingProfileRuleResponse(BaseModel):
    id: str
    rule_type: str = "filter"
    name: str
    match_mode: str = "all"
    # Takes the opposite of what its conditions and groups say: with "any",
    # none of them; with "all", not all of them.
    negate: bool = False
    conditions: list[SortingProfileConditionResponse] = Field(default_factory=list)
    children: list["SortingProfileRuleResponse"] = Field(default_factory=list)
    disabled: bool = False
    # Set-specific fields (only used when rule_type == "set")
    set_source: str | None = None
    set_num: str | None = None
    include_spares: bool = False
    set_meta: dict[str, Any] | None = None
    custom_parts: list[dict[str, Any]] = Field(default_factory=list)
    # Kit rules (rule_type == "kit"): the kit whose parts this rule collects.
    kit_id: str | None = None
    # A picture for the rule's bin. Without one, pages show its best known part.
    image_url: str | None = None


class SortingProfileFallbackModeResponse(BaseModel):
    rebrickable_categories: bool = False
    bricklink_categories: bool = False
    by_color: bool = False
    # When a piece's category has no bin and none is free: "misc" (the default
    # bin, never stop), "share" (the least filled bin takes the category too),
    # or None (the machine's own setting, which stops and asks by default).
    no_bin: str | None = None


class SortingProfileForkSourceResponse(BaseModel):
    profile_id: UUID
    profile_name: str
    version_number: int | None = None


class SortingProfileRuleSummaryResponse(BaseModel):
    """Compact rule representation for profile list cards."""
    name: str
    rule_type: str = "filter"
    set_source: str | None = None
    set_num: str | None = None
    set_meta: dict[str, Any] | None = None
    disabled: bool = False
    condition_count: int = 0
    child_count: int = 0


class SortingProfileBinSummaryResponse(BaseModel):
    """One of a version's first bins, for a card that shows a profile by them."""

    id: str
    name: str | None = None
    kind: str | None = None
    image_url: str | None = None
    rgb: str | None = None
    part_count: int | None = None


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
    rules_summary: list[SortingProfileRuleSummaryResponse] = Field(default_factory=list)
    # The first bins in order (versions compiled before bins had pictures have none).
    bins: list[SortingProfileBinSummaryResponse] = Field(default_factory=list)
    # "web", "api", "assistant" or "system", and the API key's name for "api".
    created_via: str | None = None
    created_via_key_name: str | None = None
    # What a sorter must be able to run for this version ("color_fallback").
    requires: list[str] = Field(default_factory=list)


class SortingProfileVersionResponse(SortingProfileVersionSummaryResponse):
    name: str
    description: str | None
    default_category_id: str
    rules: list[SortingProfileRuleResponse]
    fallback_mode: SortingProfileFallbackModeResponse
    compiled_stats: dict[str, Any] | None = None
    # Each bin the profile fills: name, picture, its conditions in words, how
    # many parts it takes and a few of them. category_order is the order to
    # show them in.
    categories: dict[str, dict[str, Any]] = Field(default_factory=dict)
    category_order: list[str] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class SortingProfileSummaryResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    visibility: str
    profile_type: str = "rule"
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
    # A profile Hive keeps and gives every machine.
    is_default: bool = False
    default_rank: int | None = None
    # The profile's page on this Hive.
    web_url: str | None = None
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
    # The first version's rules and fallback; an empty profile without them.
    rules: list["SortingProfileRuleResponse"] = Field(default_factory=list)
    fallback_mode: "SortingProfileFallbackModeResponse | None" = None
    default_category_id: str = "misc"
    change_note: str | None = None


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


class SortingProfileChangeNoteSuggestRequest(BaseModel):
    old_rules: list[dict[str, Any]] = Field(default_factory=list)
    new_rules: list[dict[str, Any]] = Field(default_factory=list)


class SortingProfileChangeNoteSuggestResponse(BaseModel):
    change_note: str


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


class SortingProfileHeadResponse(BaseModel):
    """Enough to tell whether a page showing a profile is out of date."""

    profile_id: UUID
    name: str
    updated_at: datetime
    latest_version_id: UUID | None = None
    latest_version_number: int
    latest_version_created_at: datetime | None = None
    created_via: str | None = None
    created_via_key_name: str | None = None


class SortingProfileRoutePiece(BaseModel):
    # A part by BrickLink ID or Rebrickable number; none for a piece
    # recognition could not identify.
    part: str | None = None
    # Its color: a Rebrickable color ID (as in rule conditions) or a BrickLink
    # color ID; neither means the color is unknown.
    color_id: int | None = None
    bricklink_color_id: int | None = None
    # What the machine would observe (rules on the piece itself): recognition
    # and color confidence, 0 to 100 (100 when left out for an identified
    # piece), and this part's price in this color, in US$ (unknown when left out).
    confidence: float | None = None
    color_confidence: float | None = None
    price: float | None = None


class SortingProfileRouteRequest(BaseModel):
    """Where pieces would go: under a draft document, or a saved version (the
    profile's latest when version_id is left out)."""

    document: SortingProfilePreviewRequest | None = None
    profile_id: UUID | None = None
    version_id: UUID | None = None
    pieces: list[SortingProfileRoutePiece] = Field(..., min_length=1, max_length=200)
    # Kits start empty and fill in the order the pieces are given, as on a
    # machine; false asks where each piece goes with every kit still collecting.
    fill_kits: bool = True


class SortingProfileAiRequest(BaseModel):
    message: str
    version_id: UUID | None = None
    selected_rule_id: str | None = None


class SortingProfileAiApplyRequest(BaseModel):
    label: str | None = None
    change_note: str | None = None
    publish: bool = False


class SortingProfileBricklinkCsvImportRequest(BaseModel):
    csv_content: str
    filename: str | None = None


class AiToolTraceItem(BaseModel):
    tool: str
    input: dict[str, Any]
    output_summary: str
    output: dict[str, Any] | None = None
    duration_ms: float | None = None


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


class SortingProfileSetProgressSetResponse(BaseModel):
    set_num: str
    name: str
    total_needed: int
    total_found: int
    pct: float
    updated_at: datetime | None = None


class SortingProfileSetProgressMachineResponse(BaseModel):
    machine_id: UUID
    machine_name: str
    assignment_id: UUID
    desired_version_id: UUID | None = None
    active_version_id: UUID | None = None
    desired_version_number: int | None = None
    active_version_number: int | None = None
    last_synced_at: datetime | None = None
    last_activated_at: datetime | None = None
    overall_needed: int
    overall_found: int
    overall_pct: float
    updated_at: datetime | None = None
    sets: list[SortingProfileSetProgressSetResponse] = Field(default_factory=list)


class SortingProfileSetProgressResponse(BaseModel):
    profile_id: UUID
    machines: list[SortingProfileSetProgressMachineResponse] = Field(default_factory=list)


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
