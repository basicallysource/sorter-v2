"""Silent device enrollment for the hosted-services layer.

`POST /api/devices/enroll` — a sorter's one-time (per install) self-enrollment
so it can call hosted services (color prediction) on the main hive without any
account existing. No user auth: the whole point is that these services work
before, or without, registration. The sorter sends a self-generated opaque
device_key and gets back a device id + bearer token; re-enrolling with the same
key (lost token) rotates the token but keeps the same device row, so logged
data stays under one identity.

Rate limited per source IP. Device rows are admin-only — never shown to
regular users, never implied to an operator as "already registered".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models.device import Device
from app.services.auth import generate_machine_token

router = APIRouter(prefix="/api/devices", tags=["devices"])
limiter = Limiter(key_func=get_remote_address)


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else None


class DeviceEnroll(BaseModel):
    device_key: str = Field(min_length=16, max_length=128)
    hardware_info: dict[str, Any] | None = None


@router.post("/enroll")
@limiter.limit("5/minute")
def enroll_device(data: DeviceEnroll, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    raw_token, token_hash, prefix = generate_machine_token()

    device = db.query(Device).filter(Device.device_key == data.device_key).first()
    if device is None:
        device = Device(
            device_key=data.device_key,
            token_hash=token_hash,
            token_prefix=prefix,
        )
        db.add(device)
    else:
        # Same key, new token: the sorter lost its token but kept its key.
        # Rotating (instead of refusing) keeps re-enroll self-service; the key
        # never travels anywhere except this endpoint.
        device.token_hash = token_hash
        device.token_prefix = prefix
        device.is_active = True
    if data.hardware_info is not None:
        device.hardware_info = data.hardware_info
    device.last_seen_ip = _client_ip(request)
    device.last_seen_at = now
    db.commit()
    db.refresh(device)
    return {"device_id": str(device.id), "token": raw_token}
