"""Analytics over an arbitrary set of machines.

The same primitives serve every context — one machine, a user's whole fleet, one
user's fleet (admin), or the entire fleet (admin) — by resolving the request to a
list of machine ids and aggregating over it:

  * time-series  — machines / pieces / distributed / avg-PPM / sorting-capacity
    per day, from the pre-computed machine_daily_stats table.
  * distributions — pieces by machine / classification status / top parts / top
    colors (live group-bys, cheap at current scale).
  * totals        — headline numbers for the set.

"Sorting capacity" on day D = for each machine active that day, its PPM that day
projected over a full day (× 1440 min), summed across machines — i.e. how many
pieces the fleet could theoretically sort in a day at that day's throughput.
"""

from __future__ import annotations

import uuid as uuid_mod
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.errors import APIError
from app.models.machine import Machine
from app.models.machine_daily_stats import MachineDailyStats
from app.models.machine_piece import MachinePiece
from app.models.user import User

# Idle-gap threshold — must match app.services.machine_stats so the derived
# active time is consistent between the summary cache and the daily table.
ACTIVE_GAP_IDLE_S = 60.0
MINUTES_PER_DAY = 1440.0


# --------------------------------------------------------------------------- refresh

def refresh_daily_stats(db: Session) -> int:
    """Recompute per-(machine, day) pieces/distributed/active_seconds and upsert.

    Full recompute each pass — pieces are only ever appended, so upsert-in-place
    keeps every day correct without deleting anything. Returns rows written.
    """
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy import text

        result = db.execute(
            text(
                """
                INSERT INTO machine_daily_stats (machine_id, day, pieces_seen, distributed, active_seconds)
                SELECT machine_id, day,
                       count(*) AS pieces_seen,
                       count(*) FILTER (WHERE bin_x IS NOT NULL) AS distributed,
                       COALESCE(SUM(CASE WHEN gap > 0 AND gap <= :idle THEN gap ELSE 0 END), 0) AS active_seconds
                FROM (
                    SELECT machine_id, bin_x,
                           (seen_at AT TIME ZONE 'UTC')::date AS day,
                           EXTRACT(EPOCH FROM (
                               seen_at - LAG(seen_at) OVER (
                                   PARTITION BY machine_id ORDER BY seen_at, local_id))) AS gap
                    FROM machine_pieces
                    WHERE seen_at IS NOT NULL
                ) g
                GROUP BY machine_id, day
                ON CONFLICT (machine_id, day) DO UPDATE SET
                    pieces_seen = EXCLUDED.pieces_seen,
                    distributed = EXCLUDED.distributed,
                    active_seconds = EXCLUDED.active_seconds
                """
            ),
            {"idle": ACTIVE_GAP_IDLE_S},
        )
        db.commit()
        return result.rowcount or 0

    return _refresh_daily_stats_python(db)


def _refresh_daily_stats_python(db: Session) -> int:
    """SQLite / non-Postgres fallback — compute in Python, upsert via ORM."""
    rows = (
        db.query(
            MachinePiece.machine_id,
            MachinePiece.seen_at,
            MachinePiece.bin_x,
        )
        .filter(MachinePiece.seen_at.isnot(None))
        .order_by(MachinePiece.machine_id, MachinePiece.seen_at, MachinePiece.local_id)
        .all()
    )
    agg: dict[tuple[Any, Any], dict[str, float]] = {}
    prev_mid = None
    prev_seen = None
    for mid, seen_at, bin_x in rows:
        day = seen_at.date()
        key = (str(mid), day)
        cell = agg.setdefault(key, {"pieces": 0, "distributed": 0, "active": 0.0})
        cell["pieces"] += 1
        if bin_x is not None:
            cell["distributed"] += 1
        if prev_mid == str(mid) and prev_seen is not None:
            gap = (seen_at - prev_seen).total_seconds()
            if 0 < gap <= ACTIVE_GAP_IDLE_S:
                cell["active"] += gap
        prev_mid = str(mid)
        prev_seen = seen_at

    existing = {(str(r.machine_id), r.day): r for r in db.query(MachineDailyStats).all()}
    for (mid, day), cell in agg.items():
        row = existing.get((mid, day))
        if row is None:
            row = MachineDailyStats(machine_id=uuid_mod.UUID(mid), day=day)
            db.add(row)
        row.pieces_seen = int(cell["pieces"])
        row.distributed = int(cell["distributed"])
        row.active_seconds = float(cell["active"])
    db.commit()
    return len(agg)


# --------------------------------------------------------------------------- scope

