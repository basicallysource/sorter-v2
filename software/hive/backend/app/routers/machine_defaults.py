"""The defaults every sorter starts from (services/machine_defaults.py): what a
machine fetches, and an admin's overrides."""

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.deps import get_current_machine, get_db, require_role, verify_csrf
from app.errors import APIError
from app.models.machine import Machine
from app.models.user import User
from app.services import machine_defaults

router = APIRouter(prefix="/api", tags=["machine-defaults"])


@router.get("/machine/defaults")
def get_machine_defaults(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _machine: Machine = Depends(get_current_machine),
):
    """The block of defaults, with its version as the ETag: a machine that
    sends If-None-Match with the version it has gets a 304."""
    block = machine_defaults.current(db)
    etag = f'"{block["version"]}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    return block


@router.get("/admin/machine-defaults")
def get_admin_machine_defaults(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    """What every machine is served, Hive's own defaults and the overrides."""
    return machine_defaults.admin_view(db)


class MachineDefaultOverrideIn(BaseModel):
    path: str = Field(min_length=1, max_length=200)
    # None goes back to Hive's own default.
    value: Any = None


@router.put("/admin/machine-defaults")
def put_admin_machine_default(
    data: MachineDefaultOverrideIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
):
    """Override one default for every machine, or put Hive's own back.
    Machines fetch the new block after their next heartbeat."""
    try:
        return machine_defaults.set_override(db, data.path, data.value, admin.id)
    except machine_defaults.MachineDefaultsError as exc:
        raise APIError(400, str(exc), "INVALID_MACHINE_DEFAULT") from exc
