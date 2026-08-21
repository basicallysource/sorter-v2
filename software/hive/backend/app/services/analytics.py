"""Analytics over an arbitrary set of machines.

**No request aggregates.** Every number served here is a fold over two
pre-computed tables — machine_stats_cache (one row per machine, hourly) and
machine_daily_stats (one row per machine-day) — and the fold is plain Python
over rows fetched by primary key. The set a caller asks about (one machine, one
owner's fleet, yours, the whole fleet) only chooses which rows to add up.

That rule is the point of this module and it was learned the expensive way. The
version this replaced ran the group-bys live, "cheap at current scale". By
August 2026 machine_pieces held 354k rows in 240 MB, one /stats call was about
18 sequential scans of it and took 5-7 seconds, the public site called it every
6 seconds, and both of prod's vCPUs were pinned around the clock. Nothing about
that was a sudden failure: the cost per call had been growing linearly with the
table since June and nobody was watching it.

So: if a number here starts needing a scan of machine_pieces, it belongs in the
worker that builds the cache (`services/machine_stats.py`), not here.

The one exception, deliberately: `_live_pieces_since` counts rows newer than
the cache watermark through the (machine_id, seen_at) index, so the headline
piece counter ticks up between hourly passes. It reads minutes of data, never
the table.

  * time-series  — machines / pieces / distributed / avg-PPM / sorting-capacity
    per day, from machine_daily_stats.
  * distributions — pieces by machine / classification status / top parts /
    colors / categories, folded from the cached per-machine maps.
  * totals        — headline numbers for the set, plus the live top-up.

"Sorting capacity" on day D = for each machine active that day, its PPM that day
projected over a full day (× 1440 min), summed across machines — i.e. how many
pieces the fleet could theoretically sort in a day at that day's throughput.
"""

from __future__ import annotations

import uuid as uuid_mod
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.errors import APIError
from app.models.machine import Machine
from app.models.machine_daily_stats import MachineDailyStats
from app.models.machine_piece import MachinePiece
from app.models.machine_stats_cache import MachineStatsCache
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


def _category_distribution(part_counts: list[tuple[Any, int]], limit: int) -> list[dict[str, Any]]:
    """Fold per-part counts into a BrickLink-category breakdown, biggest first.

    The pieces table knows a part but not its category, so the counts come
    grouped by part here and the catalog supplies the category. A part the
    catalog can't place is pooled under "Unknown" rather than dropped, so the
    shares still add up to every piece with a part id. Best-effort: no catalog,
    no breakdown."""
    if not part_counts:
        return []
    try:
        from app.services.profile_catalog import get_profile_catalog_service

        cat_by_part = get_profile_catalog_service().bricklink_category_names(
            [str(pid) for pid, _ in part_counts]
        )
    except Exception:
        return []

    totals: dict[str, int] = {}
    for pid, count in part_counts:
        name = cat_by_part.get(str(pid)) or "Unknown"
        totals[name] = totals.get(name, 0) + count
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{"category_name": name, "value": value} for name, value in ranked]


def _bricklink_rgb() -> dict[int, str | None]:
    """BrickLink color id -> swatch hex (no leading '#'), from the parts catalog.

    Best-effort and imported lazily: analytics is imported all over, the catalog
    is heavy, and a box without it loaded should still serve distributions —
    just with no rgb, which a client treats as "no swatch"."""
    try:
        from app.services.profile_catalog import get_profile_catalog_service

        return {c["id"]: c.get("rgb") for c in get_profile_catalog_service().list_bricklink_colors()}
    except Exception:
        return {}


def _fold_cached(db: Session, machine_ids: list[Any]) -> dict[str, Any]:
    """Merge the cached per-machine rows for a set into one aggregate.

    Pure Python over rows already fetched by primary key. Sums are sums; the
    part and colour maps are merged key-by-key, which is what makes
    `unique_parts` for a set exactly the size of the union rather than an
    estimate, and what makes a fleet-wide top-15 correct rather than a top-15
    of top-15s.
    """
    rows = (
        db.query(MachineStatsCache).filter(MachineStatsCache.machine_id.in_(machine_ids)).all()
        if machine_ids
        else []
    )

    totals = {"pieces_seen": 0, "distributed": 0, "classified": 0, "machines": 0}
    status: dict[str, int] = {}
    parts: dict[str, list[Any]] = {}
    colors: dict[str, list[Any]] = {}
    by_machine: list[tuple[str, int]] = []
    # Machines grouped by how fresh their row is, which is what the live top-up
    # counts forward from. Per machine and not per set: a machine with no row
    # yet (registered since the last pass) contributes nothing to the sums, so
    # its bucket is None and ALL of its pieces are counted live. That is the
    # cold-start case handled by arithmetic instead of by a special case.
    cached = {str(row.machine_id): row for row in rows}
    since_buckets: dict[datetime | None, list[Any]] = {}
    for mid in machine_ids:
        row = cached.get(str(mid))
        since_buckets.setdefault(row.computed_at if row is not None else None, []).append(mid)

    for row in rows:
        totals["pieces_seen"] += row.pieces_seen or 0
        totals["distributed"] += row.distributed or 0
        totals["classified"] += row.classified or 0
        if row.pieces_seen:
            totals["machines"] += 1
            by_machine.append((str(row.machine_id), int(row.pieces_seen)))

        dist = row.distributions or {}
        for label, count in (dist.get("status") or {}).items():
            status[label] = status.get(label, 0) + int(count)
        for src, dest in ((dist.get("parts") or {}, parts), (dist.get("colors") or {}, colors)):
            for key, entry in src.items():
                count, name = (entry + [None])[:2] if isinstance(entry, list) else (entry, None)
                current = dest.get(key)
                if current is None:
                    dest[key] = [int(count), name]
                else:
                    current[0] += int(count)
                    current[1] = current[1] or name

    return {
        "totals": totals,
        "status": status,
        "parts": parts,
        "colors": colors,
        "by_machine": by_machine,
        "since_buckets": since_buckets,
        # When the folded half was built — the stalest row in the set, so "as
        # of" is never a claim the freshest member can't back up.
        "watermark": min((r.computed_at for r in rows if r.computed_at), default=None),
    }


