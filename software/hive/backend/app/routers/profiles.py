"""Sorting profiles: the catalog to build them from, the profiles and their
versions, and what machines download.

A profile is edited as a document (ordered rules) and saved as versions; each
version is compiled when saved (profile_engine.compiler). Every route a
person's browser uses also takes an API key with the profiles scopes, so an
assistant can do what the editor does; the chat in the editor stays on the
browser session, since it spends the user's own model key.
"""

from __future__ import annotations

import copy
import gzip
import json
import logging
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, object_session

from app.config import settings
from app.deps import (
    API_KEY_SCOPE_PROFILES_READ,
    API_KEY_SCOPE_PROFILES_WRITE,
    get_current_machine,
    get_current_user,
    get_db,
    require_api_key_scopes,
    require_role,
    verify_csrf,
)
from app.errors import APIError
from app.models.machine import Machine
from app.models.machine_profile_assignment import MachineProfileAssignment
from app.models.sorting_profile import SortingProfile
from app.models.sorting_profile_ai_message import SortingProfileAiMessage
from app.models.sorting_profile_library_entry import SortingProfileLibraryEntry
from app.models.sorting_profile_version import SortingProfileVersion
from app.models.user import User
from app.schemas.profile import (
    MachineProfileActivationRequest,
    MachineProfileAssignmentResponse,
    MachineProfileAssignmentUpdateRequest,
    MachineProfileLibraryResponse,
    SortingProfileAiApplyRequest,
    SortingProfileAiMessageResponse,
    SortingProfileAiRequest,
    SortingProfileBricklinkCsvImportRequest,
    SortingProfileChangeNoteSuggestRequest,
    SortingProfileChangeNoteSuggestResponse,
    SortingProfileCreateRequest,
    SortingProfileDetailResponse,
    SortingProfileForkRequest,
    SortingProfileHeadResponse,
    SortingProfilePreviewRequest,
    SortingProfileRouteRequest,
    SortingProfileSetProgressResponse,
    SortingProfileSummaryResponse,
    SortingProfileUpdateRequest,
    SortingProfileVersionCreateRequest,
    SortingProfileVersionResponse,
    SortingProfileVersionSummaryResponse,
)
from app.services.profile_ai import (
    AiProgressEvent,
    AiProposalResult,
    apply_profile_ai_proposal,
    generate_change_note,
    generate_change_note_from_diff,
    generate_profile_ai_proposal,
    generate_profile_ai_proposal_streaming,
)
from app.services.ai_usage import record_ai_usage
from app.services.kits import kits_for_rules, kits_from_set_rules, missing_kits
from app.services.profile_display import described, display_for
from app.services.secrets import decrypt_secret
from app.services.machine_set_progress import summarize_machine_set_progress
from app.services.profile_catalog import PROFILE_CATALOG_SYNC_TYPES, get_profile_catalog_service
from app.services.profile_engine.compiler import Router as ProfileRouter, expand_legacy, part_preview
from app.services.profile_engine.fields import FIELD_ALIASES, FIELDS, OP_LABELS
from app.services.rate_limit import rate_limit

router = APIRouter(prefix="/api", tags=["profiles"])
logger = logging.getLogger("uvicorn.error").getChild("profiles")

# One dependency object each, so a route that names it twice (itself and its
# rate limit) resolves the caller once.
_reader = require_api_key_scopes(API_KEY_SCOPE_PROFILES_READ)
_writer = require_api_key_scopes(API_KEY_SCOPE_PROFILES_WRITE)
READ = Depends(_reader)
WRITE = Depends(_writer)

CATALOG_SYNC_TYPES = set(PROFILE_CATALOG_SYNC_TYPES)
AI_CONVERSATION_HISTORY_LIMIT = 12


def _build_ai_usage_payload(proposal_result: AiProposalResult) -> dict[str, object] | None:
    usage_with_trace = dict(proposal_result.usage or {})
    if proposal_result.tool_trace:
        usage_with_trace["tool_trace"] = [
            {
                "tool": t.tool,
                "input": t.input,
                "output_summary": t.output_summary,
                "output": t.output,
                "duration_ms": t.duration_ms,
            }
                for t in proposal_result.tool_trace
            ]
    performance = getattr(proposal_result, "performance", None)
    if performance:
        usage_with_trace["performance"] = performance
    return usage_with_trace or None


def _record_chat_usage(
    db: Session,
    current_user: User,
    profile: SortingProfile,
    assistant_message: SortingProfileAiMessage,
    proposal_result: AiProposalResult,
) -> None:
    performance = getattr(proposal_result, "performance", None) or {}
    generation_ids = performance.get("generation_ids") or None
    record_ai_usage(
        db,
        user_id=current_user.id,
        profile_id=profile.id,
        message_id=assistant_message.id,
        purpose="profile_chat",
        model=proposal_result.model,
        usage=proposal_result.usage,
        generation_ids=generation_ids if isinstance(generation_ids, list) else None,
        call_count=int(performance.get("round_count") or 1),
    )


@router.get("/profile-catalog/status")
def get_profile_catalog_status(
    _current_user: User = Depends(require_role("admin")),
):
    return get_profile_catalog_service().status()


@router.post("/profile-catalog/sync/{sync_type}")
def start_profile_catalog_sync(
    sync_type: str,
    _current_user: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
):
    if sync_type not in CATALOG_SYNC_TYPES:
        raise APIError(400, f"Unsupported sync type '{sync_type}'", "PROFILE_CATALOG_SYNC_INVALID")
    started = get_profile_catalog_service().start_sync(sync_type)
    if not started:
        status = get_profile_catalog_service().status()
        error = status.get("error")
        if error:
            raise APIError(400, str(error), "PROFILE_CATALOG_SYNC_ERROR")
        raise APIError(409, "A catalog sync is already running", "PROFILE_CATALOG_SYNC_RUNNING")
    return {"started": True}


@router.post("/profile-catalog/stop")
def stop_profile_catalog_sync(
    _current_user: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
):
    get_profile_catalog_service().stop_sync()
    return {"stopped": True}



# --- The catalog a profile is built from ----------------------------------------


@router.get("/profile-catalog/fields")
def list_profile_fields(_current_user: User = READ):
    """Every field a condition can test: its type, the operators it takes, and
    what its values name ("bl_category", "color", ...)."""
    return {
        "fields": [
            {
                "field": spec.key,
                "label": spec.label,
                "group": spec.group,
                "type": spec.type,
                "ops": list(spec.ops),
                "ref": spec.ref,
                "unit": spec.unit,
                "description": spec.description,
            }
            for spec in FIELDS.values()
            if spec.alias_of is None
        ],
        # Older names still found in saved rules, and the field each now is.
        "aliases": {
            **FIELD_ALIASES,
            **{spec.key: spec.alias_of for spec in FIELDS.values() if spec.alias_of},
        },
        "ops": OP_LABELS,
        # Where the values a ref names are listed.
        "refs": {
            "bl_category": "/api/profile-catalog/bricklink-categories",
            "rb_category": "/api/profile-catalog/categories",
            "color": "/api/profile-catalog/colors (the Rebrickable id)",
            "part": "/api/profile-catalog/search-parts (the Rebrickable part_num)",
            "bl_part": "/api/profile-catalog/search-parts or /api/profile-catalog/parts/{id} (a BrickLink ID)",
        },
    }


@router.get("/profile-catalog/search-parts")
def search_profile_catalog_parts(
    q: str = "",
    cat_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    _current_user: User = READ,
    _rl: None = Depends(rate_limit("catalog_search", user=_reader)),
):
    return get_profile_catalog_service().search_parts(q, cat_id, limit, offset)


@router.get("/profile-catalog/parts/{part}")
def get_profile_catalog_part(part: str, _current_user: User = READ):
    """One part by Rebrickable number or BrickLink ID."""
    index = get_profile_catalog_service().index()
    rows = index.rows_for(part)
    if not rows:
        raise APIError(404, f"No part {part!r} in the catalog", "PART_NOT_FOUND")
    return part_preview(rows[0], index)


@router.get("/profile-catalog/categories")
def list_profile_catalog_categories(_current_user: User = READ):
    """The Rebrickable part categories. Served to any signed-in user: the
    part-correction picker needs it without making labelers admins."""
    return {"results": get_profile_catalog_service().admin_list_categories()}


