"""Fleet records: who is fastest, who got somewhere first, and what was found last.

The roster says how much each machine has sorted. A leaderboard wants more
than that, and every extra answer here costs a scan the roster cannot afford:

* **Speed** over the trailing 24 hours and 30 days, per machine, and the
  day's double feeds (pieces the machine dropped together and could not tell
  apart). Pieces per minute of ACTIVE time — the same rule as `machine_stats` and the daily
  table, gaps longer than `ACTIVE_GAP_IDLE_S` are a machine between sessions
  and do not count against it. Served as the three raw sums rather than a
  rate, so a consumer can set its own floor on how much running time a rate
  needs before it is worth ranking.
* **Fleet milestones**: which machine processed the fleet's Nth piece, for
  each rung of `FLEET_MILESTONES` the fleet has passed. "Processed" is every
  piece a machine looked at, sorted into a bin or not — the same population
  as `pieces_seen` — ordered by when the machine saw it.
* **Machine milestones**: the first machine to reach each of
  `MACHINE_MILESTONES` on its own, and when.
* **Newest finds**: the most recent parts, colors, and parts in a color the
  fleet had never seen before, with the machine that saw each one first.

**Nothing here runs on a request path.** The finds are a grouped scan of
machine_pieces and a milestone is a sort over it; a worker computes and
publishes, `latest()` reads. Same trade as `fleet_mass`: a record that is a
quarter of an hour stale is still the record.

**A milestone can move, and that is why it is memoised.** Pieces are ordered
by `seen_at`, and a machine that was offline uploads its backlog later with
the times it really saw them, which can put somebody else's piece ahead of
the one that held the record. Each milestone is computed once per process and
then kept: an answer that changes after people have been told it is worse than
one that was right as of when it was first given.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.machine import Machine
from app.models.machine_daily_stats import MachineDailyStats
from app.models.machine_piece import MachinePiece
from app.services.machine_stats import ACTIVE_GAP_IDLE_S
from app.services.periodic import PeriodicWorker

logger = logging.getLogger(__name__)

# The fleet's own rungs: a few early ones so a young fleet has history, then
# every million, generated up to the next one past the current total.
FLEET_MILESTONES = (100_000, 250_000, 500_000)
FLEET_MILESTONE_STEP = 1_000_000

# One machine on its own.
MACHINE_MILESTONES = (100_000, 250_000, 500_000, 1_000_000)

# The classification status a machine records when more than one piece came
# down at once and it could not tell them apart.
DOUBLE_FEED_STATUS = "multi_drop_fail"

# How many newest parts and colors are served.
NEWEST = 5

# A color id that is not a color: the bucket a profile sorts into when it
# does not care about color.
_NOT_A_COLOR = ("", "any_color")

_latest: dict[str, Any] | None = None
_lock = threading.Lock()

# Milestones already answered, by (kind, rung). See the module docstring.
_memo: dict[tuple[str, int], dict[str, Any]] = {}


def latest() -> dict[str, Any]:
    """The last published answer. Never computes; empty with a null
    `computed_at` until the first pass lands."""
    with _lock:
        if _latest is None:
            return {**_empty(), "computed_at": None}
        return _latest


def refresh(db: Session, machine_ids: list) -> dict[str, Any]:
    """Recompute and publish. The worker's job, and what a test drives directly."""
    computed = _compute(db, machine_ids, datetime.now(timezone.utc))
    computed["computed_at"] = datetime.now(timezone.utc).isoformat()
    with _lock:
        global _latest
        _latest = computed
    return computed


def reset_cache() -> None:
    """Forget what was published and every memoised milestone. For tests."""
    global _latest
    with _lock:
        _latest = None
        _memo.clear()


def _empty() -> dict[str, Any]:
    return {
        "speed": [],
        "fleet_milestones": [],
        "next_fleet_milestone": FLEET_MILESTONES[0],
        "fleet_pieces": 0,
        "machine_milestones": [],
        "newest_parts": [],
        "newest_colors": [],
        "newest_combos": [],
        "distinct_parts": 0,
        "distinct_colors": 0,
        "distinct_combos": 0,
    }


def _compute(db: Session, machine_ids: list, now: datetime) -> dict[str, Any]:
    if not machine_ids:
        return _empty()
    # Pieces with a time, per machine: the population both kinds of milestone
    # are counted in, read once.
    counts = {
        mid: int(n)
        for mid, n in db.query(MachinePiece.machine_id, func.count())
        .filter(MachinePiece.machine_id.in_(machine_ids))
        .filter(MachinePiece.seen_at.isnot(None))
        .group_by(MachinePiece.machine_id)
        .all()
    }
    total = sum(counts.values())
    passed, upcoming = _fleet_rungs(total)
    parts, distinct_parts = _newest(db, machine_ids, MachinePiece.part_id)
    colors, distinct_colors = _newest(db, machine_ids, MachinePiece.color_id)
    combos, distinct_combos = _newest(db, machine_ids, MachinePiece.part_id, MachinePiece.color_id)
    return {
        "speed": _speed(db, machine_ids, now),
        "fleet_milestones": _fleet_milestones(db, machine_ids, passed),
        "next_fleet_milestone": upcoming,
        "fleet_pieces": total,
        "machine_milestones": _machine_milestones(db, counts),
        "newest_parts": _with_part_images(parts),
        "newest_colors": _with_swatches(colors),
        "newest_combos": _with_swatches(_with_part_images(combos)),
        "distinct_parts": distinct_parts,
        "distinct_colors": distinct_colors,
        "distinct_combos": distinct_combos,
    }


