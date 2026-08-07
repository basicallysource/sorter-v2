from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.deps import get_current_machine, get_current_user, get_db, require_role, verify_csrf
from app.errors import APIError
from app.models.machine import Machine
from app.models.machine_piece import MachinePiece
from app.models.machine_piece_image import MachinePieceImage
from app.models.machine_channel_crop import MachineChannelCrop
from app.models.user import User
from app.schemas.machine import (
    MachineCreate,
    MachineHeartbeat,
    MachineRegister,
    MachineResponse,
    MachineUpdate,
    MachineWithTokenResponse,
)
from app.services import machine_stats
from app.services.auth import generate_machine_token, verify_password
from app.services.machine_set_progress import build_set_progress_inventory_index, summarize_machine_set_progress
from app.services.machine_stats import get_machine_stats_worker
from app.services.storage import delete_machine_files, serve_stored_file

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
    scope: str | None = Query(None, pattern="^(mine|all)$"),
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Machine).options(joinedload(Machine.owner))
    if scope != "all":
        query = query.filter(Machine.owner_id == current_user.id)
    if not include_archived:
        query = query.filter(Machine.archived_at.is_(None))
    return query.all()


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


@router.get("/admin/machines")
def admin_list_machines(
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    """Every machine across ALL owners (admin-only fleet view)."""
    machines = db.query(Machine).options(joinedload(Machine.owner)).order_by(Machine.created_at).all()
    return [
        {
            "id": str(m.id),
            "name": m.name,
            "description": m.description,
            "owner_id": str(m.owner_id),
            "owner_email": m.owner.email if m.owner else None,
            "owner_display_name": m.owner.display_name if m.owner else None,
            "is_active": m.is_active,
            "archived_at": m.archived_at.isoformat() if m.archived_at else None,
            "last_seen_at": m.last_seen_at.isoformat() if m.last_seen_at else None,
            "last_seen_ip": m.last_seen_ip,
            "local_ui_port": m.local_ui_port,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in machines
    ]


@router.get("/admin/machines/stats")
def admin_machine_stats(
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    """Per-machine lifetime metrics (pieces, PPM, on-time %) across ALL machines.

    Served from the machine_stats_cache table, refreshed hourly by the
    MachineStatsWorker (see app.services.machine_stats). Cold-start fallback:
    if the cache has never been populated, compute it once here so the first
    admin load isn't blank.
    """
    from app.models.machine_stats_cache import MachineStatsCache

    if db.query(MachineStatsCache.machine_id).first() is None:
        try:
            machine_stats.refresh_cache(db)
        except Exception:
            # A concurrent refresh (e.g. the boot-time worker pass) may have
            # populated the cache between the check and here — just serve
            # whatever is there rather than 500 on the insert race.
            db.rollback()
    return machine_stats.get_fleet_stats(db)


@router.post("/admin/machines/stats/refresh")
def admin_refresh_machine_stats(
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
):
    """Force an immediate recompute of every machine's cached stats."""
    count = machine_stats.refresh_cache(db)
    return {"ok": True, "refreshed": count, "worker": get_machine_stats_worker().status()}


def _machine_for_viewer(db: Session, machine_id: UUID, user: User) -> Machine:
    """Fetch a machine the given user may view (its owner, or any admin).

    Non-owners without the admin role get a 404 rather than a 403 so the
    endpoint doesn't confirm the existence of other users' machines.
    """
    machine = db.query(Machine).options(joinedload(Machine.owner)).filter(Machine.id == machine_id).first()
    if machine is None or (str(machine.owner_id) != str(user.id) and user.role != "admin"):
        raise APIError(404, "Machine not found", "MACHINE_NOT_FOUND")
    return machine


@router.get("/machines/{machine_id}/overview")
def get_machine_overview(
    machine_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dashboard overview for a single machine — metadata + cached stats.

    Accessible to the machine's owner or any admin. Stats come from the
    machine_stats_cache (lazily computed on a miss)."""
    machine = _machine_for_viewer(db, machine_id, current_user)
    stats = machine_stats.get_machine_stats(db, machine.id)
    is_owner = str(machine.owner_id) == str(current_user.id)
    return {
        "machine": {
            "id": str(machine.id),
            "name": machine.name,
            "description": machine.description,
            "is_active": machine.is_active,
            "archived_at": machine.archived_at.isoformat() if machine.archived_at else None,
            "last_seen_at": machine.last_seen_at.isoformat() if machine.last_seen_at else None,
            "last_seen_ip": machine.last_seen_ip,
            "local_ui_port": machine.local_ui_port,
            "created_at": machine.created_at.isoformat() if machine.created_at else None,
            "token_prefix": machine.token_prefix,
            "hardware_info": machine.hardware_info,
            "owner": {
                "display_name": machine.owner.display_name if machine.owner else None,
                "email": machine.owner.email if machine.owner else None,
            },
        },
        "stats": stats,
        "is_owner": is_owner,
        "viewer_is_admin": current_user.role == "admin",
    }


PIECE_IMAGE_CACHE_CONTROL = "public, max-age=31536000, immutable"


def _serialize_machine_piece(piece: MachinePiece, images: list[MachinePieceImage]) -> dict[str, Any]:
    return {
        "piece_uuid": piece.piece_uuid,
        "local_id": piece.local_id,
        "run_id": piece.run_id,
        "seen_at": piece.seen_at.isoformat() if piece.seen_at else None,
        "recorded_at": piece.recorded_at.isoformat() if piece.recorded_at else None,
        "classification_status": piece.classification_status,
        "part_id": piece.part_id,
        "part_name": piece.part_name,
        "color_id": piece.color_id,
        "color_name": piece.color_name,
        "category_id": piece.category_id,
        "confidence": piece.confidence,
        "color_confidence": piece.color_confidence,
        "bin": {"x": piece.bin_x, "y": piece.bin_y, "z": piece.bin_z},
        "dead": piece.dead,
        "brickognize_preview_url": piece.brickognize_preview_url,
        "images": [
            {
                "seq": im.seq,
                "source": im.source,
                "channel": im.channel,
                "sharpness": im.sharpness,
                "bytes": im.bytes,
                "used": im.used,
                "excluded_from_result": im.excluded_from_result,
                "score": im.score,
                # image_key is NULL once the crop was evicted from the machine's
                # local store before syncing — the row rides up regardless, so
                # the UI still knows the piece had N crops but can't show them.
                "available": im.image_key is not None,
                "evicted_locally": im.evicted_locally,
            }
            for im in images
        ],
    }


@router.get("/machines/{machine_id}/pieces")
def list_machine_pieces(
    machine_id: UUID,
    limit: int = Query(60, ge=1, le=200),
    cursor: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every synced piece for one machine, newest first — the fleet analogue of
    the on-machine /records page. Keyset-paginated on the machine's local_id.

    Accessible to the machine's owner or any admin."""
    machine = _machine_for_viewer(db, machine_id, current_user)

    query = db.query(MachinePiece).filter(MachinePiece.machine_id == machine_id)
    if cursor is not None:
        query = query.filter(MachinePiece.local_id < cursor)
    pieces = query.order_by(MachinePiece.local_id.desc()).limit(limit + 1).all()

    has_more = len(pieces) > limit
    pieces = pieces[:limit]
    next_cursor = pieces[-1].local_id if (has_more and pieces) else None

    images_by_piece: dict[str, list[MachinePieceImage]] = {}
    piece_uuids = [p.piece_uuid for p in pieces]
    if piece_uuids:
        images = (
            db.query(MachinePieceImage)
            .filter(
                MachinePieceImage.machine_id == machine_id,
                MachinePieceImage.piece_uuid.in_(piece_uuids),
            )
            .order_by(MachinePieceImage.seq.asc())
            .all()
        )
        for im in images:
            images_by_piece.setdefault(im.piece_uuid, []).append(im)

    total = (
        db.query(func.count(MachinePiece.id))
        .filter(MachinePiece.machine_id == machine_id)
        .scalar()
        or 0
    )

    return {
        "machine": {
            "id": str(machine.id),
            "name": machine.name,
            "owner_email": machine.owner.email if machine.owner else None,
        },
        "items": [
            _serialize_machine_piece(p, images_by_piece.get(p.piece_uuid, []))
            for p in pieces
        ],
        "next_cursor": next_cursor,
        "total": total,
    }


@router.get("/machines/{machine_id}/pieces/{piece_uuid}/images/{seq}")
def get_machine_piece_image(
    machine_id: UUID,
    piece_uuid: str,
    seq: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stream one synced crop's bytes from object storage. Cookie-session auth
    (owner or admin) is enough for an <img> tag on a same-origin page."""
    _machine_for_viewer(db, machine_id, current_user)
    image = (
        db.query(MachinePieceImage)
        .filter(
            MachinePieceImage.machine_id == machine_id,
            MachinePieceImage.piece_uuid == piece_uuid,
            MachinePieceImage.seq == seq,
        )
        .first()
    )
    if image is None or not image.image_key:
        raise APIError(404, "Image not found", "IMAGE_NOT_FOUND")

    return serve_stored_file(image.image_key, headers={"Cache-Control": PIECE_IMAGE_CACHE_CONTROL})


def _serialize_channel_crop(crop: MachineChannelCrop) -> dict[str, Any]:
    return {
        "local_id": crop.local_id,
        "channel": crop.channel,
        "ts": crop.ts.isoformat() if crop.ts else None,
        "captured_at": crop.captured_at.isoformat() if crop.captured_at else None,
        "track_id": crop.track_id,
        "com_forward_to_exit_deg": crop.com_forward_to_exit_deg,
        "com_section": crop.com_section,
        "zone_code": crop.zone_code,
        "sharpness": crop.sharpness,
        "bbox": [crop.bbox_x1, crop.bbox_y1, crop.bbox_x2, crop.bbox_y2],
        "bytes": crop.bytes,
        # image_key is NULL once the crop was evicted from the machine's local
        # store before syncing — the row rides up regardless.
        "available": crop.image_key is not None,
        "evicted_locally": crop.evicted_locally,
    }


@router.get("/machines/{machine_id}/channel-crops")
def list_machine_channel_crops(
    machine_id: UUID,
    limit: int = Query(120, ge=1, le=500),
    cursor: int | None = Query(None),
    channel: int | None = Query(None),
    zone_code: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Unlabeled C2/C3 bbox crops synced from one machine, newest first.
    Keyset-paginated on the machine's local crop id. Optional channel / zone_code
    filters. Accessible to the machine's owner or any admin."""
    machine = _machine_for_viewer(db, machine_id, current_user)

    query = db.query(MachineChannelCrop).filter(MachineChannelCrop.machine_id == machine_id)
    if channel is not None:
        query = query.filter(MachineChannelCrop.channel == channel)
    if zone_code is not None:
        query = query.filter(MachineChannelCrop.zone_code == zone_code)
    if cursor is not None:
        query = query.filter(MachineChannelCrop.local_id < cursor)
    crops = query.order_by(MachineChannelCrop.local_id.desc()).limit(limit + 1).all()

    has_more = len(crops) > limit
    crops = crops[:limit]
    next_cursor = crops[-1].local_id if (has_more and crops) else None

    total = (
        db.query(func.count(MachineChannelCrop.id))
        .filter(MachineChannelCrop.machine_id == machine_id)
        .scalar()
        or 0
    )

    return {
        "machine": {
            "id": str(machine.id),
            "name": machine.name,
            "owner_email": machine.owner.email if machine.owner else None,
        },
        "items": [_serialize_channel_crop(c) for c in crops],
        "next_cursor": next_cursor,
        "total": total,
    }


@router.get("/machines/{machine_id}/channel-crops/{local_id}/image")
def get_machine_channel_crop_image(
    machine_id: UUID,
    local_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stream one synced channel crop's bytes. Cookie-session auth (owner or
    admin) is enough for an <img> tag on a same-origin page."""
    _machine_for_viewer(db, machine_id, current_user)
    crop = (
        db.query(MachineChannelCrop)
        .filter(
            MachineChannelCrop.machine_id == machine_id,
            MachineChannelCrop.local_id == local_id,
        )
        .first()
    )
    if crop is None or not crop.image_key:
        raise APIError(404, "Image not found", "IMAGE_NOT_FOUND")

    return serve_stored_file(crop.image_key, headers={"Cache-Control": PIECE_IMAGE_CACHE_CONTROL})


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
            if isinstance(data.hardware_info, dict) and data.hardware_info.get("schema_version") is not None:
                # A machine-specs snapshot: summarize for the dashboard + append
                # the full snapshot to the spec history.
                from app.machine_hardware import record_hardware_report

                record_hardware_report(db, machine, data.hardware_info)
            else:
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

@router.post("/machines/{machine_id}/archive", response_model=MachineResponse)
def archive_machine(
    machine_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
):
    """Hide a machine + its samples from default listings/stats/training pulls.

    Reversible via the matching DELETE endpoint. Sample rows stay intact; the
    archive flag just filters them out wherever the UI/training treat the
    sample roster as 'active fleet'.
    """
    machine = db.query(Machine).filter(Machine.id == machine_id).first()
    if not machine:
        raise APIError(404, "Machine not found", "MACHINE_NOT_FOUND")
    if machine.archived_at is None:
        machine.archived_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(machine)
    return machine


@router.delete("/machines/{machine_id}/archive", response_model=MachineResponse)
def unarchive_machine(
    machine_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
):
    machine = db.query(Machine).filter(Machine.id == machine_id).first()
    if not machine:
        raise APIError(404, "Machine not found", "MACHINE_NOT_FOUND")
    if machine.archived_at is not None:
        machine.archived_at = None
        db.commit()
        db.refresh(machine)
    return machine