@router.get("/profile-catalog/bricklink-categories")
def list_profile_catalog_bricklink_categories(
    q: str = "",
    all: bool = False,
    _current_user: User = READ,
):
    """The BrickLink part categories with how many catalog parts are in each:
    only those with parts (most of BrickLink's are sets and themes) unless
    all=true, and only those whose name contains q."""
    index = get_profile_catalog_service().index()
    counts: dict[int, int] = {}
    for value in index.column("bl_category_id"):
        if value == value:  # not NaN
            counts[int(value)] = counts.get(int(value), 0) + 1
    needle = q.strip().lower()
    results = [
        {
            "id": category_id,
            "name": category.get("category_name") or str(category_id),
            "parent_id": category.get("parent_id"),
            "part_count": counts.get(category_id, 0),
        }
        for category_id, category in index.bricklink_categories.items()
        if (all or counts.get(category_id)) and needle in (category.get("category_name") or "").lower()
    ]
    return {"results": sorted(results, key=lambda item: item["name"].lower())}


@router.get("/profile-catalog/search-sets")
def search_profile_catalog_sets(
    q: str = "",
    min_year: int | None = None,
    max_year: int | None = None,
    _current_user: User = READ,
):
    if not settings.REBRICKABLE_API_KEY:
        raise APIError(503, "Set search is not set up on this Hive (it has no Rebrickable key)", "SET_SEARCH_UNAVAILABLE")
    if not q.strip():
        return {"results": []}
    return {"results": get_profile_catalog_service().search_sets(q.strip(), min_year=min_year, max_year=max_year)}


@router.get("/profile-catalog/sets/{set_num}")
def get_profile_catalog_set(set_num: str, _current_user: User = READ):
    """A LEGO set and its parts inventory."""
    return get_profile_catalog_service().get_set_inventory(set_num)


@router.get("/profile-catalog/colors")
def list_profile_catalog_colors(q: str = "", _current_user: User = READ):
    """The colors rules test: `id` is the Rebrickable color ID (what conditions
    take), `bricklink_id` the BrickLink one (what a sorter reports). q filters
    by name."""
    catalog = get_profile_catalog_service()
    index = catalog.index()
    needle = q.strip().lower()
    return {
        "results": [
            {**color, "bricklink_id": index.bl_color(color["id"])}
            for color in catalog.list_colors()
            if needle in (color.get("name") or "").lower()
        ]
    }


@router.post("/profile-catalog/import-bricklink-csv")
def import_profile_catalog_bricklink_csv(
    payload: SortingProfileBricklinkCsvImportRequest,
    _current_user: User = READ,
    _csrf: None = Depends(verify_csrf),
):
    return get_profile_catalog_service().import_bricklink_csv(payload.csv_content, filename=payload.filename)


# --- Trying a profile out without saving it --------------------------------------


def _compile_draft(db: Session, owner_id: UUID, document: dict[str, Any]):
    kits = kits_for_rules(db, owner_id, document.get("rules") or [])
    compiled = get_profile_catalog_service().compile_document(document, kits)
    return compiled, missing_kits(document.get("rules") or [], kits)


@router.post("/profiles/preview")
def preview_sorting_profile(
    payload: SortingProfilePreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = READ,
):
    """Compile a draft: each bin it fills (name, picture, conditions in words,
    part count, examples), what is wrong with it, and totals. Nothing is saved."""
    started = perf_counter()
    compiled, missing = _compile_draft(db, current_user.id, payload.model_dump())
    artifact = compiled.artifact
    stats = artifact["stats"]
    return {
        # Parts that go to a bin of their own (a rule, a kit or a fallback
        # category) out of every part in the catalog; the rest go to the default.
        "stats": {"total_parts": stats["total_parts"], "sorted": stats["sorted"]},
        "categories": artifact["categories"],
        "category_order": artifact["category_order"],
        "rules": artifact["rules"],
        "warnings": compiled.warnings,
        "problems": [problem.as_dict() for problem in compiled.problems] + missing,
        "requires": artifact["requires"],
        "artifact_hash": artifact["artifact_hash"],
        "compile_ms": round((perf_counter() - started) * 1000, 1),
    }


@router.post("/profiles/preview-rule")
def preview_sorting_rule(
    payload: SortingProfilePreviewRequest,
    rule_id: str,
    q: str = "",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    standalone: bool = False,
    _current_user: User = READ,
):
    """The parts one rule of a draft matches, most sold first. A child rule is
    matched inside its parents unless standalone."""
    rules = [rule.model_dump() for rule in payload.rules]
    try:
        return get_profile_catalog_service().preview_rule(
            rules=rules, rule_id=rule_id, q=q, offset=offset, limit=limit, standalone=standalone
        )
    except KeyError:
        raise APIError(404, "Rule not found", "PROFILE_RULE_NOT_FOUND") from None


@router.post("/profiles/route")
def route_pieces(
    payload: SortingProfileRouteRequest,
    db: Session = Depends(get_db),
    current_user: User = READ,
):
    """Where each piece would go, under a draft or a saved version: the bin it
    lands in, and whether a rule, a kit, the fallback or the default sent it."""
    catalog = get_profile_catalog_service()
    index = catalog.index()
    if payload.document is not None:
        compiled, _missing = _compile_draft(db, current_user.id, payload.document.model_dump())
        artifact = compiled.artifact
    else:
        if payload.profile_id is None:
            raise APIError(400, "Give a document or a profile_id", "PROFILE_ROUTE_TARGET_MISSING")
        profile = _get_profile_or_404(db, payload.profile_id)
        _require_profile_view_access(profile, current_user)
        version = _resolve_visible_version(profile, current_user, payload.version_id)
        if version is None:
            raise APIError(404, "Version not found", "PROFILE_VERSION_NOT_FOUND")
        artifact = version.compiled_artifact_json or {}
        if "program" not in artifact:
            # Compiled before the program existed: compile its rules again.
            recompiled, _missing = _compile_draft(db, profile.owner_id, _document_from_version(version))
            artifact = recompiled.artifact
    routing = ProfileRouter(artifact["program"])
    categories = artifact.get("categories") or {}
    # Kits start empty and fill in the order the pieces are given, as on a
    # machine: a kit that has all it needs of a part passes the next one on.
    left: dict[tuple[str, str, str], int] = {}
    for kit_category, inventory in (artifact.get("set_inventories") or {}).items():
        for line in inventory.get("parts") or []:
            color = "any" if line.get("color_id") in (None, -1, "-1") else str(line.get("color_id"))
            key = (str(kit_category), str(line.get("part_num")), color)
            left[key] = left.get(key, 0) + int(line.get("quantity") or 0)

    def kit_lines(category: str, part: str, color: str | None) -> list[tuple[str, str, str]]:
        return [key for key in ((category, part, color or ""), (category, part, "any")) if key in left]

    def kit_is_full(category: str, part: str, color: str | None) -> bool:
        if not payload.fill_kits:
            return False
        lines = kit_lines(category, part, color)
        return bool(lines) and all(left[key] <= 0 for key in lines)

    results = []
    for piece in payload.pieces:
        rows = index.rows_for(piece.part)
        part_key = index.keys[rows[0]][0] if rows else piece.part.strip()
        color = None
        color_info = None
        if piece.color_id is not None:
            if piece.color_id not in index.colors:
                raise APIError(400, f"No Rebrickable color {piece.color_id}", "COLOR_NOT_FOUND")
            color = index.bl_color(piece.color_id)
        elif piece.bricklink_color_id is not None:
            color = str(piece.bricklink_color_id)
        if color is not None:
            color_info = index.bl_colors.get(color, {"id": color, "name": f"BrickLink color {color}"})
        category, why = routing.route(part_key, color, kit_is_full)
        kit_left = None
        if why == "kit":
            lines = [key for key in kit_lines(category, part_key, color) if left[key] > 0]
            if lines and payload.fill_kits:
                left[lines[0]] -= 1
            kit_left = sum(max(left[key], 0) for key in kit_lines(category, part_key, color))
        category_info = categories.get(category) or {}
        part = index.part(rows[0]) if rows else {}
        results.append(
            {
                "part": piece.part,
                "bricklink_id": part_key,
                "part_name": part.get("name"),
                "img_url": part.get("part_img_url"),
                "known_part": bool(rows),
                "color": color_info,
                "category_id": category,
                "category_name": category_info.get("name", category),
                "why": why,
                # For a kit: how many more of this part and color it still takes.
                "kit_left": kit_left,
            }
        )
    return {"results": results}


# --- Profiles ---------------------------------------------------------------------


@router.get("/profiles", response_model=list[SortingProfileSummaryResponse])
def list_profiles(
    scope: str = Query(default="discover", pattern="^(discover|mine|library|defaults)$"),
    q: str = Query(default=""),
    db: Session = Depends(get_db),
    current_user: User = READ,
):
    profiles = _query_profiles_for_scope(db, current_user, scope, q)
    saved_profile_ids = _saved_profile_ids(db, current_user.id)
    return [_serialize_profile_summary(db, profile, current_user, saved_profile_ids) for profile in profiles]


