"""Public, unauthenticated endpoints for the anonymous sorter fleet.

DEPRECATED as a system: the anonymous installs concept has merged into the
Device identity (routers/devices.py) — new software pings /api/devices/ping
under a device token, and the first such ping absorbs this table's row for its
install_id. These endpoints stay only for machines running pre-merge software.

`POST /api/installs/ping` — a machine's hourly "I exist / I'm online" report
(legacy status_ping.py on the machine). No auth: an unregistered machine has no
token, and the whole point is to hear from every machine, registered or not.
The row is keyed by the machine-chosen install_id.

`POST /api/installs/forget` — the deletion path behind the public /forget page:
paste an install_id, everything held for it is erased — the legacy installs row
AND the telemetry columns of any device that absorbed it. Idempotent. The
device's service identity (enrollment, color-prediction logs) is not touched;
those are governed by the color-provider opt-in, not the status ping.

Both are rate limited per source IP.
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
from app.models.install import Install

router = APIRouter(prefix="/api/installs", tags=["installs"])
limiter = Limiter(key_func=get_remote_address)

# Only the keys we hand to the DB layer are trusted; anything else in the JSON
# body is ignored for column mapping but preserved wholesale in last_payload.
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
    # Client sends unix seconds; store as tz-aware UTC.
    ts = _as_float(value)
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


class InstallPing(BaseModel):
    install_id: str = Field(min_length=1, max_length=128)
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


class ForgetRequest(BaseModel):
    install_id: str = Field(min_length=1, max_length=128)


@router.post("/ping")
@limiter.limit("120/minute")
def ping(data: InstallPing, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    software = data.software or {}
    os_info = data.os or {}
    hardware = data.hardware or {}
    config = data.config or {}
    usage = data.usage or {}
    uptime = data.uptime or {}

    install = db.get(Install, data.install_id)
    if install is None:
        install = Install(install_id=data.install_id, first_seen_at=now, ping_count=0)
        db.add(install)

    install.last_seen_at = now
    install.ping_count = (install.ping_count or 0) + 1
    install.last_reason = _clip(data.reason)
    # created_at is set once — the earliest the machine claims it came online.
    reported_created = _as_dt(data.created_at)
    if reported_created is not None and install.created_at is None:
        install.created_at = reported_created

    install.last_ip = _clip(_client_ip(request))
    install.software_version = _clip(software.get("version"))
    install.channel = _clip(software.get("channel"))
    install.commit = _clip(software.get("commit"))
    install.os_name = _clip(os_info.get("name"))
    install.sorter_os_version = _clip(os_info.get("sorter_os_version"))
    install.hw_model = _clip(hardware.get("model"))
    install.ram_bytes = _as_int(hardware.get("ram_bytes"))
    install.cpu_temp_c = _as_float(hardware.get("cpu_temp_c"))
    install.disk_free_bytes = _as_int(hardware.get("disk_free_bytes"))
    install.disk_total_bytes = _as_int(hardware.get("disk_total_bytes"))
    install.machine_setup = _clip(config.get("machine_setup"))
    install.feeder_mode = _clip(config.get("feeder_mode"))
    install.classification_channel_mode = _clip(config.get("classification_channel_mode"))
    install.pieces_seen = _as_int(usage.get("pieces_seen"))
    install.pieces_classified = _as_int(usage.get("pieces_classified"))
    install.pieces_distributed = _as_int(usage.get("pieces_distributed"))
    install.seconds_powered = _as_float(usage.get("seconds_powered"))
    install.seconds_sorted = _as_float(usage.get("seconds_sorted"))
    install.best_hour_ppm = _as_float(usage.get("best_hour_ppm"))
    install.registered = data.registered
    install.process_uptime_s = _as_float(uptime.get("process_s"))
    install.system_uptime_s = _as_float(uptime.get("system_s"))
    # Account identity (registered machines only). Never clear an id we already
    # learned — if a later ping omits it (e.g. account temporarily removed), the
    # link to the operator's machine stays intact.
    if data.machine_id:
        install.machine_id = _clip(data.machine_id)
    if data.accounts:
        install.accounts = data.accounts
    install.last_payload = data.model_dump()

    db.commit()
    return {"ok": True}


_DEVICE_TELEMETRY_FIELDS = (
    "first_ping_at",
    "last_ping_reason",
    "reported_created_at",
    "country",
    "region",
    "software_version",
    "channel",
    "commit",
    "os_name",
    "sorter_os_version",
    "hw_model",
    "ram_bytes",
    "cpu_temp_c",
    "disk_free_bytes",
    "disk_total_bytes",
    "machine_setup",
    "feeder_mode",
    "classification_channel_mode",
    "pieces_seen",
    "pieces_classified",
    "pieces_distributed",
    "seconds_powered",
    "seconds_sorted",
    "best_hour_ppm",
    "registered",
    "process_uptime_s",
    "system_uptime_s",
    "local_machine_id",
    "accounts",
    "last_ping_payload",
)


@router.post("/forget")
@limiter.limit("30/minute")
def forget(data: ForgetRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    from app.models.device import Device

    deleted = db.query(Install).filter(Install.install_id == data.install_id).delete()

    # The install may have been absorbed into a device (post-merge software):
    # honor the same promise by wiping the device's telemetry and unlinking the
    # id. Future pings from that machine start a fresh telemetry record unless
    # the operator sets SORTER_BASE_REPORTING_OFF.
    devices = db.query(Device).filter(Device.install_id == data.install_id).all()
    for device in devices:
        device.install_id = None
        device.ping_count = 0
        for field in _DEVICE_TELEMETRY_FIELDS:
            setattr(device, field, None)

    db.commit()
    return {"ok": True, "deleted": int(deleted) + len(devices)}
