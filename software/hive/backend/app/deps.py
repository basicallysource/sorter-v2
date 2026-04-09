import hashlib
from uuid import UUID
from typing import Generator

from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.machine import Machine
from app.models.user import User
from app.services.auth import decode_access_token


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(default=None),
) -> User:
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_access_token(access_token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    try:
        user_id = UUID(str(payload["sub"]))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token subject") from None
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def get_current_machine(
    db: Session = Depends(get_db),
    authorization: str = Header(...),
) -> Machine:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    raw_token = authorization[7:]
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    machine = db.query(Machine).filter(Machine.token_hash == token_hash, Machine.is_active.is_(True)).first()
    if machine is None:
        raise HTTPException(status_code=401, detail="Invalid machine token")
    return machine


def require_role(*roles: str):
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return dependency


def verify_csrf(
    request: Request,
    x_csrf_token: str | None = Header(default=None),
    csrf_token: str | None = Cookie(default=None),
) -> None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if not x_csrf_token or not csrf_token:
        raise HTTPException(status_code=403, detail="CSRF token missing")
    if x_csrf_token != csrf_token:
        raise HTTPException(status_code=403, detail="CSRF token mismatch")
