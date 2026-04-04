from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.deps import get_current_machine, get_current_user, get_db, verify_csrf
from app.errors import APIError
from app.models.machine import Machine
from app.models.user import User
from app.schemas.machine import MachineCreate, MachineRegister, MachineResponse, MachineUpdate, MachineWithTokenResponse
from app.services.auth import generate_machine_token, verify_password
from app.services.storage import delete_machine_files

router = APIRouter(prefix="/api", tags=["machines"])
limiter = Limiter(key_func=get_remote_address)


@router.get("/machines", response_model=list[MachineResponse])
def list_machines(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    machines = db.query(Machine).filter(Machine.owner_id == current_user.id).all()
    return machines


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
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    machine.last_seen_at = datetime.now(timezone.utc)
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

    rows = db.query(MachineSetProgress).filter(
        MachineSetProgress.assignment_id == assignment.id
    ).all()

    progress = []
    for row in rows:
        progress.append({
            "set_num": row.set_num,
            "part_num": row.part_num,
            "color_id": row.color_id,
            "quantity_needed": row.quantity_needed,
            "quantity_found": row.quantity_found,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        })

    return {"progress": progress, "assignment_id": str(assignment.id)}


@router.post("/machine/set-progress")
def report_machine_set_progress(
    payload: dict,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    """Machine reports its set progress snapshot. Authenticated via machine token."""
    from app.models.machine_set_progress import MachineSetProgress
    from app.models.machine_profile_assignment import MachineProfileAssignment
    from datetime import datetime, timezone

    assignment = db.query(MachineProfileAssignment).filter(
        MachineProfileAssignment.machine_id == machine.id
    ).first()
    if not assignment:
        raise APIError(404, "No profile assignment found", "NO_ASSIGNMENT")

    items = payload.get("items", [])
    for item in items:
        existing = db.query(MachineSetProgress).filter(
            MachineSetProgress.assignment_id == assignment.id,
            MachineSetProgress.set_num == item["set_num"],
            MachineSetProgress.part_num == item["part_num"],
            MachineSetProgress.color_id == item["color_id"],
        ).first()

        if existing:
            existing.quantity_found = item.get("quantity_found", 0)
            existing.quantity_needed = item.get("quantity_needed", existing.quantity_needed)
            existing.updated_at = datetime.now(timezone.utc)
        else:
            row = MachineSetProgress(
                machine_id=machine.id,
                assignment_id=assignment.id,
                set_num=item["set_num"],
                part_num=item["part_num"],
                color_id=item["color_id"],
                quantity_needed=item.get("quantity_needed", 1),
                quantity_found=item.get("quantity_found", 0),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(row)

    db.commit()
    return {"ok": True, "updated": len(items)}
