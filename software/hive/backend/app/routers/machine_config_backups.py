from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_current_machine, get_current_user, get_db
from app.models.machine import Machine
from app.models.machine_config_backup import MachineConfigBackup
from app.models.user import User
from app.schemas.machine_config_backup import (
    ConfigBackupDetail,
    ConfigBackupSummary,
    ConfigBackupUpload,
    ConfigBackupUploadResponse,
)

router = APIRouter()


def _latest_backup(db: Session, machine_id) -> MachineConfigBackup | None:
    return (
        db.query(MachineConfigBackup)
        .filter(MachineConfigBackup.machine_id == machine_id)
        .order_by(MachineConfigBackup.version.desc())
        .first()
    )


# --- Machine-facing (Bearer token) ----------------------------------------


@router.post("/api/machine/config-backup", response_model=ConfigBackupUploadResponse)
def upload_config_backup(
    data: ConfigBackupUpload,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    """Store a settings snapshot. Hash-deduped: an unchanged config returns the
    existing latest version without creating a new row."""
    latest = _latest_backup(db, machine.id)
    if latest is not None and latest.content_hash == data.content_hash:
        return ConfigBackupUploadResponse(
            version=latest.version,
            content_hash=latest.content_hash,
            deduped=True,
            created_at=latest.created_at,
        )

    backup = MachineConfigBackup(
        machine_id=machine.id,
        version=(latest.version + 1) if latest is not None else 1,
        content_hash=data.content_hash,
        payload=data.payload,
        trigger=data.trigger or "config_change",
    )
    db.add(backup)
    db.commit()
    db.refresh(backup)
    return ConfigBackupUploadResponse(
        version=backup.version,
        content_hash=backup.content_hash,
        deduped=False,
        created_at=backup.created_at,
    )


@router.get("/api/machine/config-backups", response_model=list[ConfigBackupSummary])
def list_own_config_backups(
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    """A machine lists its own backup versions (newest first) — used by the
    sorter UI to offer a restore picker."""
    return (
        db.query(MachineConfigBackup)
        .filter(MachineConfigBackup.machine_id == machine.id)
        .order_by(MachineConfigBackup.version.desc())
        .all()
    )


@router.get("/api/machine/config-backup/{version}", response_model=ConfigBackupDetail)
def get_own_config_backup(
    version: int,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    """A machine pulls one of its own versions verbatim to restore it."""
    backup = (
        db.query(MachineConfigBackup)
        .filter(
            MachineConfigBackup.machine_id == machine.id,
            MachineConfigBackup.version == version,
        )
        .first()
    )
    if backup is None:
        raise HTTPException(status_code=404, detail="No such config backup version.")
    return backup


# --- User-facing (cookie, owner-scoped) ------------------------------------


def _owned_machine(db: Session, machine_id: UUID, user: User) -> Machine:
    machine = (
        db.query(Machine)
        .filter(Machine.id == machine_id, Machine.owner_id == user.id)
        .first()
    )
    if machine is None:
        raise HTTPException(status_code=404, detail="Machine not found.")
    return machine


@router.get(
    "/api/machines/{machine_id}/config-backups",
    response_model=list[ConfigBackupSummary],
)
def list_machine_config_backups(
    machine_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_machine(db, machine_id, current_user)
    return (
        db.query(MachineConfigBackup)
        .filter(MachineConfigBackup.machine_id == machine_id)
        .order_by(MachineConfigBackup.version.desc())
        .all()
    )


@router.get(
    "/api/machines/{machine_id}/config-backups/{version}",
    response_model=ConfigBackupDetail,
)
def get_machine_config_backup(
    machine_id: UUID,
    version: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_machine(db, machine_id, current_user)
    backup = (
        db.query(MachineConfigBackup)
        .filter(
            MachineConfigBackup.machine_id == machine_id,
            MachineConfigBackup.version == version,
        )
        .first()
    )
    if backup is None:
        raise HTTPException(status_code=404, detail="No such config backup version.")
    return backup
