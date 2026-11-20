from __future__ import annotations

import re
import threading
import time
from typing import Any, Optional

import hive_metadata_cache
import lot_sets
import sorting_runs

# What a lot holds, for the dashboard's Lot tab: how many pieces, how many of
# them identified, and those by color, by type and by part. Counted as the lot
# counts (its runs that add to it; another pass over its pieces is left out).
#
# The dashboard asks every few seconds and a lot can hold tens of thousands of
# pieces, so an answer is kept for a few seconds, and a run that has ended is
# counted once and kept for minutes: only the current run is read each time.
# A correction to a piece of an ended run shows after that. Read on an API
# thread, never the control loop's.

_SUMMARY_TTL_S = 5.0
_ENDED_RUN_TTL_S = 300.0
_TOP_PARTS = 12

_lock = threading.Lock()
_summaries: dict[str, tuple[float, dict[str, Any]]] = {}
# (run id, started_at, ended_at) -> (counted at, runCounts' answer)
_ended_runs: dict[tuple[str, float, float], tuple[float, tuple[int, list]]] = {}
# part id -> BrickLink category, which never changes.
_categories: dict[str, str] = {}

_FIRST_WORD = re.compile(r"[^\s,\d]+")


def _runCounts(run: dict[str, Any], now: float) -> tuple[int, list]:
    if run["ended_at"] is None:
        return sorting_runs.runCounts(run)
    key = (run["id"], run["started_at"], run["ended_at"])
    hit = _ended_runs.get(key)
    if hit is None or now - hit[0] >= _ENDED_RUN_TTL_S:
        for stale in [k for k, v in _ended_runs.items() if now - v[0] >= _ENDED_RUN_TTL_S]:
            del _ended_runs[stale]
        hit = _ended_runs[key] = (now, sorting_runs.runCounts(run))
    return hit[1]


def _partType(category: Optional[str], name: Optional[str]) -> str:
    """A part's kind, as coarse as BrickLink's top categories: "Plate" for the
    category "Plate, Modified", or, with no category cached, the first word of
    its name ("Slope 45 2 x 1" is a "Slope")."""
    head = (category or "").split(",")[0].strip()
    if head:
        return head
    word = _FIRST_WORD.match((name or "").strip())
    return word.group() if word else "Other"


def _hex(rgb: Any) -> Optional[str]:
    text = str(rgb or "").strip().lstrip("#")
    return f"#{text.upper()}" if re.fullmatch(r"[0-9a-fA-F]{6}", text) else None


def _build(lot_id: str, now: float) -> dict[str, Any]:
    name, runs = sorting_runs.lotAddingRuns(lot_id)
    pieces = 0
    by_part: dict[str, list] = {}  # part id -> [name, count]
    by_color: dict[str, list] = {}  # color id ('' for none) -> [name, count]
    for run in runs:
        run_pieces, parts = _runCounts(run, now)
        pieces += run_pieces
        for part_id, color, part_name, color_name, n in parts:
            part = by_part.setdefault(part_id, [part_name, 0])
            part[0] = part[0] or part_name
            part[1] += n
            color_id = "" if color == "any_color" else color
            tally = by_color.setdefault(color_id, [color_name, 0])
            tally[0] = tally[0] or color_name
            tally[1] += n

    unknown = [part_id for part_id in by_part if part_id not in _categories]
    if unknown:
        _categories.update(hive_metadata_cache.get_cached_bricklink_categories(unknown))
    by_type: dict[str, int] = {}
    for part_id, (part_name, n) in by_part.items():
        kind = _partType(_categories.get(part_id), part_name)
        by_type[kind] = by_type.get(kind, 0) + n

    # A corrected piece is counted under its true color, whose name the record
    # does not carry: the palette's name wins when it has the color.
    palette = {str(c.get("id")): c for c in hive_metadata_cache.get_cached_palette() or []}
    colors = []
    for color_id, (color_name, n) in by_color.items():
        known = palette.get(color_id, {})
        colors.append(
            {
                "color_id": color_id or None,
                "color_name": (known.get("name") or color_name) if color_id else None,
                "hex": _hex(known.get("rgb")),
                "count": n,
            }
        )
    colors.sort(key=lambda c: -c["count"])
    top = sorted(by_part.items(), key=lambda item: -item[1][1])[:_TOP_PARTS]
    return {
        "lot_id": lot_id,
        "name": name,
        "pieces": pieces,
        "identified": sum(n for _, n in by_part.values()),
        "distinct_parts": len(by_part),
        "colors": colors,
        "types": [
            {"type": kind, "count": n} for kind, n in sorted(by_type.items(), key=lambda item: -item[1])
        ],
        "top_parts": [
            {"part_id": part_id, "part_name": part_name, "count": n} for part_id, (part_name, n) in top
        ],
        "sets": lot_sets.candidateSets(lot_id),
        "computed_at": now,
    }


def lotSummary(lot_id: str) -> dict[str, Any]:
    """The lot's summary, at most a few seconds old. Raises
    sorting_runs.RunError for an unknown lot."""
    now = time.time()
    # One at a time: a second asker waits for the first's answer.
    with _lock:
        hit = _summaries.get(lot_id)
        if hit is not None and now - hit[0] < _SUMMARY_TTL_S:
            return hit[1]
        summary = _build(lot_id, now)
        for stale in [k for k, v in _summaries.items() if now - v[0] >= _SUMMARY_TTL_S]:
            del _summaries[stale]
        _summaries[lot_id] = (now, summary)
        return summary
