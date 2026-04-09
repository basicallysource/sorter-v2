from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.deps import get_current_machine, get_current_user, get_db, verify_csrf
from app.errors import APIError
from app.models.machine import Machine
from app.models.user import User
from app.schemas.machine import (
    MachineCreate,
    MachineHeartbeat,
    MachineRegister,
    MachineResponse,
    MachineUpdate,
    MachineWithTokenResponse,
)
from app.services.auth import generate_machine_token, verify_password
from app.services.machine_set_progress import build_set_progress_inventory_index, summarize_machine_set_progress
from app.services.storage import delete_machine_files

router = APIRouter(prefix="/api", tags=["machines"])
limiter = Limiter(key_func=get_remote_address)


class MachineSetProgressItemPayload(BaseModel):
    category_id: str | None = None
    set_num: str
    name: str | None = None
    part_num: str
    color_id: int | str
    quantity_needed: int = 0
    quantity_found: int = 0


class MachineSetProgressReportPayload(BaseModel):
    version_id: UUID
    artifact_hash: str = Field(min_length=1)
    items: list[MachineSetProgressItemPayload] = Field(default_factory=list)


@router.get("/machines", response_model=list[MachineResponse])
def list_machines(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    machines = db.query(Machine).filter(Machine.owner_id == current_user.id).all()
    return machines


@router.get("/machines/stats")
def get_machine_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Per-machine statistics for the dashboard cards."""
    from app.models.sample import Sample
    from app.models.upload_session import UploadSession
    from app.models.machine_set_progress import MachineSetProgress

    machine_ids = [
        mid for (mid,) in db.query(Machine.id).filter(Machine.owner_id == current_user.id).all()
    ]
    if not machine_ids:
        return {}

    # Sample counts per machine
    sample_rows = (
        db.query(
            Sample.machine_id,
            func.count(Sample.id).label("total_samples"),
            func.count(Sample.id).filter(Sample.review_status == "accepted").label("accepted_samples"),
            func.min(Sample.captured_at).label("first_capture"),
            func.max(Sample.captured_at).label("last_capture"),
        )
        .filter(Sample.machine_id.in_(machine_ids))
        .group_by(Sample.machine_id)
        .all()
    )
    sample_map = {str(r.machine_id): r for r in sample_rows}

    # Session counts per machine
    session_rows = (
        db.query(
            UploadSession.machine_id,
            func.count(UploadSession.id).label("total_sessions"),
        )
        .filter(UploadSession.machine_id.in_(machine_ids))
        .group_by(UploadSession.machine_id)
        .all()
    )
    session_map = {str(r.machine_id): r.total_sessions for r in session_rows}

    # Set progress aggregates per machine
    progress_rows = (
        db.query(
            MachineSetProgress.machine_id,
            func.sum(MachineSetProgress.quantity_found).label("parts_found"),
            func.sum(MachineSetProgress.quantity_needed).label("parts_needed"),
        )
        .filter(MachineSetProgress.machine_id.in_(machine_ids))
        .group_by(MachineSetProgress.machine_id)
        .all()
    )
    progress_map = {str(r.machine_id): r for r in progress_rows}

    result = {}
    for mid in machine_ids:
        mid_str = str(mid)
        sr = sample_map.get(mid_str)
        pr = progress_map.get(mid_str)
        result[mid_str] = {
            "total_samples": sr.total_samples if sr else 0,
            "accepted_samples": sr.accepted_samples if sr else 0,
            "first_capture": sr.first_capture.isoformat() if sr and sr.first_capture else None,
            "last_capture": sr.last_capture.isoformat() if sr and sr.last_capture else None,
            "total_sessions": session_map.get(mid_str, 0),
            "parts_found": int(pr.parts_found) if pr and pr.parts_found else 0,
            "parts_needed": int(pr.parts_needed) if pr and pr.parts_needed else 0,
        }

    return result


@router.post("/machines", response_model=MachineWithTokenResponse)
def create_machine(
    data: MachineCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    raw_token, token_hash, prefix = generate_machine_token()
    machine = Machine(
        owner_id=current_user.id,
        token_hash=token_hash,
        token_prefix=prefix,
        name=data.name,
        description=data.description,
    )
    db.add(machine)
    db.commit()
    db.refresh(machine)

    data_dict = MachineResponse.model_validate(machine).model_dump()
    data_dict["raw_token"] = raw_token
    return MachineWithTokenResponse(**data_dict)


@router.patch("/machines/{machine_id}", response_model=MachineResponse)
def update_machine(
    machine_id: UUID,
    data: MachineUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        raise APIError(404, "Machine not found", "MACHINE_NOT_FOUND")

    if data.name is not None:
        machine.name = data.name
    if data.description is not None:
        machine.description = data.description
    db.commit()
    db.refresh(machine)
    return machine


@router.delete("/machines/{machine_id}")
def delete_machine(
    machine_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        raise APIError(404, "Machine not found", "MACHINE_NOT_FOUND")

    delete_machine_files(str(machine.id))
    db.delete(machine)
    db.commit()
    return {"ok": True}


@router.post("/machines/{machine_id}/purge")
def purge_machine_data(
    machine_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    """Delete all upload sessions, samples, reviews, and files for a machine."""
    from app.models.sample import Sample
    from app.models.upload_session import UploadSession

    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        raise APIError(404, "Machine not found", "MACHINE_NOT_FOUND")

    sessions = db.query(UploadSession).filter(UploadSession.machine_id == machine.id).all()
    session_ids = [s.id for s in sessions]
    count = db.query(Sample).filter(Sample.upload_session_id.in_(session_ids)).count() if session_ids else 0
    for session in sessions:
        db.delete(session)  # cascades to samples and reviews

    delete_machine_files(str(machine.id))
    db.commit()

    return {"ok": True, "deleted_sessions": len(sessions), "deleted_samples": count}


@router.post("/machines/{machine_id}/rotate-token", response_model=MachineWithTokenResponse)
def rotate_token(
    machine_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        raise APIError(404, "Machine not found", "MACHINE_NOT_FOUND")

    raw_token, token_hash, prefix = generate_machine_token()
    machine.token_hash = token_hash
    machine.token_prefix = prefix
    db.commit()
    db.refresh(machine)

    data_dict = MachineResponse.model_validate(machine).model_dump()
    data_dict["raw_token"] = raw_token
    return MachineWithTokenResponse(**data_dict)


@router.post("/machine/heartbeat")
def heartbeat(
    request: Request,
    data: MachineHeartbeat | None = None,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    machine.last_seen_at = datetime.now(timezone.utc)
    # Capture the machine's IP from the request so we can link to its local UI
    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else None)
    if client_ip:
        machine.last_seen_ip = client_ip
    if data is not None:
        if "hardware_info" in data.model_fields_set:
            machine.hardware_info = data.hardware_info
        local_ui_port = data.local_ui_port if "local_ui_port" in data.model_fields_set else None
        if local_ui_port is None and isinstance(data.hardware_info, dict) and "hardware_info" in data.model_fields_set:
            raw_port = data.hardware_info.get("local_ui_port")
            if isinstance(raw_port, (str, int)) and not isinstance(raw_port, bool):
                local_ui_port = str(raw_port)
        if local_ui_port is not None:
            normalized_port = local_ui_port.strip()
            machine.local_ui_port = normalized_port or None
    db.commit()
    return {"ok": True, "machine_id": str(machine.id)}


@router.post("/machine/register", response_model=MachineWithTokenResponse)
@limiter.limit("5/minute")
def register_machine(
    request: Request,
    data: MachineRegister,
    db: Session = Depends(get_db),
):
    """Self-registration endpoint for machines.

    Authenticates with user credentials and creates a new machine,
    returning the API token in one step. No cookies/CSRF needed.
    """
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise APIError(401, "Invalid email or password", "INVALID_CREDENTIALS")
    if not user.is_active:
        raise APIError(403, "Account is inactive", "ACCOUNT_INACTIVE")

    raw_token, token_hash, prefix = generate_machine_token()
    machine = Machine(
        owner_id=user.id,
        token_hash=token_hash,
        token_prefix=prefix,
        name=data.machine_name,
        description=data.machine_description,
    )
    db.add(machine)
    db.commit()
    db.refresh(machine)

    data_dict = MachineResponse.model_validate(machine).model_dump()
    data_dict["raw_token"] = raw_token
    return MachineWithTokenResponse(**data_dict)


@router.get("/machines/{machine_id}/set-progress")
def get_machine_set_progress(
    machine_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get set-based sorting progress for a machine."""
    from app.models.machine_set_progress import MachineSetProgress
    from app.models.machine_profile_assignment import MachineProfileAssignment

    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        raise APIError(404, "Machine not found", "MACHINE_NOT_FOUND")

    assignment = db.query(MachineProfileAssignment).filter(
        MachineProfileAssignment.machine_id == machine_id
    ).first()
    if not assignment:
        return {"progress": [], "assignment_id": None}

    version = assignment.active_version or assignment.desired_version
    rows = db.query(MachineSetProgress).filter(
        MachineSetProgress.assignment_id == assignment.id
    ).all()

    summary = summarize_machine_set_progress(
        version.compiled_artifact_json if version is not None else {},
        rows,
    )
    progress = [
        {
            "set_num": item["set_num"],
            "set_name": item["set_name"],
            "part_num": item["part_num"],
            "color_id": item["color_id"],
            "quantity_needed": item["quantity_needed"],
            "quantity_found": item["quantity_found"],
            "updated_at": item["updated_at"].isoformat() if item["updated_at"] else None,
        }
        for item in summary["progress"]
    ]

    return {"progress": progress, "assignment_id": str(assignment.id)}


@router.post("/machine/set-progress")
def report_machine_set_progress(
    payload: MachineSetProgressReportPayload,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    """Machine reports its set progress snapshot. Authenticated via machine token."""
    from app.models.machine_set_progress import MachineSetProgress
    from app.models.machine_profile_assignment import MachineProfileAssignment

    assignment = db.query(MachineProfileAssignment).filter(
        MachineProfileAssignment.machine_id == machine.id
    ).first()
    if not assignment:
        raise APIError(404, "No profile assignment found", "NO_ASSIGNMENT")

    expected_version = assignment.active_version or assignment.desired_version
    expected_version_id = expected_version.id if expected_version is not None else None
    if expected_version_id is None:
        raise APIError(409, "Machine assignment has no active profile version", "SET_PROGRESS_VERSION_UNAVAILABLE")
    if payload.version_id != expected_version_id:
        raise APIError(409, "Reported progress does not match the active assignment version", "SET_PROGRESS_VERSION_MISMATCH")

    expected_artifact_hash = str(assignment.artifact_hash or getattr(expected_version, "compiled_hash", "") or "")
    if not expected_artifact_hash:
        raise APIError(409, "Machine assignment has no compiled artifact hash", "SET_PROGRESS_ARTIFACT_UNAVAILABLE")
    if payload.artifact_hash != expected_artifact_hash:
        raise APIError(409, "Reported progress does not match the active assignment artifact", "SET_PROGRESS_ARTIFACT_MISMATCH")

    compiled_artifact = expected_version.compiled_artifact_json if expected_version is not None else {}
    valid_progress_items = build_set_progress_inventory_index(compiled_artifact)
    expected_keys = set(valid_progress_items.keys())
    if not valid_progress_items and payload.items:
        raise APIError(400, "Non-set profiles must report an empty progress snapshot", "SET_PROGRESS_NOT_SET_BASED")

    now = datetime.now(timezone.utc)
    normalized_by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
    for item in payload.items:
        try:
            color_id = int(item.color_id)
        except (TypeError, ValueError):
            raise APIError(400, f"Invalid color_id '{item.color_id}'", "SET_PROGRESS_COLOR_INVALID")

        set_num = item.set_num.strip()
        part_num = item.part_num.strip()
        if not set_num or not part_num:
            raise APIError(400, "set_num and part_num are required", "SET_PROGRESS_ITEM_INVALID")

        key = (set_num, part_num, color_id)
        expected_item = valid_progress_items.get(key)
        if expected_item is None:
            raise APIError(
                400,
                f"Progress item {set_num}/{part_num}/{color_id} is not part of the assigned artifact",
                "SET_PROGRESS_ITEM_UNKNOWN",
            )

        try:
            quantity_found = max(0, int(item.quantity_found))
        except (TypeError, ValueError):
            raise APIError(400, f"Invalid quantity_found '{item.quantity_found}'", "SET_PROGRESS_QUANTITY_INVALID")

        normalized = normalized_by_key.setdefault(
            key,
            {
                "set_num": set_num,
                "part_num": part_num,
                "color_id": color_id,
                "quantity_needed": int(expected_item["quantity_needed"]),
                "quantity_found": 0,
            },
        )
        normalized["quantity_found"] = min(
            normalized["quantity_needed"],
            normalized["quantity_found"] + quantity_found,
        )

    incoming_keys = set(normalized_by_key.keys())
    if expected_keys != incoming_keys:
        missing_count = len(expected_keys - incoming_keys)
        extra_count = len(incoming_keys - expected_keys)
        raise APIError(
            400,
            f"Progress snapshot is incomplete for the assigned artifact (missing={missing_count}, extra={extra_count})",
            "SET_PROGRESS_SNAPSHOT_INCOMPLETE",
        )

    normalized_items = list(normalized_by_key.values())

    existing_rows = db.query(MachineSetProgress).filter(
        MachineSetProgress.assignment_id == assignment.id
    ).all()
    existing_by_key = {
        (row.set_num, row.part_num, row.color_id): row
        for row in existing_rows
    }

    deleted = 0
    for key, row in existing_by_key.items():
        if key not in incoming_keys:
            db.delete(row)
            deleted += 1

    for item in normalized_items:
        key = (item["set_num"], item["part_num"], item["color_id"])
        existing = existing_by_key.get(key)
        if existing is not None:
            existing.quantity_found = item["quantity_found"]
            existing.quantity_needed = item["quantity_needed"]
            existing.updated_at = now
            continue

        db.add(
            MachineSetProgress(
                machine_id=machine.id,
                assignment_id=assignment.id,
                set_num=item["set_num"],
                part_num=item["part_num"],
                color_id=item["color_id"],
                quantity_needed=item["quantity_needed"],
                quantity_found=item["quantity_found"],
                updated_at=now,
            )
        )

    db.commit()
    return {"ok": True, "updated": len(normalized_items), "deleted": deleted}
