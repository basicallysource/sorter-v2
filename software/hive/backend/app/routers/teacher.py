"""Admin endpoints to (re)run the Gemini teacher across a filtered set of Hive samples."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.deps import get_db, require_role, verify_csrf
from app.errors import APIError
from app.models.sample import Sample
from app.models.teacher_job import TeacherJob, TeacherJobItem
from app.models.teacher_prompt import TeacherPrompt
from app.models.user import User
from app.services.secrets import decrypt_secret
from app.services.teacher_adapters import get_adapter, list_adapters
from app.services.teacher_adapters.base import TeacherAdapter
from app.services.teacher_adapters.perceptron import _zone_instruction as perceptron_zone_instruction
from app.services.teacher_detector import (
    SOURCE_ROLE_TO_ZONE,
    SUPPORTED_OPENROUTER_MODELS,
    DEFAULT_OPENROUTER_MODEL,
    apply_teacher_result_to_sample,
    gemini_prompt,
    normalize_openrouter_model,
    run_teacher_detection,
    zone_for_source_role,
)
from app.services.storage_backend import get_backend
from app.services.teacher_prompts import (
    SUPPORTED_PROMPT_KINDS,
    SUPPORTED_PROMPT_ZONES,
    adapter_kind_for,
    default_template,
    resolve_prompt,
)

from app.config import settings
from app.schemas.sample import SampleDetailResponse
from app.services.teacher_worker import get_teacher_worker


router = APIRouter(prefix="/api/admin/teacher", tags=["teacher"])


SUPPORTED_SOURCE_ROLES: tuple[str, ...] = tuple(sorted(SOURCE_ROLE_TO_ZONE))


def _resolve_adapter_secret(user: User, adapter: TeacherAdapter) -> str:
    """Decrypt and return the right API key for ``adapter`` from ``user``'s profile.

    Each adapter declares ``secret_kind`` (currently "openrouter" or "perceptron"); the
    router picks the matching encrypted column. Raises APIError with a clear message if
    the key is missing so the UI can tell the user where to set it.
    """
    kind = getattr(adapter, "secret_kind", "openrouter")
    if kind == "perceptron":
        key = decrypt_secret(user.perceptron_api_key_encrypted)
        if not key:
            raise APIError(
                400,
                "Set your Perceptron API key on your profile to use this model.",
                "PERCEPTRON_KEY_MISSING",
            )
        return key
    key = decrypt_secret(user.openrouter_api_key_encrypted)
    if not key:
        raise APIError(
            400,
            "Set your OpenRouter API key on your profile to use this model.",
            "OPENROUTER_KEY_MISSING",
        )
    return key


class TeacherJobFilter(BaseModel):
    """Same shape as the samples list filters so the admin can re-run on what they see."""

    scope: str | None = None
    machine_id: UUID | None = None
    upload_session_id: UUID | None = None
    source_role: str | None = None
    capture_reason: str | None = None
    review_status: str | None = None
    max_age_hours: int | None = None


class CreateTeacherJobRequest(BaseModel):
    filter: TeacherJobFilter = Field(default_factory=TeacherJobFilter)
    openrouter_model: str | None = None


class TeacherJobItemSummary(BaseModel):
    id: UUID
    sample_id: UUID
    status: str
    error_message: str | None
    detection_count: int | None
    processed_at: datetime | None


class TeacherJobSummary(BaseModel):
    id: UUID
    owner_id: UUID
    status: str
    openrouter_model: str
    total: int
    processed: int
    succeeded: int
    failed: int
    last_error: str | None
    cost_usd: float
    cost_usd_estimated_total: float | None
    tokens_input: int
    tokens_output: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    filter: dict | None


class TeacherJobDetail(TeacherJobSummary):
    items: list[TeacherJobItemSummary]
    status_counts: dict[str, int]
    items_truncated: bool
    # Pagination metadata for the items page below — kept inline so the existing detail
    # endpoint stays one round-trip per UI refresh.
    items_page: int = 1
    items_page_size: int = 50
    items_total: int = 0
    items_pages: int = 1
    items_status_filter: str | None = None


def _job_to_summary(job: TeacherJob) -> TeacherJobSummary:
    cost_so_far = float(job.cost_usd or 0.0)
    estimated_total: float | None = None
    if job.processed > 0 and job.total > 0 and cost_so_far > 0:
        # Project the running cost-per-item onto the full job. We don't bother with a
        # per-model price table — OpenRouter's billed cost is authoritative, and a
        # running average self-corrects as more samples land.
        estimated_total = cost_so_far / job.processed * job.total
    return TeacherJobSummary(
        id=job.id,
        owner_id=job.owner_id,
        status=job.status,
        openrouter_model=job.openrouter_model,
        total=job.total,
        processed=job.processed,
        succeeded=job.succeeded,
        failed=job.failed,
        last_error=job.last_error,
        cost_usd=cost_so_far,
        cost_usd_estimated_total=estimated_total,
        tokens_input=int(job.tokens_input or 0),
        tokens_output=int(job.tokens_output or 0),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        filter=job.filter_json,
    )


@router.post("/jobs", response_model=TeacherJobSummary)
def create_teacher_job(
    payload: CreateTeacherJobRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
) -> TeacherJobSummary:
    # The job creator's key is what the worker will use for every item in this job, so
    # validate up-front. Default model = Gemini via OpenRouter; if the admin requested a
    # Perceptron job we check the Perceptron key instead.
    requested_model = payload.openrouter_model or admin.preferred_teacher_model
    candidate_model = normalize_openrouter_model(requested_model)
    candidate_adapter = get_adapter(candidate_model)
    if candidate_adapter is not None:
        # Raises 400 with a clear message if the relevant key is missing.
        _resolve_adapter_secret(admin, candidate_adapter)

    filt = payload.filter
    query = db.query(Sample)
    if filt.scope == "mine":
        query = query.filter(Sample.machine.has(owner_id=admin.id))
    if filt.machine_id is not None:
        query = query.filter(Sample.machine_id == filt.machine_id)
    if filt.upload_session_id is not None:
        query = query.filter(Sample.upload_session_id == filt.upload_session_id)
    if filt.source_role:
        query = query.filter(Sample.source_role == filt.source_role)
    if filt.capture_reason:
        query = query.filter(Sample.capture_reason == filt.capture_reason)
    if filt.review_status:
        query = query.filter(Sample.review_status == filt.review_status)
    if filt.max_age_hours is not None and filt.max_age_hours > 0:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=filt.max_age_hours)
        query = query.filter(Sample.uploaded_at >= cutoff)

    # Only enqueue samples whose source_role has a teacher zone — otherwise we'd just burn
    # Gemini credits on the wrong prompt. We also skip rows missing image_path defensively.
    query = query.filter(
        Sample.source_role.in_(SUPPORTED_SOURCE_ROLES),
        Sample.image_path.isnot(None),
    )

    sample_ids = [row[0] for row in query.with_entities(Sample.id).all()]
    if not sample_ids:
        raise APIError(
            400,
            "No samples match the filter (need source_role in: "
            + ", ".join(SUPPORTED_SOURCE_ROLES)
            + ").",
            "TEACHER_JOB_EMPTY",
        )

    # preferred_teacher_model is the user's persisted choice (set on the settings page);
    # falls back to the global default if unset or not in the registry.
    model = normalize_openrouter_model(payload.openrouter_model or admin.preferred_teacher_model)
    if model not in SUPPORTED_OPENROUTER_MODELS:
        model = DEFAULT_OPENROUTER_MODEL

    job = TeacherJob(
        owner_id=admin.id,
        status="pending",
        openrouter_model=model,
        filter_json=payload.filter.model_dump(mode="json", exclude_none=True),
        total=len(sample_ids),
    )
    db.add(job)
    db.flush()

    db.bulk_save_objects(
        [TeacherJobItem(job_id=job.id, sample_id=sid, status="queued") for sid in sample_ids]
    )
    db.commit()
    db.refresh(job)
    get_teacher_worker().notify()
    return _job_to_summary(job)


@router.get("/jobs", response_model=list[TeacherJobSummary])
def list_teacher_jobs(
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
) -> list[TeacherJobSummary]:
    jobs = (
        db.query(TeacherJob)
        .order_by(TeacherJob.created_at.desc())
        .limit(50)
        .all()
    )
    return [_job_to_summary(j) for j in jobs]


_VALID_ITEM_STATUSES: tuple[str, ...] = ("queued", "running", "done", "error", "skipped")


@router.get("/jobs/{job_id}", response_model=TeacherJobDetail)
def get_teacher_job(
    job_id: UUID,
    items_status: str | None = Query(
        None,
        description=(
            "Filter the items list by status (queued|running|done|error|skipped). "
            "Omit or use 'all' for everything. status_counts always reflects the full job."
        ),
    ),
    items_page: int = Query(1, ge=1),
    items_page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
) -> TeacherJobDetail:
    """Job detail + paginated, status-filtered items.

    At 4k+ items a single-page dump is unusable. status_counts still scans the whole
    job (cheap GROUP BY) so the per-status badges in the header stay accurate; the items
    list itself is paginated and filtered server-side.
    """
    job = db.query(TeacherJob).filter(TeacherJob.id == job_id).first()
    if job is None:
        raise APIError(404, "Job not found", "TEACHER_JOB_NOT_FOUND")

    # Per-status totals come straight from a GROUP BY so the page can show "12 queued / 3
    # running / 47 done" without iterating the item list client-side.
    rows = (
        db.query(TeacherJobItem.status, func.count(TeacherJobItem.id))
        .filter(TeacherJobItem.job_id == job_id)
        .group_by(TeacherJobItem.status)
        .all()
    )
    status_counts: dict[str, int] = {status: int(count) for status, count in rows}

    requested_status = (items_status or "").strip().lower() or None
    if requested_status == "all":
        requested_status = None
    if requested_status is not None and requested_status not in _VALID_ITEM_STATUSES:
        raise APIError(
            400,
            f"Invalid items_status {requested_status!r}; expected one of "
            + ", ".join(_VALID_ITEM_STATUSES) + " or 'all'.",
            "TEACHER_ITEMS_STATUS_INVALID",
        )

    base_q = db.query(TeacherJobItem).filter(TeacherJobItem.job_id == job_id)
    if requested_status is not None:
        base_q = base_q.filter(TeacherJobItem.status == requested_status)

    # Order so active work surfaces first when no filter is applied. With a filter, the
    # natural order is "oldest first" for queued/running and "most-recently-finished" for
    # everything else — so we branch by filter.
    if requested_status in (None, "queued", "running"):
        ordered_q = base_q.order_by(TeacherJobItem.created_at.asc())
    else:
        ordered_q = base_q.order_by(TeacherJobItem.processed_at.desc().nullslast())

    items_total = base_q.count()
    items_pages = max(1, (items_total + items_page_size - 1) // items_page_size)
    safe_page = min(items_page, items_pages)
    offset = (safe_page - 1) * items_page_size

    page_rows = ordered_q.offset(offset).limit(items_page_size).all()
    items = [
        TeacherJobItemSummary(
            id=item.id,
            sample_id=item.sample_id,
            status=item.status,
            error_message=item.error_message,
            detection_count=item.detection_count,
            processed_at=item.processed_at,
        )
        for item in page_rows
    ]

    summary = _job_to_summary(job)
    return TeacherJobDetail(
        **summary.model_dump(),
        items=items,
        status_counts=status_counts,
        # Items are properly paginated now — the truncation flag stays for backward
        # compat but is always False; the UI uses items_pages/items_total instead.
        items_truncated=False,
        items_page=safe_page,
        items_page_size=items_page_size,
        items_total=items_total,
        items_pages=items_pages,
        items_status_filter=requested_status,
    )


class RerunSingleSampleRequest(BaseModel):
    openrouter_model: str | None = None


class TeacherModelInfo(BaseModel):
    model_id: str
    display_name: str
    adapter_kind: str
    notes: str


class TeacherPreviewRequest(BaseModel):
    openrouter_model: str
    # Optional override of the system prompt sent to the model. The compare page uses this
    # so an admin can iterate on prompt wording without redeploying. None falls back to the
    # adapter's default (Gemini-style JSON prompt for chat adapters, short zone instruction
    # for Perceptron).
    override_prompt: str | None = None


class TeacherPromptResponse(BaseModel):
    model_id: str
    adapter_kind: str
    zone: str
    prompt: str
    is_default: bool = True


class TeacherPreviewResponse(BaseModel):
    model: str
    adapter_kind: str
    algorithm: str
    image_width: int
    image_height: int
    bboxes: list[list[int]]
    score: float
    count: int
    detections: list[dict[str, Any]]
    cost_usd: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    elapsed_ms: int
    # Raw assistant message text + any structured annotations the provider returned. Used
    # by the compare page's "Show raw response" toggle so the admin can verify what the
    # model actually emitted — invaluable when boxes look mis-placed and you can't tell
    # whether it's a parsing bug or a model hallucination.
    raw_text: str | None = None
    raw_annotations: list[dict[str, Any]] | None = None


@router.get("/samples/{sample_id}/prompt", response_model=TeacherPromptResponse)
def get_sample_teacher_prompt(
    sample_id: UUID,
    openrouter_model: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
) -> TeacherPromptResponse:
    """Default prompt the given adapter would send for this sample's zone.

    The compare page prefills its textarea with this so the admin can tweak from a known
    baseline. Width/height are baked into the Gemini prompt as ``image is WxH`` but they
    just inform the model — the same prompt works for any size, the actual call always
    uses the real image dimensions.
    """
    sample = db.query(Sample).filter(Sample.id == sample_id).first()
    if sample is None:
        raise APIError(404, "Sample not found", "SAMPLE_NOT_FOUND")
    zone = zone_for_source_role(sample.source_role)
    if zone is None:
        raise APIError(
            400,
            f"Teacher has no prompt zone for source_role={sample.source_role!r}.",
            "TEACHER_ZONE_UNSUPPORTED",
        )
    adapter = get_adapter(openrouter_model)
    if adapter is None:
        raise APIError(400, f"Unknown teacher model {openrouter_model!r}.", "TEACHER_MODEL_UNKNOWN")

    resolved = resolve_prompt(
        db,
        zone,
        adapter_kind_for(adapter.adapter_kind),
        width=int(sample.image_width or 1024),
        height=int(sample.image_height or 1024),
    )

    return TeacherPromptResponse(
        model_id=adapter.model_id,
        adapter_kind=adapter.adapter_kind,
        zone=zone,
        prompt=resolved.content,
    )


@router.get("/models", response_model=list[TeacherModelInfo])
def list_teacher_models(
    admin: User = Depends(require_role("admin")),
) -> list[TeacherModelInfo]:
    """Expose the adapter registry so the compare page renders rows dynamically."""
    return [
        TeacherModelInfo(
            model_id=a.model_id,
            display_name=a.display_name,
            adapter_kind=a.adapter_kind,
            notes=getattr(a, "notes", "") or "",
        )
        for a in list_adapters()
    ]


@router.post("/samples/{sample_id}/preview", response_model=TeacherPreviewResponse)
def preview_sample_teacher(
    sample_id: UUID,
    payload: TeacherPreviewRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
) -> TeacherPreviewResponse:
    """Run a single adapter on a single sample WITHOUT writing back.

    Powers the per-sample compare page: each model fires its own preview request so the
    admin can stack the boxes side-by-side and pick a winner. Cost and latency travel with
    the response so the row can show "$0.0012 · 4.2s".
    """
    sample = db.query(Sample).filter(Sample.id == sample_id).first()
    if sample is None:
        raise APIError(404, "Sample not found", "SAMPLE_NOT_FOUND")

    zone = zone_for_source_role(sample.source_role)
    if zone is None:
        raise APIError(
            400,
            f"Teacher has no prompt zone for source_role={sample.source_role!r}.",
            "TEACHER_ZONE_UNSUPPORTED",
        )

    adapter = get_adapter(payload.openrouter_model)
    if adapter is None:
        raise APIError(
            400,
            f"Unknown teacher model {payload.openrouter_model!r}.",
            "TEACHER_MODEL_UNKNOWN",
        )
    api_key = _resolve_adapter_secret(admin, adapter)

    try:
        image_bytes = get_backend().read_bytes(sample.image_path)
    except FileNotFoundError as exc:
        raise APIError(404, "Sample image is missing", "SAMPLE_IMAGE_MISSING") from exc

    # Chain: compare-page textarea override (ad-hoc) > persisted DB prompt (settings) >
    # hardcoded default. The textarea has been pre-filled with the resolved value so the
    # user only sees a real "override" when they actually typed something different.
    effective_prompt = payload.override_prompt
    if not (effective_prompt and effective_prompt.strip()):
        resolved = resolve_prompt(
            db,
            zone,
            adapter_kind_for(adapter.adapter_kind),
            width=int(sample.image_width or 1024),
            height=int(sample.image_height or 1024),
        )
        effective_prompt = resolved.content

    try:
        result = adapter.detect(
            image_bytes=image_bytes,
            zone=zone,
            api_key=api_key,
            public_app_url=settings.public_app_url,
            override_prompt=effective_prompt,
        )
    except Exception as exc:
        raise APIError(502, f"Teacher detection failed: {exc}", "TEACHER_DETECTION_FAILED") from exc

    raw = result.raw_response if isinstance(result.raw_response, dict) else None
    raw_text: str | None = None
    raw_annotations: list[dict[str, Any]] | None = None
    if raw is not None:
        text_field = raw.get("text")
        if isinstance(text_field, str):
            raw_text = text_field
        ann = raw.get("annotations")
        if isinstance(ann, list):
            raw_annotations = ann

    return TeacherPreviewResponse(
        model=result.model,
        adapter_kind=result.adapter_kind,
        algorithm=result.algorithm,
        image_width=result.image_width,
        image_height=result.image_height,
        bboxes=result.bboxes,
        score=result.score,
        count=result.count,
        detections=result.detections,
        cost_usd=result.cost_usd,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        elapsed_ms=result.elapsed_ms,
        raw_text=raw_text,
        raw_annotations=raw_annotations,
    )


@router.post("/samples/{sample_id}/rerun", response_model=SampleDetailResponse)
def rerun_single_sample(
    sample_id: UUID,
    payload: RerunSingleSampleRequest | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
) -> SampleDetailResponse:
    """Run the teacher synchronously on one sample. Bypasses the worker queue.

    Used from the sample-detail page when an admin wants an immediate refresh — waiting on
    the background worker would block behind any backfill job that's already running. The
    request stays open for the full round-trip (~3–10s).
    """
    sample = db.query(Sample).filter(Sample.id == sample_id).first()
    if sample is None:
        raise APIError(404, "Sample not found", "SAMPLE_NOT_FOUND")

    zone = zone_for_source_role(sample.source_role)
    if zone is None:
        raise APIError(
            400,
            f"Teacher has no prompt zone for source_role={sample.source_role!r}.",
            "TEACHER_ZONE_UNSUPPORTED",
        )

    requested_model = (payload.openrouter_model if payload else None) or admin.preferred_teacher_model
    model = normalize_openrouter_model(requested_model)
    if model not in SUPPORTED_OPENROUTER_MODELS:
        model = DEFAULT_OPENROUTER_MODEL

    adapter = get_adapter(model)
    if adapter is None:
        raise APIError(400, f"Unknown teacher model {model!r}.", "TEACHER_MODEL_UNKNOWN")
    api_key = _resolve_adapter_secret(admin, adapter)

    try:
        image_bytes = get_backend().read_bytes(sample.image_path)
    except FileNotFoundError as exc:
        raise APIError(404, "Sample image is missing", "SAMPLE_IMAGE_MISSING") from exc

    # Persisted-prompt resolution: pull DB-stored prompt for this zone+kind (or default
    # template) and pass it via override_prompt. Same chain as the batch worker.
    resolved = resolve_prompt(
        db,
        zone,
        adapter_kind_for(adapter.adapter_kind),
        width=int(sample.image_width or 1024),
        height=int(sample.image_height or 1024),
    )

    try:
        result = run_teacher_detection(
            image_bytes=image_bytes,
            zone=zone,
            api_key=api_key,
            public_app_url=settings.public_app_url,
            openrouter_model=model,
            override_prompt=resolved.content,
        )
    except Exception as exc:
        raise APIError(502, f"Teacher detection failed: {exc}", "TEACHER_DETECTION_FAILED") from exc

    apply_teacher_result_to_sample(sample, result, source="hive_teacher_inline")
    db.add(sample)
    db.commit()
    db.refresh(sample)

    response = SampleDetailResponse.model_validate(sample)
    response.has_full_frame = sample.full_frame_path is not None
    response.has_overlay = sample.overlay_path is not None
    return response


@router.post("/jobs/{job_id}/cancel", response_model=TeacherJobSummary)
def cancel_teacher_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
) -> TeacherJobSummary:
    job = db.query(TeacherJob).filter(TeacherJob.id == job_id).first()
    if job is None:
        raise APIError(404, "Job not found", "TEACHER_JOB_NOT_FOUND")
    if job.status in ("done", "cancelled"):
        return _job_to_summary(job)

    db.query(TeacherJobItem).filter(
        TeacherJobItem.job_id == job_id,
        TeacherJobItem.status == "queued",
    ).update({TeacherJobItem.status: "skipped", TeacherJobItem.error_message: "Cancelled by admin"})

    job.status = "cancelled"
    job.finished_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()
    db.refresh(job)
    return _job_to_summary(job)


# ============================================================ persisted prompts CRUD

class TeacherPromptEntry(BaseModel):
    zone: str
    kind: str  # 'chat' | 'perceptron'
    content: str              # currently-effective template (DB if set, else default)
    is_custom: bool           # True iff a DB row exists for this (zone, kind)
    default_content: str      # the hardcoded baseline; powers the "Reset" button
    updated_at: datetime | None = None
    updated_by_display_name: str | None = None


class TeacherPromptUpdateRequest(BaseModel):
    content: str


def _prompt_entry_for(db: Session, zone: str, kind: str) -> TeacherPromptEntry:
    """Compose the per-row payload the settings page consumes for one zone × kind."""
    row = (
        db.query(TeacherPrompt)
        .filter(TeacherPrompt.zone == zone, TeacherPrompt.kind == kind)
        .first()
    )
    default_tmpl = default_template(zone, kind)
    if row is None:
        return TeacherPromptEntry(
            zone=zone, kind=kind,
            content=default_tmpl, is_custom=False,
            default_content=default_tmpl,
        )
    updater_name: str | None = None
    if row.updated_by_id is not None:
        u = db.query(User).filter(User.id == row.updated_by_id).first()
        if u is not None:
            updater_name = u.display_name or u.email
    return TeacherPromptEntry(
        zone=zone, kind=kind,
        content=row.content, is_custom=True,
        default_content=default_tmpl,
        updated_at=row.updated_at,
        updated_by_display_name=updater_name,
    )


@router.get("/prompts", response_model=list[TeacherPromptEntry])
def list_teacher_prompts(
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
) -> list[TeacherPromptEntry]:
    """Return one row per supported (zone, kind) — exactly what the editor renders."""
    return [
        _prompt_entry_for(db, zone, kind)
        for zone in SUPPORTED_PROMPT_ZONES
        for kind in SUPPORTED_PROMPT_KINDS
    ]


def _validate_zone_kind(zone: str, kind: str) -> None:
    if zone not in SUPPORTED_PROMPT_ZONES:
        raise APIError(400, f"Unknown zone {zone!r}", "TEACHER_PROMPT_ZONE_INVALID")
    if kind not in SUPPORTED_PROMPT_KINDS:
        raise APIError(400, f"Unknown kind {kind!r}", "TEACHER_PROMPT_KIND_INVALID")


@router.put("/prompts/{zone}/{kind}", response_model=TeacherPromptEntry)
def upsert_teacher_prompt(
    zone: str,
    kind: str,
    payload: TeacherPromptUpdateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
) -> TeacherPromptEntry:
    """Persist or update the custom prompt for ``(zone, kind)``."""
    _validate_zone_kind(zone, kind)
    content = (payload.content or "").strip()
    if not content:
        raise APIError(400, "Prompt content cannot be empty", "TEACHER_PROMPT_EMPTY")

    row = (
        db.query(TeacherPrompt)
        .filter(TeacherPrompt.zone == zone, TeacherPrompt.kind == kind)
        .first()
    )
    if row is None:
        row = TeacherPrompt(zone=zone, kind=kind, content=content, updated_by_id=admin.id)
        db.add(row)
    else:
        row.content = content
        row.updated_by_id = admin.id
    db.commit()
    db.refresh(row)
    return _prompt_entry_for(db, zone, kind)


@router.delete("/prompts/{zone}/{kind}", response_model=TeacherPromptEntry)
def reset_teacher_prompt(
    zone: str,
    kind: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
) -> TeacherPromptEntry:
    """Drop the custom prompt so detection falls back to the hardcoded default."""
    _validate_zone_kind(zone, kind)
    row = (
        db.query(TeacherPrompt)
        .filter(TeacherPrompt.zone == zone, TeacherPrompt.kind == kind)
        .first()
    )
    if row is not None:
        db.delete(row)
        db.commit()
    return _prompt_entry_for(db, zone, kind)
