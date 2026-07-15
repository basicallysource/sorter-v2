from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.deps import get_db, require_role, verify_csrf
from app.errors import APIError
from app.models.user import User
from app.schemas.auth import AdminUpdateUserRequest, UserResponse
from app.services import access_window
from app.services.server_health import get_server_health
from app.services.storage import delete_machine_files

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/server-health")
def server_health(
    refresh_storage: bool = Query(False),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    """Storage usage (sample vs piece images vs models), DB size, and memory.

    Storage figures are cached for a few minutes since they require walking the
    whole object store; pass refresh_storage=true to force a fresh walk."""
    return get_server_health(db, refresh_storage=refresh_storage)


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
