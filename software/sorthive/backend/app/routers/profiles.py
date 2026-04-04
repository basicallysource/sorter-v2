from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.deps import get_current_machine, get_current_user, get_db, verify_csrf
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
    SortingProfileArtifactResponse,
    SortingProfileCreateRequest,
    SortingProfileDetailResponse,
    SortingProfileForkRequest,
    SortingProfilePreviewRequest,
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
    generate_profile_ai_proposal,
    generate_profile_ai_proposal_streaming,
)
from app.services.profile_catalog import get_profile_catalog_service

router = APIRouter(prefix="/api", tags=["profiles"])

CATALOG_SYNC_TYPES = {"categories", "colors", "parts", "brickstore", "prices"}


@router.get("/profile-catalog/status")
def get_profile_catalog_status(
    _current_user: User = Depends(get_current_user),
):
    return get_profile_catalog_service().status()


@router.post("/profile-catalog/sync/{sync_type}")
def start_profile_catalog_sync(
    sync_type: str,
    _current_user: User = Depends(get_current_user),
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
    _current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    get_profile_catalog_service().stop_sync()
    return {"stopped": True}


@router.get("/profile-catalog/search-parts")
def search_profile_catalog_parts(
    q: str = "",
    cat_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    _current_user: User = Depends(get_current_user),
):
    return get_profile_catalog_service().search_parts(q, cat_id, limit, offset)


@router.post("/profiles/preview")
def preview_sorting_profile(
    payload: SortingProfilePreviewRequest,
    _current_user: User = Depends(get_current_user),
):
    return get_profile_catalog_service().preview_document(payload.model_dump())


@router.post("/profiles/preview-rule")
def preview_sorting_rule(
    payload: SortingProfilePreviewRequest,
    rule_id: str | None = None,
    q: str = "",
    offset: int = 0,
    limit: int = 50,
    standalone: bool = False,
    _current_user: User = Depends(get_current_user),
):
    target_rule = _find_rule(payload.rules, rule_id) if rule_id else None
    if target_rule is None:
        raise APIError(404, "Rule not found", "PROFILE_RULE_NOT_FOUND")
    return get_profile_catalog_service().preview_rule(
        rule=target_rule,
        rules=[rule.model_dump() for rule in payload.rules],
        rule_id=rule_id,
        q=q,
        offset=offset,
        limit=limit,
        standalone=standalone,
    )


@router.get("/profiles", response_model=list[SortingProfileSummaryResponse])
def list_profiles(
    scope: str = Query(default="discover"),
    q: str = Query(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profiles = _query_profiles_for_scope(db, current_user, scope, q)
    saved_profile_ids = _saved_profile_ids(db, current_user.id)
    return [_serialize_profile_summary(db, profile, current_user, saved_profile_ids) for profile in profiles]


@router.post("/profiles", response_model=SortingProfileDetailResponse)
def create_profile(
    payload: SortingProfileCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    visibility = _normalize_visibility(payload.visibility)
    profile = SortingProfile(
        owner_id=current_user.id,
        name=payload.name.strip() or "Untitled Profile",
        description=(payload.description or "").strip() or None,
        visibility=visibility,
        tags=_sanitize_tags(payload.tags),
        latest_version_number=0,
    )
    db.add(profile)
    db.flush()

    version = _create_version(
        db=db,
        profile=profile,
        current_user=current_user,
        payload=SortingProfileVersionCreateRequest(
            name=profile.name,
            description=profile.description,
            default_category_id="misc",
            rules=[],
            fallback_mode={},
            change_note="Initial version",
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
    current_user: User = Depends(get_current_user),
):
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_view_access(profile, current_user)
    saved_profile_ids = _saved_profile_ids(db, current_user.id)
    current_version = _resolve_visible_version(profile, current_user, version_id)
    return _serialize_profile_detail(db, profile, current_user, saved_profile_ids, current_version=current_version)


@router.patch("/profiles/{profile_id}", response_model=SortingProfileDetailResponse)
def update_profile(
    profile_id: UUID,
    payload: SortingProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_edit_access(profile, current_user)
    db.delete(profile)
    db.commit()
    return {"ok": True}


@router.post("/profiles/{profile_id}/library")
def save_profile_to_library(
    profile_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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
    version_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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


@router.post("/profiles/{profile_id}/versions", response_model=SortingProfileVersionResponse)
def create_profile_version(
    profile_id: UUID,
    payload: SortingProfileVersionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_edit_access(profile, current_user)
    version = _create_version(db=db, profile=profile, current_user=current_user, payload=payload)
    db.commit()
    db.refresh(version)
    return _serialize_version_detail(version)


@router.post("/profiles/{profile_id}/versions/{version_id}/publish", response_model=SortingProfileVersionResponse)
def publish_profile_version(
    profile_id: UUID,
    version_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
    db.commit()
    db.refresh(version)
    return _serialize_version_detail(version)


@router.get("/profiles/{profile_id}/versions/{version_id}/artifact", response_model=SortingProfileArtifactResponse)
def get_profile_artifact(
    profile_id: UUID,
    version_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_view_access(profile, current_user)
    version = _resolve_visible_version(profile, current_user, version_id)
    if version is None:
        raise APIError(404, "Version not found", "PROFILE_VERSION_NOT_FOUND")
    return {"artifact": copy.deepcopy(version.compiled_artifact_json)}


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
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_edit_access(profile, current_user)
    version = _resolve_visible_version(profile, current_user, payload.version_id)
    if version is None:
        raise APIError(404, "Version not found", "PROFILE_VERSION_NOT_FOUND")

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

    proposal_result = generate_profile_ai_proposal(
        user=current_user,
        catalog=get_profile_catalog_service(),
        document=_document_from_version(version),
        message=payload.message,
        selected_rule_id=payload.selected_rule_id,
    )
    usage_with_trace = proposal_result.usage or {}
    if proposal_result.tool_trace:
        usage_with_trace["tool_trace"] = [
            {"tool": t.tool, "input": t.input, "output_summary": t.output_summary}
            for t in proposal_result.tool_trace
        ]
    assistant_message = SortingProfileAiMessage(
        profile_id=profile.id,
        user_id=current_user.id,
        version_id=version.id,
        selected_rule_id=payload.selected_rule_id,
        role="assistant",
        content=proposal_result.content,
        model=proposal_result.model,
        usage_json=usage_with_trace or None,
        proposal_json=proposal_result.proposal,
    )
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)
    return _serialize_ai_message(assistant_message)


@router.post("/profiles/{profile_id}/ai/messages/stream")
def create_profile_ai_message_stream(
    profile_id: UUID,
    payload: SortingProfileAiRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    profile = _get_profile_or_404(db, profile_id)
    _require_profile_edit_access(profile, current_user)
    version = _resolve_visible_version(profile, current_user, payload.version_id)
    if version is None:
        raise APIError(404, "Version not found", "PROFILE_VERSION_NOT_FOUND")

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
                selected_rule_id=payload.selected_rule_id,
            ):
                if isinstance(event, AiProgressEvent):
                    yield f"data: {json.dumps({'type': event.type, **event.data})}\n\n"
                elif isinstance(event, AiProposalResult):
                    proposal_result = event

            if proposal_result is None:
                yield f"data: {json.dumps({'type': 'error', 'error': 'AI did not produce a result'})}\n\n"
                return

            usage_with_trace = proposal_result.usage or {}
            if proposal_result.tool_trace:
                usage_with_trace["tool_trace"] = [
                    {"tool": t.tool, "input": t.input, "output_summary": t.output_summary}
                    for t in proposal_result.tool_trace
                ]
            assistant_message = SortingProfileAiMessage(
                profile_id=profile.id,
                user_id=current_user.id,
                version_id=version.id,
                selected_rule_id=payload.selected_rule_id,
                role="assistant",
                content=proposal_result.content,
                model=proposal_result.model,
                usage_json=usage_with_trace or None,
                proposal_json=proposal_result.proposal,
            )
            db.add(assistant_message)
            db.commit()
            db.refresh(assistant_message)

            msg_data = _serialize_ai_message(assistant_message)
            yield f"data: {json.dumps({'type': 'complete', 'message': msg_data.model_dump(mode='json')})}\n\n"
        except APIError as exc:
            yield f"data: {json.dumps({'type': 'error', 'error': exc.error_message})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"

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
            change_note = generate_change_note(
                api_key=api_key,
                user_message=user_text,
                proposal=message.proposal_json,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Change note generation failed: %s", exc)
            change_note = f"Applied AI proposal from {message.created_at.date().isoformat()}"

    version = _create_version(
        db=db,
        profile=profile,
        current_user=current_user,
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
    _require_profile_assignable(profile, current_user, db)
    version = _get_profile_version_or_404(profile, payload.version_id)
    if profile.owner_id != current_user.id and not version.is_published:
        raise APIError(403, "Only published versions can be assigned from other users", "PROFILE_VERSION_NOT_PUBLISHED")

    assignment = machine.profile_assignment
    if assignment is None:
        assignment = MachineProfileAssignment(
            machine_id=machine.id,
            profile_id=profile.id,
            desired_version_id=version.id,
            assigned_by_id=current_user.id,
        )
        db.add(assignment)
    else:
        assignment.profile_id = profile.id
        assignment.desired_version_id = version.id
        assignment.assigned_by_id = current_user.id
        assignment.last_error = None

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


@router.get("/machine/profile-assignment", response_model=MachineProfileAssignmentResponse | None)
def get_machine_profile_assignment(
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    assignment = machine.profile_assignment
    if assignment is None:
        return None
    return _serialize_machine_assignment(db, assignment, machine.owner, _saved_profile_ids(db, machine.owner_id))


@router.get("/machine/profiles/library", response_model=MachineProfileLibraryResponse)
def get_machine_profile_library(
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    accessible_profiles = _accessible_profiles_for_user(db, machine.owner_id)
    saved_profile_ids = _saved_profile_ids(db, machine.owner_id)
    profiles = [_serialize_profile_summary(db, profile, machine.owner, saved_profile_ids) for profile in accessible_profiles]
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


@router.get("/machine/profiles/versions/{version_id}/artifact", response_model=SortingProfileArtifactResponse)
def download_machine_profile_artifact(
    version_id: UUID,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    version = db.query(SortingProfileVersion).filter(SortingProfileVersion.id == version_id).first()
    if version is None:
        raise APIError(404, "Version not found", "PROFILE_VERSION_NOT_FOUND")
    profile = version.profile
    if profile is None:
        raise APIError(404, "Profile not found", "PROFILE_NOT_FOUND")
    _require_profile_assignable_for_machine(profile, version, machine.owner_id, db)
    return {"artifact": copy.deepcopy(version.compiled_artifact_json)}


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
    return q.order_by(SortingProfile.updated_at.desc()).all()


def _saved_profile_ids(db: Session, user_id: UUID) -> set[UUID]:
    rows = (
        db.query(SortingProfileLibraryEntry.profile_id)
        .filter(SortingProfileLibraryEntry.user_id == user_id)
        .all()
    )
    return {row[0] for row in rows}


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
    for profile in library_profiles:
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
    if profile.owner_id == current_user.id:
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


def _create_version(
    *,
    db: Session,
    profile: SortingProfile,
    current_user: User,
    payload: SortingProfileVersionCreateRequest,
) -> SortingProfileVersion:
    compiled = get_profile_catalog_service().compile_document(payload.model_dump())
    next_version_number = int(profile.latest_version_number or 0) + 1
    version = SortingProfileVersion(
        profile_id=profile.id,
        created_by_id=current_user.id,
        version_number=next_version_number,
        label=(payload.label or "").strip() or None,
        change_note=(payload.change_note or "").strip() or None,
        name=payload.name.strip() or profile.name,
        description=(payload.description or "").strip() or None,
        default_category_id=payload.default_category_id.strip() or "misc",
        rules_json=[rule.model_dump() if hasattr(rule, "model_dump") else rule for rule in payload.rules],
        fallback_mode_json=payload.fallback_mode.model_dump() if hasattr(payload.fallback_mode, "model_dump") else payload.fallback_mode,
        compiled_artifact_json=compiled["artifact"],
        compiled_stats_json=compiled["stats"],
        compiled_hash=compiled["artifact_hash"],
        compiled_part_count=compiled["compiled_part_count"],
        coverage_ratio=compiled["coverage_ratio"],
        is_published=bool(payload.publish),
    )
    db.add(version)
    profile.latest_version_number = next_version_number
    if payload.publish:
        profile.latest_published_version_number = next_version_number
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


def _serialize_profile_summary(
    db: Session,
    profile: SortingProfile,
    current_user: User,
    saved_profile_ids: set[UUID],
) -> SortingProfileSummaryResponse:
    versions = _visible_versions_for_user(profile, current_user)
    latest_version = versions[0] if versions else None
    latest_published = next((version for version in versions if version.is_published), None)
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
    )


def _serialize_version_detail(version: SortingProfileVersion | None) -> SortingProfileVersionResponse | None:
    if version is None:
        return None
    summary = _serialize_version_summary(version)
    if summary is None:
        return None
    payload = summary.model_dump()
    payload.update(
        {
            "name": version.name,
            "description": version.description,
            "default_category_id": version.default_category_id,
            "rules": version.rules_json or [],
            "fallback_mode": version.fallback_mode_json or {},
            "compiled_stats": version.compiled_stats_json,
            "categories": (version.compiled_artifact_json or {}).get("categories", {}),
        }
    )
    return SortingProfileVersionResponse(**payload)


def _serialize_ai_message(message: SortingProfileAiMessage) -> SortingProfileAiMessageResponse:
    usage = message.usage_json if isinstance(message.usage_json, dict) else None
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
        profile=_serialize_profile_summary(db, assignment.profile, current_user, saved_profile_ids),
        desired_version=_serialize_version_summary(assignment.desired_version),
        active_version=_serialize_version_summary(assignment.active_version),
        artifact_hash=assignment.artifact_hash,
        last_error=assignment.last_error,
        last_synced_at=assignment.last_synced_at,
        last_activated_at=assignment.last_activated_at,
    )


def _find_rule(rules: list, rule_id: str | None):
    if not rule_id:
        return None
    for rule in rules:
        data = rule.model_dump() if hasattr(rule, "model_dump") else rule
        if data.get("id") == rule_id:
            return data
        found = _find_rule(data.get("children", []), rule_id)
        if found is not None:
            return found
    return None