@router.post("/profiles", response_model=SortingProfileDetailResponse)
def create_profile(
    payload: SortingProfileCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = WRITE,
    _csrf: None = Depends(verify_csrf),
):
    """A new profile, private, with a first version from the rules given (or none)."""
    visibility = _normalize_visibility(payload.visibility)
    profile = SortingProfile(
        owner_id=current_user.id,
        name=payload.name.strip() or "Untitled Profile",
        description=(payload.description or "").strip() or None,
        visibility=visibility,
        tags=_sanitize_tags(payload.tags),
        latest_version_number=0,
        profile_type="rule",
    )
    db.add(profile)
    db.flush()
    version = _create_version(
        db=db,
        profile=profile,
        current_user=current_user,
        request=request,
        payload=SortingProfileVersionCreateRequest(
            name=profile.name,
            description=profile.description,
            default_category_id=payload.default_category_id or "misc",
            rules=payload.rules,
            fallback_mode=payload.fallback_mode.model_dump() if payload.fallback_mode is not None else {},
            change_note=(payload.change_note or "").strip() or "Initial version",
            publish=False,
        ),
    )
    db.commit()
    db.refresh(profile)
    return _serialize_profile_detail(db, profile, current_user, saved_profile_ids=set(), current_version=version)


@router.get("/profiles/{profile_id}", response_model=SortingProfileDetailResponse)
def get_profile(
    profile_id: UUID,
    version_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: User = READ,
):
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_view_access(profile, current_user)
    saved_profile_ids = _saved_profile_ids(db, current_user.id)
    current_version = _resolve_visible_version(profile, current_user, version_id)
    return _serialize_profile_detail(db, profile, current_user, saved_profile_ids, current_version=current_version)


@router.get("/profiles/{profile_id}/head", response_model=SortingProfileHeadResponse)
def get_profile_head(
    profile_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = READ,
):
    """The profile's latest version and when it changed: cheap enough for an
    open page to ask every few seconds, so a change made elsewhere (by an
    assistant through the API, say) shows up without a reload."""
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_view_access(profile, current_user)
    query = db.query(SortingProfileVersion).filter(SortingProfileVersion.profile_id == profile.id)
    if profile.owner_id != current_user.id:
        query = query.filter(SortingProfileVersion.is_published.is_(True))
    latest = query.order_by(SortingProfileVersion.version_number.desc()).first()
    return {
        "profile_id": profile.id,
        "name": profile.name,
        "updated_at": profile.updated_at,
        "latest_version_id": latest.id if latest else None,
        "latest_version_number": latest.version_number if latest else 0,
        "latest_version_created_at": latest.created_at if latest else None,
        "created_via": latest.created_via if latest else None,
        "created_via_key_name": latest.created_via_key.name if latest and latest.created_via_key else None,
    }


@router.get("/profiles/{profile_id}/set-progress", response_model=SortingProfileSetProgressResponse)
def get_profile_set_progress(
    profile_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = READ,
):
    from app.models.machine_set_progress import MachineSetProgress

    profile = _get_profile_or_404(db, profile_id)
    _require_profile_view_access(profile, current_user)

    assignments = (
        db.query(MachineProfileAssignment)
        .join(Machine, Machine.id == MachineProfileAssignment.machine_id)
        .filter(
            MachineProfileAssignment.profile_id == profile.id,
            Machine.owner_id == current_user.id,
        )
        .all()
    )

    machines: list[dict[str, Any]] = []
    for assignment in assignments:
        version = assignment.active_version or assignment.desired_version
        artifact = version.compiled_artifact_json if version is not None else {}
        rows = (
            db.query(MachineSetProgress)
            .filter(MachineSetProgress.assignment_id == assignment.id)
            .all()
        )
        summary = summarize_machine_set_progress(artifact, rows)
        if not summary["sets"] and _profile_type_for_version(version) != "set":
            continue
        machines.append(
            {
                "machine_id": assignment.machine_id,
                "machine_name": assignment.machine.name if assignment.machine is not None else "Machine",
                "assignment_id": assignment.id,
                "desired_version_id": assignment.desired_version_id,
                "active_version_id": assignment.active_version_id,
                "desired_version_number": assignment.desired_version.version_number if assignment.desired_version else None,
                "active_version_number": assignment.active_version.version_number if assignment.active_version else None,
                "last_synced_at": assignment.last_synced_at,
                "last_activated_at": assignment.last_activated_at,
                "overall_needed": summary["overall_needed"],
                "overall_found": summary["overall_found"],
                "overall_pct": summary["overall_pct"],
                "updated_at": summary["updated_at"],
                "sets": summary["sets"],
            }
        )

    machines.sort(key=lambda item: item["machine_name"].lower())
    return {
        "profile_id": profile.id,
        "machines": machines,
    }


@router.patch("/profiles/{profile_id}", response_model=SortingProfileDetailResponse)
def update_profile(
    profile_id: UUID,
    payload: SortingProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = WRITE,
    _csrf: None = Depends(verify_csrf),
):
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_edit_access(profile, current_user)

    if payload.name is not None:
        profile.name = payload.name.strip() or profile.name
    if payload.description is not None:
        description = payload.description
        profile.description = description.strip() or None if isinstance(description, str) else None
    if payload.visibility is not None:
        profile.visibility = _normalize_visibility(payload.visibility)
    if payload.tags is not None:
        profile.tags = _sanitize_tags(payload.tags)

    profile.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(profile)
    saved_profile_ids = _saved_profile_ids(db, current_user.id)
    current_version = _resolve_visible_version(profile, current_user, None)
    return _serialize_profile_detail(db, profile, current_user, saved_profile_ids, current_version=current_version)


@router.delete("/profiles/{profile_id}")
def delete_profile(
    profile_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = WRITE,
    _csrf: None = Depends(verify_csrf),
):
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_edit_access(profile, current_user)

    try:
        db.query(MachineProfileAssignment).filter(
            MachineProfileAssignment.profile_id == profile.id
        ).delete(synchronize_session=False)
        db.delete(profile)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise APIError(500, f"Failed to delete profile: {exc}", "PROFILE_DELETE_FAILED")

    return {"ok": True}


@router.post("/profiles/{profile_id}/library")
def save_profile_to_library(
    profile_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = WRITE,
    _csrf: None = Depends(verify_csrf),
):
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_view_access(profile, current_user)
    if not db.query(SortingProfileLibraryEntry).filter(
        SortingProfileLibraryEntry.user_id == current_user.id,
        SortingProfileLibraryEntry.profile_id == profile.id,
    ).first():
        db.add(SortingProfileLibraryEntry(user_id=current_user.id, profile_id=profile.id))
        profile.library_count += 1
        db.commit()
    return {"ok": True}


@router.delete("/profiles/{profile_id}/library")
def remove_profile_from_library(
    profile_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = WRITE,
    _csrf: None = Depends(verify_csrf),
):
    entry = db.query(SortingProfileLibraryEntry).filter(
        SortingProfileLibraryEntry.user_id == current_user.id,
        SortingProfileLibraryEntry.profile_id == profile_id,
    ).first()
    if entry is None:
        raise APIError(404, "Profile is not in your library", "PROFILE_LIBRARY_ENTRY_NOT_FOUND")
    profile = db.query(SortingProfile).filter(SortingProfile.id == profile_id).first()
    if profile is not None and profile.library_count > 0:
        profile.library_count -= 1
    db.delete(entry)
    db.commit()
    return {"ok": True}


@router.post("/profiles/{profile_id}/fork", response_model=SortingProfileDetailResponse)
def fork_profile(
    profile_id: UUID,
    payload: SortingProfileForkRequest,
    request: Request,
    version_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: User = WRITE,
    _csrf: None = Depends(verify_csrf),
):
    source_profile = _get_profile_or_404(db, profile_id)
    _require_profile_view_access(source_profile, current_user)
    source_version = _resolve_visible_version(source_profile, current_user, version_id)
    if source_version is None:
        raise APIError(404, "No source version found for fork", "PROFILE_VERSION_NOT_FOUND")

    fork = SortingProfile(
        owner_id=current_user.id,
        source_profile_id=source_profile.id,
        source_version_number=source_version.version_number,
        name=(payload.name or f"{source_profile.name} (Fork)").strip(),
        description=(payload.description if payload.description is not None else source_profile.description),
        visibility="private",
        tags=copy.deepcopy(source_profile.tags or []),
    )
    db.add(fork)
    db.flush()

    version = _create_version(
        db=db,
        profile=fork,
        current_user=current_user,
        request=request,
        payload=SortingProfileVersionCreateRequest(
            name=source_version.name,
            description=source_version.description,
            default_category_id=source_version.default_category_id,
            rules=source_version.rules_json or [],
            fallback_mode=source_version.fallback_mode_json or {},
            change_note=f"Forked from {source_profile.name} v{source_version.version_number}",
            label=payload.name,
            publish=False,
        ),
    )

    source_profile.fork_count += 1
    if payload.add_to_library:
        if not db.query(SortingProfileLibraryEntry).filter(
            SortingProfileLibraryEntry.user_id == current_user.id,
            SortingProfileLibraryEntry.profile_id == fork.id,
        ).first():
            db.add(SortingProfileLibraryEntry(user_id=current_user.id, profile_id=fork.id))
            fork.library_count += 1

    db.commit()
    db.refresh(fork)
    saved_profile_ids = _saved_profile_ids(db, current_user.id)
    return _serialize_profile_detail(db, fork, current_user, saved_profile_ids, current_version=version)