def _live_pieces_since(db: Session, since_buckets: dict[datetime | None, list[Any]]) -> int:
    """Pieces this fleet reported since each machine's cache row was built.

    The only query analytics runs against machine_pieces, and normally it is a
    single index range on (machine_id, created_at) covering rows newer than the
    last refresh — minutes of data, not the table. One query per distinct
    watermark, and a fleet refreshed in one pass shares one.

    ``created_at`` (when hive stored the row) and not ``seen_at`` (when the
    machine saw the piece): a machine that has been offline uploads a backlog
    stamped days ago, and those pieces have to count when they arrive rather
    than an hour later.

    A machine with no cached row yet counts from the beginning, which is the
    right answer — its cached contribution is zero — and is bounded by what
    that one machine has ever sorted. It self-corrects on the next worker pass.

    The count can lag by the few seconds a refresh takes (rows landing mid-pass
    are in neither half until the following one). That direction is chosen: the
    counter creeps up to the truth instead of overshooting and visibly falling
    back, which is what stamping the watermark before the pass would do.
    """
    total = 0
    for since, ids in since_buckets.items():
        if not ids:
            continue
        query = (
            db.query(func.count())
            .select_from(MachinePiece)
            .filter(MachinePiece.machine_id.in_(ids))
        )
        if since is not None:
            query = query.filter(MachinePiece.created_at >= since)
        total += int(query.scalar() or 0)
    return total


def _ranked(counts: dict[str, list[Any]], id_key: str, name_key: str, limit: int) -> list[dict[str, Any]]:
    ranked = sorted(counts.items(), key=lambda kv: kv[1][0], reverse=True)[:limit]
    return [{id_key: key, name_key: entry[1], "value": entry[0]} for key, entry in ranked]


def get_analytics(db: Session, machine_ids: list[Any]) -> dict[str, Any]:
    """Totals, time-series and distributions for a set of machines.

    Reads machine_stats_cache and machine_daily_stats and folds them. The only
    thing it asks of machine_pieces is an indexed count of rows newer than the
    cache, so the cost is flat in the size of that table — which is the whole
    point, because it grew from 51k rows in June to 354k in August and the old
    version's cost grew with it.
    """
    if not machine_ids:
        return {
            "totals": {
                "machines": 0, "pieces_seen": 0, "distributed": 0, "classified": 0,
                "unique_parts": 0, "unique_colors": 0, "active_seconds": 0.0,
                "overall_ppm": 0.0, "capacity_recent": 0.0,
                "first_day": None, "last_day": None,
            },
            "timeseries": [],
            "distributions": {"by_machine": [], "by_status": [], "top_parts": [], "top_colors": [], "top_categories": []},
            "fresh_as_of": None,
        }

    folded = _fold_cached(db, machine_ids)
    series = get_timeseries(db, machine_ids)
    counts = folded["totals"]

    # Live top-up. Only pieces_seen gets it: it is the number people watch
    # climb, and the rest (which part, which colour, whether it was
    # distributed) is not knowable without reading the rows themselves.
    pieces_seen = counts["pieces_seen"] + _live_pieces_since(db, folded["since_buckets"])

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

    top_colors = _ranked(folded["colors"], "color_id", "color_name", 15)
    rgb_by_bl_id = _bricklink_rgb()
    for entry in top_colors:
        try:
            entry["rgb"] = rgb_by_bl_id.get(int(entry["color_id"]))
        except (TypeError, ValueError):
            entry["rgb"] = None

    name_by_id = {
        str(mid): name
        for mid, name in db.query(Machine.id, Machine.name).filter(Machine.id.in_(machine_ids)).all()
    }

    return {
        "totals": {
            "machines": counts["machines"],
            "pieces_seen": pieces_seen,
            "distributed": counts["distributed"],
            "classified": counts["classified"],
            "unique_parts": len(folded["parts"]),
            "unique_colors": len(folded["colors"]),
            "active_seconds": round(active_seconds, 1),
            "overall_ppm": round(counts["distributed"] * 60.0 / active_seconds, 3) if active_seconds > 0 else 0.0,
            "capacity_recent": series[-1]["capacity_per_day"] if series else 0.0,
            "first_day": day_bounds[0].isoformat() if day_bounds[0] else None,
            "last_day": day_bounds[1].isoformat() if day_bounds[1] else None,
        },
        "timeseries": series,
        "distributions": {
            # Only meaningful for a set; one machine's breakdown by machine is itself.
            "by_machine": [
                {"machine_id": mid, "label": name_by_id.get(mid, "?"), "value": value}
                for mid, value in sorted(folded["by_machine"], key=lambda kv: kv[1], reverse=True)
            ] if len(machine_ids) > 1 else [],
            "by_status": [{"label": label, "value": value} for label, value in folded["status"].items()],
            "top_parts": _ranked(folded["parts"], "part_id", "part_name", 15),
            "top_colors": top_colors,
            # Every part is counted, not just the top fifteen, so the shares are
            # honest; the catalog then maps part -> category.
            "top_categories": _category_distribution(
                [(key, entry[0]) for key, entry in folded["parts"].items()], limit=15
            ),
        },
        # When the folded half was built. The caller can say "as of" rather than
        # implying every number in the payload is to-the-second.
        "fresh_as_of": folded["watermark"].isoformat() if folded["watermark"] else None,
    }