def resolve_machine_set(
    db: Session,
    current_user: User,
    *,
    machine_id: Any | None = None,
    owner_id: Any | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """Resolve + authorize a machine set. Returns {ids, kind, label}.

    Precedence: machine_id > owner_id > scope. Default is the caller's own fleet.
    Non-owner/non-admin access to another's machine yields 404 (existence hidden).
    """
    is_admin = current_user.role == "admin"

    if machine_id is not None:
        machine = db.query(Machine).filter(Machine.id == machine_id).first()
        if machine is None or (str(machine.owner_id) != str(current_user.id) and not is_admin):
            raise APIError(404, "Machine not found", "MACHINE_NOT_FOUND")
        return {"ids": [machine.id], "kind": "machine", "label": machine.name}

    if owner_id is not None:
        if str(owner_id) != str(current_user.id) and not is_admin:
            raise APIError(403, "Forbidden", "FORBIDDEN")
        ids = _owner_ids(db, owner_id)
        owner = db.query(User).filter(User.id == owner_id).first()
        label = (owner.display_name or owner.email) if owner else "fleet"
        return {"ids": ids, "kind": "owner_fleet", "label": label}

    if scope == "all":
        if not is_admin:
            raise APIError(403, "Admin only", "FORBIDDEN")
        ids = [mid for (mid,) in db.query(Machine.id).filter(Machine.archived_at.is_(None)).all()]
        return {"ids": ids, "kind": "all", "label": "All machines"}

    return {"ids": _owner_ids(db, current_user.id), "kind": "my_fleet", "label": "My machines"}


def _owner_ids(db: Session, owner_id: Any) -> list[Any]:
    return [
        mid
        for (mid,) in db.query(Machine.id)
        .filter(Machine.owner_id == owner_id, Machine.archived_at.is_(None))
        .all()
    ]


# --------------------------------------------------------------------------- reads

def get_timeseries(db: Session, machine_ids: list[Any]) -> list[dict[str, Any]]:
    if not machine_ids:
        return []
    rows = (
        db.query(MachineDailyStats)
        .filter(MachineDailyStats.machine_id.in_(machine_ids))
        .order_by(MachineDailyStats.day)
        .all()
    )
    if not rows:
        return []

    day_agg: dict[Any, dict[str, Any]] = {}
    machine_first_day: dict[str, Any] = {}
    for r in rows:
        d = r.day
        cell = day_agg.setdefault(d, {"pieces": 0, "distributed": 0, "active": 0.0, "cap": 0.0, "ppms": []})
        cell["pieces"] += r.pieces_seen
        cell["distributed"] += r.distributed
        cell["active"] += r.active_seconds
        if r.active_seconds and r.active_seconds > 0:
            ppm = r.distributed * 60.0 / r.active_seconds
            cell["cap"] += ppm * MINUTES_PER_DAY
            cell["ppms"].append(ppm)
        mid = str(r.machine_id)
        if mid not in machine_first_day or d < machine_first_day[mid]:
            machine_first_day[mid] = d

    first_days = sorted(machine_first_day.values())
    days = sorted(day_agg.keys())

    series: list[dict[str, Any]] = []
    cum_pieces = 0
    cum_distributed = 0
    fd_idx = 0
    for d in days:
        cell = day_agg[d]
        cum_pieces += cell["pieces"]
        cum_distributed += cell["distributed"]
        while fd_idx < len(first_days) and first_days[fd_idx] <= d:
            fd_idx += 1
        throughput = (cell["distributed"] * 60.0 / cell["active"]) if cell["active"] > 0 else 0.0
        avg_ppm = (sum(cell["ppms"]) / len(cell["ppms"])) if cell["ppms"] else 0.0
        series.append(
            {
                "day": d.isoformat(),
                "pieces_seen": cell["pieces"],
                "distributed": cell["distributed"],
                "active_seconds": round(cell["active"], 1),
                "avg_ppm": round(avg_ppm, 3),
                "throughput_ppm": round(throughput, 3),
                "capacity_per_day": round(cell["cap"], 1),
                "cumulative_pieces": cum_pieces,
                "cumulative_distributed": cum_distributed,
                "cumulative_machines": fd_idx,
            }
        )
    return series


def get_distributions(db: Session, machine_ids: list[Any]) -> dict[str, Any]:
    if not machine_ids:
        return {"by_machine": [], "by_status": [], "top_parts": [], "top_colors": []}

    base = db.query(MachinePiece).filter(MachinePiece.machine_id.in_(machine_ids))

    by_status = [
        {"label": status or "unknown", "value": count}
        for status, count in (
            base.with_entities(MachinePiece.classification_status, func.count())
            .group_by(MachinePiece.classification_status)
            .all()
        )
    ]

    top_parts = [
        {"part_id": pid, "part_name": pname, "value": count}
        for pid, pname, count in (
            base.with_entities(MachinePiece.part_id, func.max(MachinePiece.part_name), func.count())
            .filter(MachinePiece.part_id.isnot(None))
            .group_by(MachinePiece.part_id)
            .order_by(func.count().desc())
            .limit(15)
            .all()
        )
    ]

    top_colors = [
        {"color_id": cid, "color_name": cname, "value": count}
        for cid, cname, count in (
            base.with_entities(MachinePiece.color_id, func.max(MachinePiece.color_name), func.count())
            .filter(MachinePiece.color_id.isnot(None))
            .group_by(MachinePiece.color_id)
            .order_by(func.count().desc())
            .limit(15)
            .all()
        )
    ]

    by_machine: list[dict[str, Any]] = []
    if len(machine_ids) > 1:
        name_by_id = {
            str(mid): name
            for mid, name in db.query(Machine.id, Machine.name).filter(Machine.id.in_(machine_ids)).all()
        }
        rows = (
            base.with_entities(MachinePiece.machine_id, func.count())
            .group_by(MachinePiece.machine_id)
            .order_by(func.count().desc())
            .all()
        )
        by_machine = [
            {"machine_id": str(mid), "label": name_by_id.get(str(mid), "?"), "value": count}
            for mid, count in rows
        ]

    return {
        "by_machine": by_machine,
        "by_status": by_status,
        "top_parts": top_parts,
        "top_colors": top_colors,
    }


def get_totals(db: Session, machine_ids: list[Any], series: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    empty = {
        "machines": 0, "pieces_seen": 0, "distributed": 0, "classified": 0,
        "unique_parts": 0, "unique_colors": 0, "active_seconds": 0.0,
        "overall_ppm": 0.0, "capacity_recent": 0.0, "first_day": None, "last_day": None,
    }
    if not machine_ids:
        return empty

    agg = (
        db.query(
            func.count().label("pieces_seen"),
            func.count().filter(MachinePiece.bin_x.isnot(None)).label("distributed"),
            func.count().filter(MachinePiece.classification_status == "classified").label("classified"),
            func.count(func.distinct(MachinePiece.part_id)).label("unique_parts"),
            func.count(func.distinct(MachinePiece.color_id)).label("unique_colors"),
        )
        .filter(MachinePiece.machine_id.in_(machine_ids))
        .one()
    )
    active_seconds = (
        db.query(func.coalesce(func.sum(MachineDailyStats.active_seconds), 0.0))
        .filter(MachineDailyStats.machine_id.in_(machine_ids))
        .scalar()
    ) or 0.0
    day_bounds = (
        db.query(func.min(MachineDailyStats.day), func.max(MachineDailyStats.day))
        .filter(MachineDailyStats.machine_id.in_(machine_ids))
        .one()
    )
    machines_with_pieces = (
        db.query(func.count(func.distinct(MachinePiece.machine_id)))
        .filter(MachinePiece.machine_id.in_(machine_ids))
        .scalar()
    ) or 0

    distributed = agg.distributed or 0
    overall_ppm = (distributed * 60.0 / active_seconds) if active_seconds > 0 else 0.0

    # Recent capacity = the most recent day's theoretical daily throughput.
    if series is None:
        series = get_timeseries(db, machine_ids)
    capacity_recent = series[-1]["capacity_per_day"] if series else 0.0

    return {
        "machines": machines_with_pieces,
        "pieces_seen": agg.pieces_seen or 0,
        "distributed": distributed,
        "classified": agg.classified or 0,
        "unique_parts": agg.unique_parts or 0,
        "unique_colors": agg.unique_colors or 0,
        "active_seconds": round(active_seconds, 1),
        "overall_ppm": round(overall_ppm, 3),
        "capacity_recent": capacity_recent,
        "first_day": day_bounds[0].isoformat() if day_bounds[0] else None,
        "last_day": day_bounds[1].isoformat() if day_bounds[1] else None,
    }


def get_analytics(db: Session, machine_ids: list[Any]) -> dict[str, Any]:
    series = get_timeseries(db, machine_ids)
    return {
        "totals": get_totals(db, machine_ids, series=series),
        "timeseries": series,
        "distributions": get_distributions(db, machine_ids),
    }