def _fleet_rungs(total: int) -> tuple[list[int], int]:
    """The rungs at or below `total`, and the first one above it."""
    rungs = list(FLEET_MILESTONES)
    step = FLEET_MILESTONE_STEP
    while rungs[-1] <= total:
        rungs.append((rungs[-1] // step + 1) * step)
    return [r for r in rungs if r <= total], next(r for r in rungs if r > total)


def _speed(db: Session, machine_ids: list, now: datetime) -> list[dict[str, Any]]:
    """Per machine, the pieces, distributed pieces and active seconds in each window.

    The day is a true trailing 24 hours, walked off the (machine_id, seen_at)
    index: a day's worth of rows is small, and a calendar day would rank
    everybody at zero just after midnight. The month comes from the daily table
    the analytics worker keeps, the last 30 UTC days including today: walking a
    month of pieces here would be the full scan this worker is trying to keep
    to one per pass.
    """
    out: dict[str, dict[str, Any]] = {}

    def slot(mid: Any) -> dict[str, Any]:
        return out.setdefault(
            str(mid),
            {
                "machine_id": str(mid),
                "day": {"pieces": 0, "distributed": 0, "double_feeds": 0, "active_seconds": 0.0},
                "month": {"pieces": 0, "distributed": 0, "active_seconds": 0.0},
            },
        )

    rows = (
        db.query(
            MachinePiece.machine_id,
            MachinePiece.seen_at,
            MachinePiece.bin_x,
            MachinePiece.classification_status,
        )
        .filter(MachinePiece.machine_id.in_(machine_ids))
        .filter(MachinePiece.seen_at >= now - timedelta(hours=24))
        .order_by(MachinePiece.machine_id, MachinePiece.seen_at, MachinePiece.local_id)
        .all()
    )
    prev_mid = prev_seen = None
    for mid, seen_at, bin_x, status in rows:
        day = slot(mid)["day"]
        day["pieces"] += 1
        if bin_x is not None:
            day["distributed"] += 1
        if status == DOUBLE_FEED_STATUS:
            day["double_feeds"] += 1
        if prev_mid == mid and prev_seen is not None:
            gap = (seen_at - prev_seen).total_seconds()
            if 0 < gap <= ACTIVE_GAP_IDLE_S:
                day["active_seconds"] += gap
        prev_mid, prev_seen = mid, seen_at

    since = (now - timedelta(days=29)).date()
    for mid, pieces, distributed, active in (
        db.query(
            MachineDailyStats.machine_id,
            func.sum(MachineDailyStats.pieces_seen),
            func.sum(MachineDailyStats.distributed),
            func.sum(MachineDailyStats.active_seconds),
        )
        .filter(MachineDailyStats.machine_id.in_(machine_ids))
        .filter(MachineDailyStats.day >= since)
        .group_by(MachineDailyStats.machine_id)
        .all()
    ):
        month = slot(mid)["month"]
        month["pieces"] = int(pieces or 0)
        month["distributed"] = int(distributed or 0)
        month["active_seconds"] = float(active or 0.0)

    for entry in out.values():
        for window in ("day", "month"):
            entry[window]["active_seconds"] = round(entry[window]["active_seconds"], 1)
    return list(out.values())


def _fleet_milestones(db: Session, machine_ids: list, passed: list[int]) -> list[dict[str, Any]]:
    """Which machine processed the fleet's Nth piece, for every rung passed.

    One window over every piece answers all the missing rungs at once, and it
    only runs when a rung has not been answered yet in this process.
    """
    missing = [n for n in passed if ("fleet", n) not in _memo]
    if missing:
        rn = (
            func.row_number()
            .over(order_by=(MachinePiece.seen_at, MachinePiece.machine_id, MachinePiece.local_id))
            .label("rn")
        )
        ranked = (
            db.query(
                MachinePiece.machine_id,
                MachinePiece.seen_at,
                MachinePiece.part_id,
                MachinePiece.part_name,
                MachinePiece.color_name,
                rn,
            )
            .filter(MachinePiece.machine_id.in_(machine_ids))
            .filter(MachinePiece.seen_at.isnot(None))
            .subquery()
        )
        for row in db.query(ranked).filter(ranked.c.rn.in_(missing)).all():
            _memo[("fleet", int(row.rn))] = {
                "pieces": int(row.rn),
                "machine_id": str(row.machine_id),
                "seen_at": row.seen_at.isoformat(),
                "part_id": row.part_id,
                "part_name": row.part_name,
                "color_name": row.color_name,
            }
    return [_memo[("fleet", n)] for n in passed if ("fleet", n) in _memo]


def _machine_milestones(db: Session, counts: dict) -> list[dict[str, Any]]:
    """The first machine to reach each rung on its own, for every rung reached.

    A machine's Nth piece is an offset walk down its (machine_id, seen_at)
    index, so only machines whose count says they got there are asked, and
    each answer is memoised.
    """
    out = []
    for rung in MACHINE_MILESTONES:
        reached = []
        for mid, n in counts.items():
            if n < rung:
                continue
            key = (f"machine:{mid}", rung)
            if key not in _memo:
                seen_at = (
                    db.query(MachinePiece.seen_at)
                    .filter(MachinePiece.machine_id == mid)
                    .filter(MachinePiece.seen_at.isnot(None))
                    .order_by(MachinePiece.seen_at, MachinePiece.local_id)
                    .offset(rung - 1)
                    .limit(1)
                    .scalar()
                )
                _memo[key] = {"pieces": rung, "machine_id": str(mid), "reached_at": seen_at.isoformat()}
            reached.append(_memo[key])
        if reached:
            out.append(min(reached, key=lambda r: r["reached_at"]))
    return out


def _newest(db: Session, machine_ids: list, *columns) -> tuple[list[dict[str, Any]], int]:
    """The NEWEST values of `columns` (one column, or a combination such as a
    part in a color) the fleet ever saw for the first time, newest first, each
    with the piece that first showed it; and how many distinct values there are.

    Classified pieces only: an unidentified piece has no part to be new, and a
    guess the machine itself would not stand behind is not a find.
    """
    labels = [f"v{i}" for i in range(len(columns))]
    query = db.query(
        *(c.label(name) for c, name in zip(columns, labels)),
        func.min(MachinePiece.seen_at).label("first_seen"),
    )
    query = (
        query.filter(MachinePiece.machine_id.in_(machine_ids))
        .filter(MachinePiece.classification_status == "classified")
        .filter(MachinePiece.seen_at.isnot(None))
    )
    for c in columns:
        query = query.filter(c.isnot(None)).filter(c.notin_(_NOT_A_COLOR))
    firsts = query.group_by(*columns).subquery()
    distinct = int(db.query(func.count()).select_from(firsts).scalar() or 0)
    newest = (
        db.query(*(firsts.c[name] for name in labels), firsts.c.first_seen)
        .order_by(firsts.c.first_seen.desc(), *(firsts.c[name] for name in labels))
        .limit(NEWEST)
        .all()
    )
    out = []
    for i, row in enumerate(newest):
        *values, first_seen = row
        piece = (
            db.query(MachinePiece)
            .filter(MachinePiece.machine_id.in_(machine_ids))
            .filter(MachinePiece.classification_status == "classified")
            .filter(*(c == v for c, v in zip(columns, values)))
            .filter(MachinePiece.seen_at == first_seen)
            .order_by(MachinePiece.machine_id, MachinePiece.local_id)
            .first()
        )
        if piece is None:
            continue
        out.append(
            {
                # The how-many-th distinct one this was: the newest is the last.
                "ordinal": distinct - i,
                "machine_id": str(piece.machine_id),
                "first_seen_at": first_seen.isoformat(),
                "part_id": piece.part_id,
                "part_name": piece.part_name,
                "color_id": piece.color_id,
                "color_name": piece.color_name,
            }
        )
    return out, distinct


def _with_part_images(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach the catalog's picture of each part, where it has one."""
    try:
        from app.services.profile_catalog import get_profile_catalog_service

        catalog = get_profile_catalog_service()
    except Exception:
        catalog = None
    for p in parts:
        p["part_img_url"] = None
        if catalog is None or not p["part_id"]:
            continue
        try:
            row = catalog.piece_metadata(p["part_id"]) or {}
        except Exception:
            row = {}
        p["part_img_url"] = row.get("part_img_url")
        p["part_name"] = p["part_name"] or row.get("name")
    return parts


def _with_swatches(colors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach each color's BrickLink swatch hex, the same lookup /stats uses."""
    from app.services.analytics import bricklink_rgb

    rgb = bricklink_rgb()
    for c in colors:
        try:
            c["rgb"] = rgb.get(int(c["color_id"]))
        except (TypeError, ValueError):
            c["rgb"] = None
    return colors


def _refresh_pass() -> dict[str, Any]:
    """One pass over every non-archived machine."""
    db = SessionLocal()
    try:
        ids = [mid for (mid,) in db.query(Machine.id).filter(Machine.archived_at.is_(None)).all()]
        answer = refresh(db, ids)
        return {
            "fleet_pieces": answer["fleet_pieces"],
            "fleet_milestones": len(answer["fleet_milestones"]),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


_WORKER: PeriodicWorker | None = None
_WORKER_LOCK = threading.Lock()


def get_fleet_records_worker() -> PeriodicWorker:
    global _WORKER
    if _WORKER is None:
        with _WORKER_LOCK:
            if _WORKER is None:
                _WORKER = PeriodicWorker(
                    "fleet-records-worker",
                    _refresh_pass,
                    lambda: max(60.0, float(settings.FLEET_RECORDS_REFRESH_INTERVAL_MINUTES) * 60.0),
                    run_at_start=True,
                )
    return _WORKER
