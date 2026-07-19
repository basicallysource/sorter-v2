"""Recording and summarizing machine hardware/software specs.

A machine attaches a specs snapshot to its heartbeat. We keep two things from
it: an append-only history row (the full snapshot, so a machine's hardware can
be tracked across restarts) and a compact summary on the machine row that the
dashboard renders. The summary is an explicit allowlist of the fields the
dashboard shows; the rest stays in the history table.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.machine import Machine
from app.models.machine_hardware_report import MachineHardwareReport

# Camera fields the dashboard shows (model + capture format + calibration state).
_SUMMARY_CAMERA_KEYS = ("model", "width", "height", "fps", "fourcc", "calibration")


def _summary_cameras(cameras: Any) -> dict[str, Any]:
    if not isinstance(cameras, dict):
        return {}
    out: dict[str, Any] = {}
    for role, entry in cameras.items():
        if isinstance(entry, dict):
            out[str(role)] = {key: entry.get(key) for key in _SUMMARY_CAMERA_KEYS}
    return out


def summarize_hardware_specs(specs: Any) -> dict[str, Any] | None:
    """The compact subset of a specs snapshot that the dashboard renders."""
    if not isinstance(specs, dict):
        return None
    platform_in = specs.get("platform")
    if not isinstance(platform_in, dict):
        platform_in = {}
    return {
        "schema_version": specs.get("schema_version"),
        "booted_at": specs.get("booted_at"),
        "captured_at": specs.get("captured_at"),
        "platform": {
            "model": platform_in.get("model"),
            "arch": platform_in.get("arch"),
            "os": platform_in.get("os"),
        },
        "software": specs.get("software"),
        "system": specs.get("system"),
        "config": specs.get("config"),
        "cameras": _summary_cameras(specs.get("cameras")),
        "controller_boards": specs.get("controller_boards"),
    }


def _content_hash(summary: dict[str, Any]) -> str:
    # Hash the stable content so history grows on meaningful spec changes — not
    # on every heartbeat's fresh capture timestamp.
    stable = {key: value for key, value in summary.items() if key not in ("captured_at", "booted_at", "schema_version")}
    encoded = json.dumps(stable, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def record_hardware_report(db: Session, machine: Machine, specs: Any) -> None:
    """Store the summary on the machine and append a history row when the
    machine rebooted or its specs changed. Best-effort: a snapshot that isn't a
    dict is ignored."""
    summary = summarize_hardware_specs(specs)
    if summary is None:
        return

    machine.hardware_info = summary

    content_hash = _content_hash(summary)
    boot_id = specs.get("boot_id") if isinstance(specs.get("boot_id"), str) else None
    latest = (
        db.query(MachineHardwareReport)
        .filter(MachineHardwareReport.machine_id == machine.id)
        .order_by(MachineHardwareReport.reported_at.desc())
        .first()
    )
    changed = (
        latest is None
        or latest.content_hash != content_hash
        or (boot_id is not None and latest.boot_id != boot_id)
    )
    if changed:
        db.add(
            MachineHardwareReport(
                machine_id=machine.id,
                boot_id=boot_id,
                content_hash=content_hash,
                specs=specs,
                reported_at=datetime.now(timezone.utc),
            )
        )