@router.post("/profiles/{profile_id}/suggest-change-note", response_model=SortingProfileChangeNoteSuggestResponse)
def suggest_change_note(
    profile_id: UUID,
    payload: SortingProfileChangeNoteSuggestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import logging
    logger = logging.getLogger(__name__)
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_edit_access(profile, current_user)
    api_key = decrypt_secret(current_user.openrouter_api_key_encrypted)
    if not api_key:
        raise APIError(400, "OpenRouter API key required", "OPENROUTER_KEY_MISSING")
    try:
        result = generate_change_note_from_diff(
            api_key=api_key,
            old_rules=payload.old_rules,
            new_rules=payload.new_rules,
        )
        note = result.text
        record_ai_usage(
            db,
            user_id=current_user.id,
            profile_id=profile.id,
            purpose="change_note",
            model=result.model,
            usage=result.usage,
            generation_ids=[result.generation_id] if result.generation_id else None,
        )
        db.commit()
    except APIError:
        raise
    except Exception:
        logger.exception("Failed to generate change note suggestion")
        raise APIError(500, "Failed to generate change note", "CHANGE_NOTE_ERROR")
    return {"change_note": note}



@router.post("/profiles/{profile_id}/versions", response_model=SortingProfileVersionResponse)
def create_profile_version(
    profile_id: UUID,
    payload: SortingProfileVersionCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = WRITE,
    _csrf: None = Depends(verify_csrf),
):
    """Save a document as the profile's next version. Refused, with every
    problem listed, when a condition cannot be evaluated or a kit is missing."""
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_edit_access(profile, current_user)
    version = _create_version(db=db, profile=profile, current_user=current_user, payload=payload, request=request)
    db.commit()
    db.refresh(version)
    return _serialize_version_detail(version)


@router.post("/profiles/{profile_id}/versions/{version_id}/publish", response_model=SortingProfileVersionResponse)
def publish_profile_version(
    profile_id: UUID,
    version_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = WRITE,
    _csrf: None = Depends(verify_csrf),
):
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_edit_access(profile, current_user)
    version = _get_profile_version_or_404(profile, version_id)
    version.is_published = True
    if (
        profile.latest_published_version_number is None
        or version.version_number >= profile.latest_published_version_number
    ):
        profile.latest_published_version_number = version.version_number
    profile.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(version)
    return _serialize_version_detail(version)


@router.get("/profiles/{profile_id}/versions/{version_id}/artifact")
def get_profile_artifact(
    profile_id: UUID,
    version_id: UUID,
    request: Request,
    format: str = Query(default="program", pattern="^(program|legacy)$"),
    db: Session = Depends(get_db),
    current_user: User = READ,
):
    """What a sorter runs for a version. "legacy" is the flat part map sorters
    from before the program read (and their local profile upload takes)."""
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_view_access(profile, current_user)
    version = _resolve_visible_version(profile, current_user, version_id)
    if version is None:
        raise APIError(404, "Version not found", "PROFILE_VERSION_NOT_FOUND")
    return _artifact_response(version, format, request)


@router.get("/profiles/{profile_id}/ai/messages", response_model=list[SortingProfileAiMessageResponse])
def list_profile_ai_messages(
    profile_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_edit_access(profile, current_user)
    messages = (
        db.query(SortingProfileAiMessage)
        .filter(
            SortingProfileAiMessage.profile_id == profile.id,
            SortingProfileAiMessage.user_id == current_user.id,
        )
        .order_by(SortingProfileAiMessage.created_at.asc())
        .all()
    )
    return [_serialize_ai_message(message) for message in messages]


@router.post("/profiles/{profile_id}/ai/messages", response_model=SortingProfileAiMessageResponse)
def create_profile_ai_message(
    profile_id: UUID,
    payload: SortingProfileAiRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    request_id = uuid4().hex[:12]
    route_started_at = perf_counter()
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_edit_access(profile, current_user)
    version = _resolve_visible_version(profile, current_user, payload.version_id)
    if version is None:
        raise APIError(404, "Version not found", "PROFILE_VERSION_NOT_FOUND")
    conversation_history = _load_profile_ai_conversation(
        db,
        profile_id=profile.id,
        user_id=current_user.id,
    )

    user_message = SortingProfileAiMessage(
        profile_id=profile.id,
        user_id=current_user.id,
        version_id=version.id,
        selected_rule_id=payload.selected_rule_id,
        role="user",
        content=payload.message,
    )
    db.add(user_message)
    db.flush()

    try:
        proposal_result = generate_profile_ai_proposal(
            user=current_user,
            catalog=get_profile_catalog_service(),
            document=_document_from_version(version),
            message=payload.message,
            conversation_history=conversation_history,
            selected_rule_id=payload.selected_rule_id,
            ai_request_id=request_id,
        )
        usage_payload = _build_ai_usage_payload(proposal_result)
        assistant_message = SortingProfileAiMessage(
            profile_id=profile.id,
            user_id=current_user.id,
            version_id=version.id,
            selected_rule_id=payload.selected_rule_id,
            role="assistant",
            content=proposal_result.content,
            model=proposal_result.model,
            usage_json=usage_payload,
            proposal_json=proposal_result.proposal,
        )
        db.add(assistant_message)
        db.flush()
        _record_chat_usage(db, current_user, profile, assistant_message, proposal_result)
        db.commit()
        db.refresh(assistant_message)

        logger.info(
            "profile_ai.http_complete %s",
            json.dumps(
                {
                    "request_id": request_id,
                    "profile_id": str(profile.id),
                    "version_id": str(version.id),
                    "user_id": str(current_user.id),
                    "streaming": False,
                    "route_total_ms": round((perf_counter() - route_started_at) * 1000, 1),
                    "generation_ms": getattr(proposal_result, "performance", None).get("total_ms") if getattr(proposal_result, "performance", None) else None,
                    "tool_call_count": len(proposal_result.tool_trace),
                    "proposal_count": len(proposal_result.proposal.get("proposals", [])) if proposal_result.proposal else 0,
                },
                sort_keys=True,
            ),
        )
        return _serialize_ai_message(assistant_message)
    except Exception:
        logger.exception(
            "profile_ai.http_failed %s",
            json.dumps(
                {
                    "request_id": request_id,
                    "profile_id": str(profile.id),
                    "version_id": str(version.id),
                    "user_id": str(current_user.id),
                    "streaming": False,
                    "route_elapsed_ms": round((perf_counter() - route_started_at) * 1000, 1),
                },
                sort_keys=True,
            ),
        )
        raise


@router.post("/profiles/{profile_id}/ai/messages/stream")
def create_profile_ai_message_stream(
    profile_id: UUID,
    payload: SortingProfileAiRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    request_id = uuid4().hex[:12]
    route_started_at = perf_counter()
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_edit_access(profile, current_user)
    version = _resolve_visible_version(profile, current_user, payload.version_id)
    if version is None:
        raise APIError(404, "Version not found", "PROFILE_VERSION_NOT_FOUND")
    conversation_history = _load_profile_ai_conversation(
        db,
        profile_id=profile.id,
        user_id=current_user.id,
    )

    user_message = SortingProfileAiMessage(
        profile_id=profile.id,
        user_id=current_user.id,
        version_id=version.id,
        selected_rule_id=payload.selected_rule_id,
        role="user",
        content=payload.message,
    )
    db.add(user_message)
    db.flush()

    def event_generator():
        try:
            proposal_result = None
            for event in generate_profile_ai_proposal_streaming(
                user=current_user,
                catalog=get_profile_catalog_service(),
                document=_document_from_version(version),
                message=payload.message,
                conversation_history=conversation_history,
                selected_rule_id=payload.selected_rule_id,
                ai_request_id=request_id,
            ):
                if isinstance(event, AiProgressEvent):
                    yield f"data: {json.dumps({'type': event.type, **event.data})}\n\n"
                elif isinstance(event, AiProposalResult):
                    proposal_result = event

            if proposal_result is None:
                yield f"data: {json.dumps({'type': 'error', 'error': 'AI did not produce a result'})}\n\n"
                return

            usage_with_trace = _build_ai_usage_payload(proposal_result)
            assistant_message = SortingProfileAiMessage(
                profile_id=profile.id,
                user_id=current_user.id,
                version_id=version.id,
                selected_rule_id=payload.selected_rule_id,
                role="assistant",
                content=proposal_result.content,
                model=proposal_result.model,
                usage_json=usage_with_trace,
                proposal_json=proposal_result.proposal,
            )
            db.add(assistant_message)
            db.flush()
            _record_chat_usage(db, current_user, profile, assistant_message, proposal_result)
            db.commit()
            db.refresh(assistant_message)

            logger.info(
                "profile_ai.http_complete %s",
                json.dumps(
                    {
                        "request_id": request_id,
                        "profile_id": str(profile.id),
                        "version_id": str(version.id),
                        "user_id": str(current_user.id),
                        "streaming": True,
                        "route_total_ms": round((perf_counter() - route_started_at) * 1000, 1),
                        "generation_ms": getattr(proposal_result, "performance", None).get("total_ms") if getattr(proposal_result, "performance", None) else None,
                        "tool_call_count": len(proposal_result.tool_trace),
                        "proposal_count": len(proposal_result.proposal.get("proposals", [])) if proposal_result.proposal else 0,
                    },
                    sort_keys=True,
                ),
            )

            msg_data = _serialize_ai_message(assistant_message)
            yield f"data: {json.dumps({'type': 'complete', 'message': msg_data.model_dump(mode='json')})}\n\n"
        except APIError as exc:
            logger.warning(
                "profile_ai.http_error %s",
                json.dumps(
                    {
                        "request_id": request_id,
                        "profile_id": str(profile.id),
                        "version_id": str(version.id),
                        "user_id": str(current_user.id),
                        "streaming": True,
                        "route_elapsed_ms": round((perf_counter() - route_started_at) * 1000, 1),
                        "error_code": exc.error_code,
                        "error_message": exc.error_message,
                    },
                    sort_keys=True,
                ),
            )
            yield f"data: {json.dumps({'type': 'error', 'error': exc.error_message, 'code': exc.error_code})}\n\n"
        except Exception as exc:
            logger.exception(
                "profile_ai.http_failed %s",
                json.dumps(
                    {
                        "request_id": request_id,
                        "profile_id": str(profile.id),
                        "version_id": str(version.id),
                        "user_id": str(current_user.id),
                        "streaming": True,
                        "route_elapsed_ms": round((perf_counter() - route_started_at) * 1000, 1),
                    },
                    sort_keys=True,
                ),
            )
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc), 'code': 'AI_ERROR'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/profiles/{profile_id}/ai/messages/{message_id}/apply", response_model=SortingProfileVersionResponse)
def apply_profile_ai_message(
    profile_id: UUID,
    message_id: UUID,
    payload: SortingProfileAiApplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_edit_access(profile, current_user)
    message = (
        db.query(SortingProfileAiMessage)
        .filter(
            SortingProfileAiMessage.id == message_id,
            SortingProfileAiMessage.profile_id == profile.id,
            SortingProfileAiMessage.user_id == current_user.id,
            SortingProfileAiMessage.role == "assistant",
        )
        .first()
    )
    if message is None or not isinstance(message.proposal_json, dict):
        raise APIError(404, "AI proposal not found", "PROFILE_AI_MESSAGE_NOT_FOUND")
    base_version = _resolve_visible_version(profile, current_user, message.version_id)
    if base_version is None:
        raise APIError(404, "Base version not found", "PROFILE_VERSION_NOT_FOUND")

    next_rules = apply_profile_ai_proposal(
        rules=base_version.rules_json or [],
        selected_rule_id=message.selected_rule_id,
        proposal=copy.deepcopy(message.proposal_json),
    )

    # Generate a concise change note via Haiku
    change_note = payload.change_note
    if not change_note:
        # Find the user message that triggered this AI response
        user_msg = (
            db.query(SortingProfileAiMessage)
            .filter(
                SortingProfileAiMessage.profile_id == profile.id,
                SortingProfileAiMessage.user_id == current_user.id,
                SortingProfileAiMessage.role == "user",
                SortingProfileAiMessage.created_at < message.created_at,
            )
            .order_by(SortingProfileAiMessage.created_at.desc())
            .first()
        )
        user_text = user_msg.content if user_msg else ""
        try:
            from app.services.profile_ai import get_user_openrouter_key
            api_key = get_user_openrouter_key(current_user)
            note_result = generate_change_note(
                api_key=api_key,
                user_message=user_text,
                proposal=message.proposal_json,
            )
            change_note = note_result.text
            record_ai_usage(
                db,
                user_id=current_user.id,
                profile_id=profile.id,
                message_id=message.id,
                purpose="change_note",
                model=note_result.model,
                usage=note_result.usage,
                generation_ids=[note_result.generation_id] if note_result.generation_id else None,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Change note generation failed: %s", exc)
            change_note = f"Applied AI proposal from {message.created_at.date().isoformat()}"

    version = _create_version(
        db=db,
        profile=profile,
        current_user=current_user,
        created_via="assistant",
        payload=SortingProfileVersionCreateRequest(
            name=base_version.name,
            description=base_version.description,
            default_category_id=base_version.default_category_id,
            rules=next_rules,
            fallback_mode=base_version.fallback_mode_json or {},
            change_note=change_note,
            label=payload.label,
            publish=payload.publish,
        ),
    )
    message.applied_version_id = version.id
    message.applied_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(version)
    return _serialize_version_detail(version)



# --- Machines -----------------------------------------------------------------------


@router.put("/machines/{machine_id}/profile-assignment", response_model=MachineProfileAssignmentResponse)
def assign_machine_profile(
    machine_id: UUID,
    payload: MachineProfileAssignmentUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    machine = (
        db.query(Machine)
        .filter(Machine.id == machine_id, Machine.owner_id == current_user.id)
        .first()
    )
    if machine is None:
        raise APIError(404, "Machine not found", "MACHINE_NOT_FOUND")

    profile = _get_profile_or_404(db, payload.profile_id)
    version = _get_profile_version_or_404(profile, payload.version_id)
    _require_profile_assignable(profile, current_user, db)
    if profile.owner_id != current_user.id and not version.is_published:
        raise APIError(403, "Only published versions can be assigned from other users", "PROFILE_VERSION_NOT_PUBLISHED")

    assignment = _upsert_machine_assignment(
        db,
        machine=machine,
        profile=profile,
        version=version,
        assigned_by_id=current_user.id,
    )

    db.commit()
    db.refresh(assignment)
    saved_profile_ids = _saved_profile_ids(db, current_user.id)
    return _serialize_machine_assignment(db, assignment, current_user, saved_profile_ids)


@router.get("/machines/{machine_id}/profile-assignment", response_model=MachineProfileAssignmentResponse | None)
def get_owned_machine_profile_assignment(
    machine_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    machine = (
        db.query(Machine)
        .filter(Machine.id == machine_id, Machine.owner_id == current_user.id)
        .first()
    )
    if machine is None:
        raise APIError(404, "Machine not found", "MACHINE_NOT_FOUND")
    if machine.profile_assignment is None:
        return None
    return _serialize_machine_assignment(db, machine.profile_assignment, current_user, _saved_profile_ids(db, current_user.id))


@router.delete("/machines/{machine_id}/profile-assignment")
def clear_machine_profile_assignment(
    machine_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    assignment = (
        db.query(MachineProfileAssignment)
        .join(Machine, Machine.id == MachineProfileAssignment.machine_id)
        .filter(Machine.id == machine_id, Machine.owner_id == current_user.id)
        .first()
    )
    if assignment is None:
        raise APIError(404, "Machine assignment not found", "MACHINE_PROFILE_ASSIGNMENT_NOT_FOUND")
    db.delete(assignment)
    db.commit()
    return {"ok": True}


# What a sorter can run, from the `features` it names when it asks. A sorter
# that names none is one from before the program: it reads the flat map and
# nothing a profile may require.
def _machine_features(features: str | None) -> frozenset[str]:
    return frozenset(item.strip() for item in (features or "").split(",") if item.strip())


def _runs_on(version: SortingProfileVersion | None, features: frozenset[str]) -> bool:
    return version is None or set(_version_requires(version)) <= features


@router.get("/machine/profile-assignment", response_model=MachineProfileAssignmentResponse | None)
def get_machine_profile_assignment(
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    assignment = machine.profile_assignment
    if assignment is None:
        return None
    return _serialize_machine_assignment(db, assignment, machine.owner, _saved_profile_ids(db, machine.owner_id))


@router.put("/machine/profile-assignment", response_model=MachineProfileAssignmentResponse)
def assign_current_machine_profile(
    payload: MachineProfileAssignmentUpdateRequest,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    profile = _get_profile_or_404(db, payload.profile_id)
    version = _get_profile_version_or_404(profile, payload.version_id)
    _require_profile_assignable_for_machine(profile, version, machine.owner_id, db)

    assignment = _upsert_machine_assignment(
        db,
        machine=machine,
        profile=profile,
        version=version,
        assigned_by_id=machine.owner_id,
    )

    db.commit()
    db.refresh(assignment)
    return _serialize_machine_assignment(db, assignment, machine.owner, _saved_profile_ids(db, machine.owner_id))


@router.get("/machine/profiles/library", response_model=MachineProfileLibraryResponse)
def get_machine_profile_library(
    features: str | None = Query(default=None),
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    """The profiles a machine may run: its owner's, those in the owner's
    library, and Hive's defaults, less any this sorter cannot run."""
    runs = _machine_features(features)
    accessible_profiles = _accessible_profiles_for_user(db, machine.owner_id)
    saved_profile_ids = _saved_profile_ids(db, machine.owner_id)
    profiles = []
    for profile in accessible_profiles:
        versions = _visible_versions_for_user(profile, machine.owner)
        if versions and not _runs_on(versions[0], runs):
            continue
        profiles.append(_serialize_profile_summary(db, profile, machine.owner, saved_profile_ids))
    assignment = (
        _serialize_machine_assignment(db, machine.profile_assignment, machine.owner, saved_profile_ids)
        if machine.profile_assignment is not None
        else None
    )
    return {
        "machine_id": machine.id,
        "machine_name": machine.name,
        "assignment": assignment,
        "profiles": profiles,
    }


@router.get("/machine/profiles/{profile_id}", response_model=SortingProfileDetailResponse)
def get_machine_profile_detail(
    profile_id: UUID,
    version_id: UUID | None = None,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_assignable(profile, machine.owner, db)
    current_version = _resolve_visible_version(profile, machine.owner, version_id)
    return _serialize_profile_detail(
        db,
        profile,
        machine.owner,
        _saved_profile_ids(db, machine.owner_id),
        current_version=current_version,
    )


@router.get("/machine/profiles/versions/{version_id}/artifact")
def download_machine_profile_artifact(
    version_id: UUID,
    request: Request,
    format: str = Query(default="legacy", pattern="^(program|legacy)$"),
    features: str | None = Query(default=None),
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    """A version as the asking sorter runs it: the program for a sorter that
    asks for it, the flat part map for one that does not."""
    version = db.query(SortingProfileVersion).filter(SortingProfileVersion.id == version_id).first()
    if version is None:
        raise APIError(404, "Version not found", "PROFILE_VERSION_NOT_FOUND")
    profile = version.profile
    if profile is None:
        raise APIError(404, "Profile not found", "PROFILE_NOT_FOUND")
    _require_profile_assignable_for_machine(profile, version, machine.owner_id, db)
    if not _runs_on(version, _machine_features(features)):
        raise APIError(
            409,
            "This profile needs newer sorter software. Update the sorter to run it.",
            "PROFILE_NEEDS_NEWER_SORTER",
        )
    return _artifact_response(version, format, request)


@router.post("/machine/profile-activation", response_model=MachineProfileAssignmentResponse)
def report_machine_profile_activation(
    payload: MachineProfileActivationRequest,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    assignment = machine.profile_assignment
    if assignment is None:
        raise APIError(404, "Machine profile assignment not found", "MACHINE_PROFILE_ASSIGNMENT_NOT_FOUND")
    version = db.query(SortingProfileVersion).filter(SortingProfileVersion.id == payload.version_id).first()
    if version is None or version.profile_id != assignment.profile_id:
        raise APIError(400, "Version does not belong to the assigned profile", "MACHINE_PROFILE_VERSION_INVALID")
    assignment.active_version_id = version.id
    assignment.artifact_hash = payload.artifact_hash or version.compiled_hash
    assignment.last_error = None
    assignment.last_synced_at = datetime.now(timezone.utc)
    assignment.last_activated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(assignment)
    return _serialize_machine_assignment(db, assignment, machine.owner, _saved_profile_ids(db, machine.owner_id))


# --- Artifacts ------------------------------------------------------------------------

# The flat map is built on request and kept, gzipped, for the last few
# versions asked for: a sorter from before the program downloads a profile
# when it is applied, and a busy profile's map runs to tens of MB (a tenth of
# that gzipped).
_LEGACY_CACHE: OrderedDict[tuple[str, str, int], bytes] = OrderedDict()
_LEGACY_CACHE_SIZE = 4
_legacy_lock = threading.Lock()


def _json_response(body: bytes, request: Request | None, *, gzipped: bool = False) -> Response:
    """JSON, gzipped for a client that takes it (every sorter does): artifacts
    are large and compress about tenfold."""
    accepts_gzip = request is not None and "gzip" in (request.headers.get("accept-encoding") or "")
    if gzipped and not accepts_gzip:
        return Response(content=gzip.decompress(body), media_type="application/json")
    if not gzipped and accepts_gzip and len(body) > 64_000:
        body, gzipped = gzip.compress(body, compresslevel=5), True
    headers = {"Content-Encoding": "gzip", "Vary": "Accept-Encoding"} if gzipped else None
    return Response(content=body, media_type="application/json", headers=headers)


def _artifact_response(version: SortingProfileVersion, format: str, request: Request | None = None) -> Response:
    artifact = version.compiled_artifact_json or {}
    if format == "program" or "program" not in artifact:
        # A version compiled before the program is already the flat map.
        return _json_response(json.dumps({"artifact": artifact}).encode(), request)
    index = get_profile_catalog_service().index()
    key = (str(version.id), str(artifact.get("artifact_hash")), index.generation)
    with _legacy_lock:
        body = _LEGACY_CACHE.get(key)
        if body is not None:
            _LEGACY_CACHE.move_to_end(key)
    if body is None:
        body = gzip.compress(json.dumps({"artifact": expand_legacy(artifact, index)}).encode(), compresslevel=5)
        with _legacy_lock:
            _LEGACY_CACHE[key] = body
            while len(_LEGACY_CACHE) > _LEGACY_CACHE_SIZE:
                _LEGACY_CACHE.popitem(last=False)
    return _json_response(body, request, gzipped=True)


# --- Helpers ----------------------------------------------------------------------------


def _query_profiles_for_scope(db: Session, current_user: User, scope: str, query: str) -> list[SortingProfile]:
    q = db.query(SortingProfile)
    search = f"%{query.lower()}%" if query else None
    if scope == "mine":
        q = q.filter(SortingProfile.owner_id == current_user.id)
    elif scope == "library":
        q = (
            q.join(
                SortingProfileLibraryEntry,
                SortingProfileLibraryEntry.profile_id == SortingProfile.id,
            )
            .filter(SortingProfileLibraryEntry.user_id == current_user.id)
        )
    elif scope == "defaults":
        q = q.filter(SortingProfile.default_rank.is_not(None))
    else:
        q = q.filter(
            SortingProfile.visibility == "public",
            SortingProfile.latest_published_version_number.is_not(None),
        )

    if search:
        q = q.filter(
            or_(
                SortingProfile.name.ilike(search),
                SortingProfile.description.ilike(search),
            )
        )
    if scope == "defaults":
        return q.order_by(SortingProfile.default_rank.asc()).all()
    return q.order_by(SortingProfile.updated_at.desc()).all()


def _saved_profile_ids(db: Session, user_id: UUID) -> set[UUID]:
    rows = (
        db.query(SortingProfileLibraryEntry.profile_id)
        .filter(SortingProfileLibraryEntry.user_id == user_id)
        .all()
    )
    return {row[0] for row in rows}


def _default_profiles(db: Session) -> list[SortingProfile]:
    return (
        db.query(SortingProfile)
        .filter(
            SortingProfile.default_rank.is_not(None),
            SortingProfile.latest_published_version_number.is_not(None),
        )
        .order_by(SortingProfile.default_rank.asc())
        .all()
    )


def _accessible_profiles_for_user(db: Session, user_id: UUID) -> list[SortingProfile]:
    profiles = (
        db.query(SortingProfile)
        .filter(SortingProfile.owner_id == user_id)
        .order_by(SortingProfile.updated_at.desc())
        .all()
    )
    profile_ids = {profile.id for profile in profiles}
    library_profiles = (
        db.query(SortingProfile)
        .join(SortingProfileLibraryEntry, SortingProfileLibraryEntry.profile_id == SortingProfile.id)
        .filter(SortingProfileLibraryEntry.user_id == user_id)
        .order_by(SortingProfile.updated_at.desc())
        .all()
    )
    for profile in [*library_profiles, *_default_profiles(db)]:
        if profile.owner_id != user_id and profile.latest_published_version_number is None:
            continue
        if profile.id not in profile_ids:
            profiles.append(profile)
            profile_ids.add(profile.id)
    return profiles


def _get_profile_or_404(db: Session, profile_id: UUID) -> SortingProfile:
    profile = db.query(SortingProfile).filter(SortingProfile.id == profile_id).first()
    if profile is None:
        raise APIError(404, "Profile not found", "PROFILE_NOT_FOUND")
    return profile


def _get_profile_version_or_404(profile: SortingProfile, version_id: UUID) -> SortingProfileVersion:
    for version in profile.versions:
        if version.id == version_id:
            return version
    raise APIError(404, "Version not found", "PROFILE_VERSION_NOT_FOUND")


def _resolve_visible_version(
    profile: SortingProfile,
    current_user: User,
    version_id: UUID | None,
) -> SortingProfileVersion | None:
    versions = list(profile.versions)
    if not versions:
        return None
    versions.sort(key=lambda version: version.version_number, reverse=True)
    if version_id is not None:
        version = next((version for version in versions if version.id == version_id), None)
        if version is None:
            raise APIError(404, "Version not found", "PROFILE_VERSION_NOT_FOUND")
        if profile.owner_id != current_user.id and not version.is_published:
            raise APIError(403, "Version is not published", "PROFILE_VERSION_NOT_PUBLISHED")
        return version
    if profile.owner_id == current_user.id:
        return versions[0]
    published = [version for version in versions if version.is_published]
    if not published:
        raise APIError(404, "No published version is available", "PROFILE_VERSION_NOT_FOUND")
    return published[0]


def _require_profile_view_access(profile: SortingProfile, current_user: User) -> None:
    if profile.owner_id == current_user.id:
        return
    if profile.visibility in {"public", "unlisted"}:
        return
    raise APIError(403, "You do not have access to this profile", "PROFILE_ACCESS_DENIED")


def _require_profile_edit_access(profile: SortingProfile, current_user: User) -> None:
    if profile.owner_id != current_user.id:
        raise APIError(403, "Only the owner can edit this profile", "PROFILE_EDIT_DENIED")


def _require_profile_assignable(profile: SortingProfile, current_user: User, db: Session) -> None:
    if profile.owner_id == current_user.id or profile.default_rank is not None:
        return
    if profile.visibility not in {"public", "unlisted"}:
        raise APIError(403, "This profile cannot be assigned", "PROFILE_ASSIGN_DENIED")
    saved_profile_ids = _saved_profile_ids(db, current_user.id)
    if profile.id not in saved_profile_ids:
        raise APIError(403, "Save the profile to your library before assigning it", "PROFILE_LIBRARY_REQUIRED")


def _require_profile_assignable_for_machine(profile: SortingProfile, version: SortingProfileVersion, owner_id: UUID, db: Session) -> None:
    if profile.owner_id == owner_id:
        return
    if not version.is_published:
        raise APIError(403, "Only published versions are available to machines", "PROFILE_VERSION_NOT_PUBLISHED")
    if profile.default_rank is not None:
        return
    saved_profile_ids = _saved_profile_ids(db, owner_id)
    if profile.id not in saved_profile_ids:
        raise APIError(403, "Profile is not in the machine owner's library", "PROFILE_LIBRARY_REQUIRED")


def _normalize_visibility(value: str) -> str:
    normalized = (value or "private").strip().lower()
    if normalized not in {"private", "unlisted", "public"}:
        raise APIError(400, "Visibility must be private, unlisted, or public", "PROFILE_VISIBILITY_INVALID")
    return normalized


def _sanitize_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    return [tag.strip() for tag in tags if isinstance(tag, str) and tag.strip()]


def _origin(request: Request | None, created_via: str | None) -> tuple[str, UUID | None]:
    if created_via:
        return created_via, None
    if request is not None and getattr(request.state, "auth_via_api_key", False):
        return "api", getattr(request.state, "api_key_id", None)
    return "web", None


def _create_version(
    *,
    db: Session,
    profile: SortingProfile,
    current_user: User,
    payload: SortingProfileVersionCreateRequest,
    request: Request | None = None,
    created_via: str | None = None,
) -> SortingProfileVersion:
    catalog = get_profile_catalog_service()
    document = payload.model_dump()
    document["id"] = str(profile.id)
    owner = profile.owner or current_user
    document["rules"] = kits_from_set_rules(db, catalog, owner, document["rules"])
    kits = kits_for_rules(db, profile.owner_id, document["rules"])
    compiled = catalog.compile_document(document, kits)
    problems = [problem.as_dict() for problem in compiled.problems] + missing_kits(document["rules"], kits)
    if problems:
        raise APIError(
            400,
            f"{len(problems)} problem(s) keep this profile from compiling; nothing was saved",
            "PROFILE_RULES_INVALID",
            details=problems,
        )
    artifact = compiled.artifact
    stats = artifact["stats"]
    via, key_id = _origin(request, created_via)
    next_version_number = int(profile.latest_version_number or 0) + 1
    version = SortingProfileVersion(
        profile_id=profile.id,
        created_by_id=current_user.id,
        version_number=next_version_number,
        label=(payload.label or "").strip() or None,
        change_note=(payload.change_note or "").strip() or None,
        name=payload.name.strip() or profile.name,
        description=(payload.description or "").strip() or None,
        default_category_id=artifact["default_category_id"],
        rules_json=artifact["rules"],
        fallback_mode_json=artifact["fallback_mode"],
        compiled_artifact_json=artifact,
        compiled_stats_json={**stats, "warnings": compiled.warnings, "requires": artifact["requires"]},
        compiled_hash=artifact["artifact_hash"],
        compiled_part_count=int(stats.get("sorted") or 0),
        coverage_ratio=(stats["matched"] / stats["total_parts"]) if stats.get("total_parts") else None,
        is_published=bool(payload.publish),
        created_via=via,
        created_via_key_id=key_id,
    )
    db.add(version)
    profile.latest_version_number = next_version_number
    if payload.publish:
        profile.latest_published_version_number = next_version_number
    profile.profile_type = artifact["profile_type"]
    profile.name = payload.name.strip() or profile.name
    profile.description = (payload.description or "").strip() or None
    profile.updated_at = datetime.now(timezone.utc)
    db.flush()
    return version


def _document_from_version(version: SortingProfileVersion) -> dict:
    return {
        "id": str(version.profile_id),
        "name": version.name,
        "description": version.description,
        "default_category_id": version.default_category_id,
        "rules": copy.deepcopy(version.rules_json or []),
        "fallback_mode": copy.deepcopy(version.fallback_mode_json or {}),
    }


def _rules_include_kits(rules: list | None) -> bool:
    for rule in rules or []:
        data = rule.model_dump() if hasattr(rule, "model_dump") else rule
        if not isinstance(data, dict):
            continue
        if data.get("rule_type") in ("set", "kit"):
            return True
        if _rules_include_kits(data.get("children")):
            return True
    return False


def _profile_type_for_version(version: SortingProfileVersion | None) -> str:
    # From the rules, not the compiled artifact, so a list of profiles never
    # loads an artifact.
    if version is None:
        return "rule"
    return "set" if _rules_include_kits(version.rules_json) else "rule"


def _version_bins(version: SortingProfileVersion) -> list[dict[str, Any]]:
    stats = version.compiled_stats_json if isinstance(version.compiled_stats_json, dict) else {}
    return [item for item in stats.get("bins") or [] if isinstance(item, dict) and item.get("id")]


def _version_requires(version: SortingProfileVersion) -> list[str]:
    stats = version.compiled_stats_json if isinstance(version.compiled_stats_json, dict) else {}
    return list(stats.get("requires") or [])


def _serialize_profile_summary(
    db: Session,
    profile: SortingProfile,
    current_user: User,
    saved_profile_ids: set[UUID],
    *,
    effective_version: SortingProfileVersion | None = None,
) -> SortingProfileSummaryResponse:
    versions = _visible_versions_for_user(profile, current_user)
    latest_version = versions[0] if versions else None
    latest_published = next((version for version in versions if version.is_published), None)
    profile_type = _profile_type_for_version(effective_version or latest_version)
    source = None
    if profile.source_profile_id:
        source_profile = db.query(SortingProfile).filter(SortingProfile.id == profile.source_profile_id).first()
        if source_profile is not None:
            source = {
                "profile_id": source_profile.id,
                "profile_name": source_profile.name,
                "version_number": profile.source_version_number,
            }

    return SortingProfileSummaryResponse(
        id=profile.id,
        name=profile.name,
        description=profile.description,
        visibility=profile.visibility,
        profile_type=profile_type,
        tags=list(profile.tags or []),
        latest_version_number=int(profile.latest_version_number or 0),
        latest_published_version_number=profile.latest_published_version_number,
        library_count=int(profile.library_count or 0),
        fork_count=int(profile.fork_count or 0),
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        owner={
            "id": profile.owner.id,
            "display_name": profile.owner.display_name,
            "github_login": profile.owner.github_login,
            "avatar_url": profile.owner.avatar_url,
        },
        source=source,
        saved_in_library=profile.id in saved_profile_ids,
        is_owner=profile.owner_id == current_user.id,
        is_default=profile.default_rank is not None,
        default_rank=profile.default_rank,
        web_url=f"{settings.public_app_url}/profiles/{profile.id}",
        latest_version=_serialize_version_summary(latest_version) if latest_version else None,
        latest_published_version=_serialize_version_summary(latest_published) if latest_published else None,
    )


def _serialize_profile_detail(
    db: Session,
    profile: SortingProfile,
    current_user: User,
    saved_profile_ids: set[UUID],
    *,
    current_version: SortingProfileVersion | None,
) -> SortingProfileDetailResponse:
    summary = _serialize_profile_summary(db, profile, current_user, saved_profile_ids)
    versions = _visible_versions_for_user(profile, current_user)
    payload = summary.model_dump()
    payload["versions"] = [_serialize_version_summary(version).model_dump() for version in versions]
    payload["current_version"] = _serialize_version_detail(current_version).model_dump() if current_version else None
    return SortingProfileDetailResponse(**payload)


def _visible_versions_for_user(profile: SortingProfile, current_user: User) -> list[SortingProfileVersion]:
    versions = sorted(profile.versions, key=lambda version: version.version_number, reverse=True)
    if profile.owner_id == current_user.id:
        return versions
    return [version for version in versions if version.is_published]


def _serialize_version_summary(version: SortingProfileVersion | None) -> SortingProfileVersionSummaryResponse | None:
    if version is None:
        return None
    rules_summary = []
    for rule in (version.rules_json or []):
        rules_summary.append({
            "name": rule.get("name", "Untitled"),
            "rule_type": rule.get("rule_type", "filter"),
            "set_source": rule.get("set_source"),
            "set_num": rule.get("set_num"),
            "set_meta": rule.get("set_meta"),
            "disabled": rule.get("disabled", False),
            "condition_count": len(rule.get("conditions", [])),
            "child_count": len(rule.get("children", [])),
        })
    return SortingProfileVersionSummaryResponse(
        id=version.id,
        version_number=version.version_number,
        label=version.label,
        change_note=version.change_note,
        is_published=version.is_published,
        compiled_hash=version.compiled_hash,
        compiled_part_count=version.compiled_part_count,
        coverage_ratio=version.coverage_ratio,
        created_at=version.created_at,
        rules_summary=rules_summary,
        created_via=version.created_via,
        created_via_key_name=version.created_via_key.name if version.created_via_key else None,
        requires=_version_requires(version),
        bins=_version_bins(version),
    )


def _serialize_version_detail(version: SortingProfileVersion | None) -> SortingProfileVersionResponse | None:
    if version is None:
        return None
    summary = _serialize_version_summary(version)
    if summary is None:
        return None
    stats = version.compiled_stats_json if isinstance(version.compiled_stats_json, dict) else {}
    if described(version):
        artifact = version.compiled_artifact_json or {}
        raw_categories = artifact.get("categories", {})
        category_order = artifact.get("category_order") or []
        warnings = list(stats.get("warnings") or [])
    else:
        # Compiled before bins were described: its rules compiled again, for
        # display only (and never its stored map, which runs to tens of MB).
        try:
            display = display_for(object_session(version), version)
            raw_categories, category_order, warnings = display["categories"], display["category_order"], display["warnings"]
        except Exception:
            logger.exception("profiles: version %s could not be described", version.id)
            raw_categories = {
                str(rule.get("id")): {"name": rule.get("name") or "Untitled"}
                for rule in version.rules_json or []
                if isinstance(rule, dict)
            }
            category_order, warnings = list(raw_categories), []
    categories: dict[str, dict[str, Any]] = {}
    if isinstance(raw_categories, dict):
        for category_id, category_meta in raw_categories.items():
            categories[str(category_id)] = dict(category_meta) if isinstance(category_meta, dict) else {}
    payload = summary.model_dump()
    payload.update(
        {
            "name": version.name,
            "description": version.description,
            "default_category_id": version.default_category_id,
            "rules": version.rules_json or [],
            "fallback_mode": version.fallback_mode_json or {},
            # The totals; each bin's own count and examples are in categories.
            "compiled_stats": {
                key: value
                for key, value in stats.items()
                if key not in ("warnings", "requires", "bins", "bins_backfilled", "per_category", "samples")
            },
            "categories": categories,
            "category_order": [category for category in category_order if category in categories],
            "warnings": warnings,
        }
    )
    return SortingProfileVersionResponse(**payload)


def _serialize_ai_message(message: SortingProfileAiMessage) -> SortingProfileAiMessageResponse:
    usage = dict(message.usage_json) if isinstance(message.usage_json, dict) else None
    tool_trace = []
    if usage and "tool_trace" in usage:
        tool_trace = usage.pop("tool_trace", [])
    return SortingProfileAiMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        model=message.model,
        version_id=message.version_id,
        applied_version_id=message.applied_version_id,
        selected_rule_id=message.selected_rule_id,
        usage=usage,
        proposal=message.proposal_json if isinstance(message.proposal_json, dict) else None,
        tool_trace=tool_trace,
        applied_at=message.applied_at,
        created_at=message.created_at,
    )


def _load_profile_ai_conversation(
    db: Session,
    *,
    profile_id: UUID,
    user_id: UUID,
    limit: int = AI_CONVERSATION_HISTORY_LIMIT,
) -> list[dict[str, str]]:
    messages = (
        db.query(SortingProfileAiMessage)
        .filter(
            SortingProfileAiMessage.profile_id == profile_id,
            SortingProfileAiMessage.user_id == user_id,
            SortingProfileAiMessage.role.in_(("user", "assistant")),
        )
        .order_by(SortingProfileAiMessage.created_at.desc())
        .limit(limit)
        .all()
    )

    conversation: list[dict[str, str]] = []
    for message in reversed(messages):
        if not message.content or not message.content.strip():
            continue
        conversation.append({
            "role": message.role,
            "content": message.content.strip(),
        })
    return conversation


def _serialize_machine_assignment(
    db: Session,
    assignment: MachineProfileAssignment | None,
    current_user: User,
    saved_profile_ids: set[UUID],
) -> MachineProfileAssignmentResponse | None:
    if assignment is None:
        return None
    return MachineProfileAssignmentResponse(
        machine_id=assignment.machine_id,
        profile=_serialize_profile_summary(
            db,
            assignment.profile,
            current_user,
            saved_profile_ids,
            effective_version=assignment.desired_version or assignment.active_version,
        ),
        desired_version=_serialize_version_summary(assignment.desired_version),
        active_version=_serialize_version_summary(assignment.active_version),
        artifact_hash=assignment.artifact_hash,
        last_error=assignment.last_error,
        last_synced_at=assignment.last_synced_at,
        last_activated_at=assignment.last_activated_at,
    )


def _upsert_machine_assignment(
    db: Session,
    *,
    machine: Machine,
    profile: SortingProfile,
    version: SortingProfileVersion,
    assigned_by_id: UUID,
) -> MachineProfileAssignment:
    from app.models.machine_set_progress import MachineSetProgress

    assignment = machine.profile_assignment
    if assignment is None:
        assignment = MachineProfileAssignment(
            machine_id=machine.id,
            profile_id=profile.id,
            desired_version_id=version.id,
            assigned_by_id=assigned_by_id,
        )
        db.add(assignment)
        return assignment

    assignment_changed = (
        assignment.profile_id != profile.id
        or assignment.desired_version_id != version.id
    )
    assignment.profile_id = profile.id
    assignment.desired_version_id = version.id
    assignment.assigned_by_id = assigned_by_id
    assignment.last_error = None
    if assignment_changed:
        assignment.active_version_id = None
        assignment.artifact_hash = None
        assignment.last_synced_at = None
        assignment.last_activated_at = None
        db.query(MachineSetProgress).filter(
            MachineSetProgress.assignment_id == assignment.id
        ).delete(synchronize_session=False)
    return assignment
