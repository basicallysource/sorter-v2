"""The telemetry limits Hive sets for machines.

A machine learns its limits from the heartbeat response (``limits``), so Hive
can slow the whole fleet down, or open it up, without a software release. The
values live in one global row of ``telemetry_limits``; the defaults below apply
while that row is missing.

``effective_limits`` takes the machine so per-machine overrides can be added
later without changing any caller.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.machine import Machine
from app.models.telemetry_limits import TelemetryLimits

# Version of the limits contract a machine reads. Bump it only when a field
# changes meaning, never when a value changes.
LIMITS_VERSION = 1

GLOBAL_ROW_ID = 1

DEFAULT_LIMITS: dict[str, float | int] = {
    "sample_burst_interval_s": 10.0,
    "sample_floor_interval_s": 3600.0,
    "sample_ramp_hours": 72.0,
    "sample_store_max_bytes": 1073741824,
    "upload_bytes_per_minute": 30000000,
    "upload_files_per_minute": 120,
}

LIMIT_FIELDS = tuple(DEFAULT_LIMITS)


class TelemetryLimitsError(ValueError):
    """A set of limits that cannot work together."""


def _row(db: Session) -> TelemetryLimits | None:
    return db.get(TelemetryLimits, GLOBAL_ROW_ID)


def _values(row: TelemetryLimits | None) -> dict[str, float | int]:
    if row is None:
        return dict(DEFAULT_LIMITS)
    values: dict[str, float | int] = {}
    for field, default in DEFAULT_LIMITS.items():
        value = getattr(row, field)
        if value is None:
            value = default
        values[field] = float(value) if isinstance(default, float) else int(value)
    return values


def global_limits(db: Session) -> dict[str, Any]:
    """The global limits as an admin sees them: the six values, plus when they
    were last changed (None while the defaults apply)."""
    row = _row(db)
    return {
        "version": LIMITS_VERSION,
        **_values(row),
        "updated_at": row.updated_at.isoformat() if row is not None and row.updated_at else None,
    }


def effective_limits(db: Session, machine: Machine) -> dict[str, Any]:
    """The limits ``machine`` must keep to. Today every machine gets the global
    limits."""
    del machine  # Reserved for per-machine overrides.
    return {"version": LIMITS_VERSION, **_values(_row(db))}


def update_global_limits(db: Session, changes: dict[str, float | int]) -> dict[str, Any]:
    """Apply a partial update to the global limits and commit it.

    Every value must be positive (the caller's schema checks that), and the
    floor interval may not be shorter than the burst interval, since the ramp
    goes from the burst toward the floor. Raises ``TelemetryLimitsError``
    without writing anything when the result would be invalid.
    """
    unknown = set(changes) - set(LIMIT_FIELDS)
    if unknown:
        raise TelemetryLimitsError(f"Unknown limit fields: {', '.join(sorted(unknown))}")

    row = _row(db)
    merged = _values(row)
    merged.update({k: v for k, v in changes.items() if v is not None})
    for field, value in merged.items():
        if value <= 0:
            raise TelemetryLimitsError(f"{field} must be positive")
    if merged["sample_floor_interval_s"] < merged["sample_burst_interval_s"]:
        raise TelemetryLimitsError("sample_floor_interval_s must be at least sample_burst_interval_s")

    if row is None:
        row = TelemetryLimits(id=GLOBAL_ROW_ID)
        db.add(row)
    for field, value in merged.items():
        setattr(row, field, value)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return global_limits(db)
