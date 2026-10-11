from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.deps import (
    API_KEY_SCOPE_SERVER_HEALTH_READ,
    get_db,
    require_api_key_scopes,
    require_role,
    require_role_flex,
    verify_csrf,
)
from app.errors import APIError
from app.models.user import User
from app.schemas.auth import AdminUpdateUserRequest, UserResponse
from app.services import access_window, telemetry_limits
from app.services.server_health import get_server_health, get_storage_stats_worker
from app.services.storage import delete_machine_files

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/server-health")
def server_health(
    refresh_storage: bool = Query(False),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role_flex("admin")),
    _scope_guard: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SERVER_HEALTH_READ)),
):
    """Storage usage (sample vs piece images vs models), DB size, and memory.

    Storage figures come from a cache a background worker walks on a slow
    cadence — reading them is instant. refresh_storage=true just nudges that
    worker to walk again soon and returns the current cache immediately (the
    walk itself is far too slow to run inside the request).

    The only admin route reachable by API key, so that monitoring can watch the
    box over days without a human holding a browser session open. Still
    admin-only: `require_role_flex` authenticates a key, `require_api_key_scopes`
    is what actually authorizes it, and a key needs both the role and
    `server_health:read`."""
    if refresh_storage:
        get_storage_stats_worker().wake()
    return get_server_health(db)


@router.get("/users", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    return db.query(User).order_by(User.created_at.desc()).all()


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: UUID,
    data: AdminUpdateUserRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise APIError(404, "User not found", "USER_NOT_FOUND")

    if data.role is not None:
        if data.role not in ("member", "reviewer", "admin"):
            raise APIError(400, "Invalid role", "INVALID_ROLE")
        # Prevent removing own admin role
        if user.id == admin.id and data.role != "admin":
            raise APIError(400, "Cannot remove your own admin role", "CANNOT_DEMOTE_SELF")
        user.role = data.role

    if data.is_active is not None:
        if user.id == admin.id and not data.is_active:
            raise APIError(400, "Cannot deactivate your own account", "CANNOT_DEACTIVATE_SELF")
        user.is_active = data.is_active

    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}")
def delete_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise APIError(404, "User not found", "USER_NOT_FOUND")
    if user.id == admin.id:
        raise APIError(400, "Cannot delete your own account via admin panel", "CANNOT_DELETE_SELF")

    for machine in user.machines:
        delete_machine_files(str(machine.id))

    db.delete(user)
    db.commit()
    return {"ok": True}


class AccessWindowUpdate(BaseModel):
    anchor: str
    size: int = Field(ge=0)
    offset: int = Field(ge=0)


@router.get("/access-windows")
def get_access_windows(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    """Effective piece-bbox visibility windows per (role, entity), with whether
    each value is a live override or the code default. Admins are unrestricted."""
    return access_window.list_effective_windows(db)


@router.put("/access-windows/{role}/{entity}")
def put_access_window(
    role: str,
    entity: str,
    data: AccessWindowUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
):
    """Set (upsert) the visibility window for a windowed role + entity. 'admin' is
    unrestricted and cannot be given a window."""
    if role not in access_window.WINDOWED_ROLES:
        raise APIError(400, f"Role must be one of {access_window.WINDOWED_ROLES}", "INVALID_ROLE")
    if entity not in access_window.ENTITIES:
        raise APIError(400, f"Entity must be one of {access_window.ENTITIES}", "INVALID_ENTITY")
    if data.anchor not in access_window.ANCHORS:
        raise APIError(400, f"Anchor must be one of {access_window.ANCHORS}", "INVALID_ANCHOR")

    access_window.set_window(db, role, entity, data.anchor, data.size, data.offset)
    return access_window.list_effective_windows(db)


class TelemetryLimitsUpdate(BaseModel):
    """A partial update: fields left out keep their current value."""

    model_config = {"extra": "forbid"}

    sample_burst_interval_s: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    sample_floor_interval_s: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    sample_ramp_hours: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    sample_store_max_bytes: int | None = Field(default=None, gt=0)
    upload_bytes_per_minute: int | None = Field(default=None, gt=0)
    upload_files_per_minute: int | None = Field(default=None, gt=0)


@router.get("/telemetry-limits")
def get_telemetry_limits(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    """The limits every machine gets on its heartbeat: how fast it may capture
    training samples, how big its local sample store may grow, and its upload
    budget. ``updated_at`` is null while the built-in defaults apply."""
    return telemetry_limits.global_limits(db)


@router.put("/telemetry-limits")
def put_telemetry_limits(
    data: TelemetryLimitsUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
):
    """Change some of the limits. Machines pick the new values up on their next
    heartbeat."""
    try:
        return telemetry_limits.update_global_limits(db, data.model_dump(exclude_none=True))
    except telemetry_limits.TelemetryLimitsError as exc:
        raise APIError(400, str(exc), "INVALID_TELEMETRY_LIMITS") from exc
