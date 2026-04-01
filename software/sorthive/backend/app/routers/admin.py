from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_db, require_role, verify_csrf
from app.errors import APIError
from app.models.user import User
from app.schemas.auth import AdminUpdateUserRequest, UserResponse
from app.services.storage import delete_machine_files

router = APIRouter(prefix="/api/admin", tags=["admin"])


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
