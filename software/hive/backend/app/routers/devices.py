"""The unregistered tier of machine identity: device enrollment + status ping.

`POST /api/devices/enroll` — a sorter's one-time (per install) self-enrollment
so it can call hosted services (status ping, color prediction) on the main hive
without any account existing. No user auth: the whole point is that these
services work before, or without, registration. The sorter sends a
self-generated opaque device_key and gets back a device id + bearer token;
re-enrolling with the same key (lost token) rotates the token but keeps the
same device row, so logged data stays under one identity.

`POST /api/devices/ping` — the machine's hourly status report (device auth),
successor to the anonymous /api/installs/ping. Updates the device's telemetry
columns; the first ping carrying an install_id absorbs the matching legacy
installs row (history folded in, row deleted). install_id remains the
operator-facing handle for the public /forget flow.

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

from app.deps import get_current_device, get_db
from app.models.device import Device
from app.models.install import Install
from app.services.auth import generate_machine_token

router = APIRouter(prefix="/api/devices", tags=["devices"])
limiter = Limiter(key_func=get_remote_address)

_MAX_STR = 512


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else None


def _clip(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:_MAX_STR] if text else None


def _as_int(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _as_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _as_dt(value: Any) -> datetime | None:
    ts = _as_float(value)
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


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


class DevicePing(BaseModel):
    # Same shape as the legacy InstallPing, but install_id is optional — it's
    # only carried as the operator-facing /forget handle and the one-time link
    # to a pre-merge installs row.
    install_id: str | None = Field(default=None, max_length=128)
    created_at: float | None = None
    reason: str | None = None
    software: dict[str, Any] | None = None
    os: dict[str, Any] | None = None
    hardware: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None
    uptime: dict[str, Any] | None = None
    registered: bool | None = None
    machine_id: str | None = None
    accounts: list[dict[str, Any]] | None = None


def _absorbLegacyInstall(db: Session, device: Device, install_id: str) -> None:
    # First ping that carries an install_id links it; if a pre-merge installs
    # row exists for it, fold its history in and delete it — the device is now
    # the single record for this machine.
    if device.install_id is None:
        device.install_id = install_id
    if device.install_id != install_id:
        return
    legacy = db.get(Install, install_id)
    if legacy is None:
        return
    device.ping_count = (device.ping_count or 0) + (legacy.ping_count or 0)
    if legacy.first_seen_at is not None and (
        device.first_ping_at is None or legacy.first_seen_at < device.first_ping_at
    ):
        device.first_ping_at = legacy.first_seen_at
    if device.reported_created_at is None:
        device.reported_created_at = legacy.created_at
    db.delete(legacy)


@router.post("/ping")
@limiter.limit("120/minute")
def ping_device(
    data: DevicePing,
    request: Request,
    db: Session = Depends(get_db),
    device: Device = Depends(get_current_device),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    software = data.software or {}
    os_info = data.os or {}
    hardware = data.hardware or {}
    config = data.config or {}
    usage = data.usage or {}
    uptime = data.uptime or {}

    if data.install_id:
        _absorbLegacyInstall(db, device, data.install_id)

    if device.first_ping_at is None:
        device.first_ping_at = now
    device.ping_count = (device.ping_count or 0) + 1
    device.last_ping_reason = _clip(data.reason)
    reported_created = _as_dt(data.created_at)
    if reported_created is not None and device.reported_created_at is None:
        device.reported_created_at = reported_created

    device.last_seen_at = now
    device.last_seen_ip = _clip(_client_ip(request))
    device.software_version = _clip(software.get("version"))
    device.channel = _clip(software.get("channel"))
    device.commit = _clip(software.get("commit"))
    device.os_name = _clip(os_info.get("name"))
    device.sorter_os_version = _clip(os_info.get("sorter_os_version"))
    device.hw_model = _clip(hardware.get("model"))
    device.ram_bytes = _as_int(hardware.get("ram_bytes"))
    device.cpu_temp_c = _as_float(hardware.get("cpu_temp_c"))
    device.disk_free_bytes = _as_int(hardware.get("disk_free_bytes"))
    device.disk_total_bytes = _as_int(hardware.get("disk_total_bytes"))
    device.machine_setup = _clip(config.get("machine_setup"))
    device.feeder_mode = _clip(config.get("feeder_mode"))
    device.classification_channel_mode = _clip(config.get("classification_channel_mode"))
    device.pieces_seen = _as_int(usage.get("pieces_seen"))
    device.pieces_classified = _as_int(usage.get("pieces_classified"))
    device.pieces_distributed = _as_int(usage.get("pieces_distributed"))
    device.seconds_powered = _as_float(usage.get("seconds_powered"))
    device.seconds_sorted = _as_float(usage.get("seconds_sorted"))
    device.best_hour_ppm = _as_float(usage.get("best_hour_ppm"))
    device.registered = data.registered
    device.process_uptime_s = _as_float(uptime.get("process_s"))
    device.system_uptime_s = _as_float(uptime.get("system_s"))
    # Never clear an id we already learned — if a later ping omits it (account
    # temporarily removed), the link to the operator's machine stays intact.
    if data.machine_id:
        device.local_machine_id = _clip(data.machine_id)
    if data.accounts:
        device.accounts = data.accounts
    device.last_ping_payload = data.model_dump()

    db.commit()
    return {"ok": True}
