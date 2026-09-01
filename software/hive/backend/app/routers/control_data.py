from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_db, require_role
from app.models.machine import Machine
from app.models.machine_control_data_segment import MachineControlDataSegment
from app.models.user import User

router = APIRouter(prefix="/api/admin/control-data", tags=["admin"])

DIMENSION_COLUMNS = ("machine_setup", "feeder_mode", "classification_mode", "autotune_mode")
RECENT_LIMIT = 30


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _duration_s(started_at: datetime | None, ended_at: datetime | None) -> float:
    if started_at is None or ended_at is None:
        return 0.0
    delta = (ended_at - started_at).total_seconds()
    return delta if delta > 0 else 0.0


@router.get("/summary")
def control_data_summary(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    """Fleet-wide inventory of synced control-data (feeder dynamics) segments.

    Aggregated in Python from the segments' summary columns — one lightweight
    row per segment, no file contents. Fine for admin-page traffic at the
    volumes a fleet produces (segments rotate at ~30 min of sorting each).
    """
    rows = (
        db.query(
            MachineControlDataSegment.machine_id,
            MachineControlDataSegment.local_id,
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
            MachineControlDataSegment.created_at,
        )
        .order_by(MachineControlDataSegment.created_at.desc())
        .all()
    )

    machine_names: dict[str, dict[str, Any]] = {}
    if rows:
        machine_ids = {row.machine_id for row in rows}
        for machine in db.query(Machine).filter(Machine.id.in_(machine_ids)).all():
            machine_names[str(machine.id)] = {
                "name": machine.name,
                "owner_email": machine.owner.email if machine.owner else None,
            }

    def _new_bucket() -> dict[str, Any]:
        return {
            "segments": 0,
            "records": 0,
            "bytes": 0,
            "hours": 0.0,
            "with_file": 0,
            "evicted": 0,
            "autotune_session": 0,
            "autotune_background": 0,
            "plain": 0,
            "first_started_at": None,
            "last_ended_at": None,
            "machine_setups": set(),
            "feeder_modes": set(),
            "classification_modes": set(),
        }

    totals = _new_bucket()
    per_machine: dict[str, dict[str, Any]] = defaultdict(_new_bucket)
    dimensions: dict[str, dict[str | None, dict[str, Any]]] = {
        col: defaultdict(lambda: {"segments": 0, "records": 0, "bytes": 0, "hours": 0.0, "machine_ids": set()})
        for col in DIMENSION_COLUMNS
    }

    def _accumulate(bucket: dict[str, Any], row: Any, duration_s: float) -> None:
        bucket["segments"] += 1
        bucket["records"] += row.records or 0
        bucket["bytes"] += row.bytes or 0
        bucket["hours"] += duration_s / 3600.0
        bucket["with_file"] += 1 if row.has_file else 0
        bucket["evicted"] += 1 if row.evicted_locally else 0
        if row.autotune_mode == "session":
            bucket["autotune_session"] += 1
        elif row.autotune_mode == "background":
            bucket["autotune_background"] += 1
        else:
            bucket["plain"] += 1
        if row.started_at and (bucket["first_started_at"] is None or row.started_at < bucket["first_started_at"]):
            bucket["first_started_at"] = row.started_at
        if row.ended_at and (bucket["last_ended_at"] is None or row.ended_at > bucket["last_ended_at"]):
            bucket["last_ended_at"] = row.ended_at
        if row.machine_setup:
            bucket["machine_setups"].add(row.machine_setup)
        if row.feeder_mode:
            bucket["feeder_modes"].add(row.feeder_mode)
        if row.classification_mode:
            bucket["classification_modes"].add(row.classification_mode)

    for row in rows:
        duration_s = _duration_s(row.started_at, row.ended_at)
        _accumulate(totals, row, duration_s)
        _accumulate(per_machine[str(row.machine_id)], row, duration_s)
        for col in DIMENSION_COLUMNS:
            slot = dimensions[col][getattr(row, col)]
            slot["segments"] += 1
            slot["records"] += row.records or 0
            slot["bytes"] += row.bytes or 0
            slot["hours"] += duration_s / 3600.0
            slot["machine_ids"].add(str(row.machine_id))

    def _finish_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
        return {
            "segments": bucket["segments"],
            "records": bucket["records"],
            "bytes": bucket["bytes"],
            "hours": round(bucket["hours"], 2),
            "with_file": bucket["with_file"],
            "evicted": bucket["evicted"],
            "autotune_session": bucket["autotune_session"],
            "autotune_background": bucket["autotune_background"],
            "plain": bucket["plain"],
            "first_started_at": _iso(bucket["first_started_at"]),
            "last_ended_at": _iso(bucket["last_ended_at"]),
            "machine_setups": sorted(bucket["machine_setups"]),
            "feeder_modes": sorted(bucket["feeder_modes"]),
            "classification_modes": sorted(bucket["classification_modes"]),
        }

    machines_out = []
    for machine_id, bucket in per_machine.items():
        info = machine_names.get(machine_id, {})
        machines_out.append(
            {
                "machine_id": machine_id,
                "name": info.get("name") or machine_id,
                "owner_email": info.get("owner_email"),
                **_finish_bucket(bucket),
            }
        )
    machines_out.sort(key=lambda m: m["records"], reverse=True)

    dimensions_out = {
        col: [
            {
                "value": value,
                "segments": slot["segments"],
                "records": slot["records"],
                "bytes": slot["bytes"],
                "hours": round(slot["hours"], 2),
                "machines": len(slot["machine_ids"]),
            }
            for value, slot in sorted(dimensions[col].items(), key=lambda kv: kv[1]["records"], reverse=True)
        ]
        for col in DIMENSION_COLUMNS
    }

    recent_out = [
        {
            "machine_id": str(row.machine_id),
            "machine_name": machine_names.get(str(row.machine_id), {}).get("name") or str(row.machine_id),
            "local_id": row.local_id,
            "started_at": _iso(row.started_at),
            "ended_at": _iso(row.ended_at),
            "duration_s": round(_duration_s(row.started_at, row.ended_at), 1),
            "records": row.records or 0,
            "bytes": row.bytes or 0,
            "machine_setup": row.machine_setup,
            "feeder_mode": row.feeder_mode,
            "autotune_mode": row.autotune_mode,
            "has_file": bool(row.has_file),
            "created_at": _iso(row.created_at),
        }
        for row in rows[:RECENT_LIMIT]
    ]

    totals_out = _finish_bucket(totals)
    totals_out["machines"] = len(per_machine)

    return {
        "totals": totals_out,
        "machines": machines_out,
        "dimensions": dimensions_out,
        "recent": recent_out,
    }
