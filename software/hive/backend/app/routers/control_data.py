from collections import defaultdict
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_db, require_role
from app.models.machine import Machine
from app.models.machine_control_data_segment import MachineControlDataSegment
from app.models.machine_stats_cache import MachineStatsCache
from app.models.user import User
from app.services.control_data import DIMENSION_COLUMNS
from app.services.control_data import duration_s as _duration_s
from app.services.control_data import iso as _iso

router = APIRouter(prefix="/api/admin/control-data", tags=["admin"])

RECENT_LIMIT = 30


@router.get("/summary")
def control_data_summary(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    """Fleet-wide inventory of synced control-data (feeder dynamics) segments.

    Added up from each machine's segments per combination of modes, which the
    stats worker keeps (machine_stats_cache.control_data, hourly), plus the
    newest RECENT_LIMIT segments read through their created_at index: no
    request reads every segment.
    """
    cached = {
        str(machine_id): data
        for machine_id, data in db.query(MachineStatsCache.machine_id, MachineStatsCache.control_data)
        if data and data.get("groups")
    }
    recent = (
        db.query(
            MachineControlDataSegment.machine_id,
            MachineControlDataSegment.local_id,
            MachineControlDataSegment.started_at,
            MachineControlDataSegment.ended_at,
            MachineControlDataSegment.records,
            MachineControlDataSegment.bytes,
            MachineControlDataSegment.machine_setup,
            MachineControlDataSegment.feeder_mode,
            MachineControlDataSegment.autotune_mode,
            MachineControlDataSegment.data_key.isnot(None).label("has_file"),
            MachineControlDataSegment.created_at,
        )
        .order_by(MachineControlDataSegment.created_at.desc())
        .limit(RECENT_LIMIT)
        .all()
    )

    machine_names: dict[str, dict[str, Any]] = {}
    machine_ids = {UUID(mid) for mid in cached} | {row.machine_id for row in recent}
    if machine_ids:
        for machine in db.query(Machine).filter(Machine.id.in_(list(machine_ids))).all():
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

    def _accumulate(bucket: dict[str, Any], group: dict[str, Any]) -> None:
        bucket["segments"] += group["segments"]
        bucket["records"] += group["records"]
        bucket["bytes"] += group["bytes"]
        bucket["hours"] += group["seconds"] / 3600.0
        bucket["with_file"] += group["with_file"]
        bucket["evicted"] += group["evicted"]
        if group["autotune_mode"] == "session":
            bucket["autotune_session"] += group["segments"]
        elif group["autotune_mode"] == "background":
            bucket["autotune_background"] += group["segments"]
        else:
            bucket["plain"] += group["segments"]
        first, last = group["first_started_at"], group["last_ended_at"]
        if first and (bucket["first_started_at"] is None or first < bucket["first_started_at"]):
            bucket["first_started_at"] = first
        if last and (bucket["last_ended_at"] is None or last > bucket["last_ended_at"]):
            bucket["last_ended_at"] = last
        if group["machine_setup"]:
            bucket["machine_setups"].add(group["machine_setup"])
        if group["feeder_mode"]:
            bucket["feeder_modes"].add(group["feeder_mode"])
        if group["classification_mode"]:
            bucket["classification_modes"].add(group["classification_mode"])

    for machine_id, data in cached.items():
        for group in data["groups"]:
            _accumulate(totals, group)
            _accumulate(per_machine[machine_id], group)
            for col in DIMENSION_COLUMNS:
                slot = dimensions[col][group[col]]
                slot["segments"] += group["segments"]
                slot["records"] += group["records"]
                slot["bytes"] += group["bytes"]
                slot["hours"] += group["seconds"] / 3600.0
                slot["machine_ids"].add(machine_id)

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
            # Kept as ISO strings, which sort as the times do.
            "first_started_at": bucket["first_started_at"],
            "last_ended_at": bucket["last_ended_at"],
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
        for row in recent
    ]

    totals_out = _finish_bucket(totals)
    totals_out["machines"] = len(per_machine)

    return {
        "totals": totals_out,
        "machines": machines_out,
        "dimensions": dimensions_out,
        "recent": recent_out,
    }
