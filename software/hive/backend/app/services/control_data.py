"""Control-data segments summed per machine and combination of modes.

The admin inventory (GET /api/admin/control-data/summary) adds these up: the
stats worker keeps one summary per machine (machine_stats_cache.control_data)
so no request reads every segment.
"""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.machine_control_data_segment import MachineControlDataSegment

DIMENSION_COLUMNS = ("machine_setup", "feeder_mode", "classification_mode", "autotune_mode")


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def duration_s(started_at: datetime | None, ended_at: datetime | None) -> float:
    if started_at is None or ended_at is None:
        return 0.0
    delta = (ended_at - started_at).total_seconds()
    return delta if delta > 0 else 0.0


def summarize_segments(rows) -> dict[str, Any]:
    """One machine's segments summed per combination of modes: what the stats
    worker keeps in machine_stats_cache.control_data for the admin summary.
    ``rows`` carry the segment columns the summary reads."""
    groups: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        modes = tuple(getattr(row, col) for col in DIMENSION_COLUMNS)
        g = groups.setdefault(
            modes,
            {"segments": 0, "records": 0, "bytes": 0, "seconds": 0.0, "with_file": 0, "evicted": 0,
             "first_started_at": None, "last_ended_at": None},
        )
        g["segments"] += 1
        g["records"] += row.records or 0
        g["bytes"] += row.bytes or 0
        g["seconds"] += duration_s(row.started_at, row.ended_at)
        g["with_file"] += 1 if row.has_file else 0
        g["evicted"] += 1 if row.evicted_locally else 0
        if row.started_at and (g["first_started_at"] is None or row.started_at < g["first_started_at"]):
            g["first_started_at"] = row.started_at
        if row.ended_at and (g["last_ended_at"] is None or row.ended_at > g["last_ended_at"]):
            g["last_ended_at"] = row.ended_at
    return {
        "groups": [
            {**dict(zip(DIMENSION_COLUMNS, modes)), **g,
             "first_started_at": iso(g["first_started_at"]), "last_ended_at": iso(g["last_ended_at"])}
            for modes, g in groups.items()
        ]
    }


def segment_rows(db: Session, machine_ids: list):
    """The segment columns ``summarize_segments`` reads, for these machines."""
    return (
        db.query(
            MachineControlDataSegment.machine_id,
            MachineControlDataSegment.started_at,
            MachineControlDataSegment.ended_at,
            MachineControlDataSegment.records,
            MachineControlDataSegment.bytes,
            MachineControlDataSegment.machine_setup,
            MachineControlDataSegment.feeder_mode,
            MachineControlDataSegment.classification_mode,
            MachineControlDataSegment.autotune_mode,
            MachineControlDataSegment.data_key.isnot(None).label("has_file"),
            MachineControlDataSegment.evicted_locally,
        )
        .filter(MachineControlDataSegment.machine_id.in_(machine_ids))
        .all()
    )
