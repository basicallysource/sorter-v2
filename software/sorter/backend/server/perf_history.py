"""In-memory performance time-series for the performance dashboard.

The main loop broadcasts a full ``runtime_stats`` snapshot once per second.
That snapshot is cumulative (its ``perf_ms`` histograms are ring buffers over
the whole run), so on its own it can't answer "how did the machine behave over
the last 5 minutes vs. the last hour." This module keeps a compact, derived row
per snapshot in a bounded ring buffer so the dashboard can show real time
windows that survive page reloads.

Lives in the SERVER process and is fed from ``shared_state`` whenever a
runtime_stats snapshot lands. Recording is idempotent per snapshot
``updated_at`` so it doesn't matter how many code paths forward the same
snapshot.

Everything here is plain numbers translated into dashboard-friendly shapes —
the frontend renders these directly without re-deriving from raw DB-style keys.
"""

from __future__ import annotations

import re
from collections import deque
from typing import Any, Optional

# ~65 min at one snapshot/second. Each row is small (a handful of floats plus a
# counts dict), so this is ~1-2 MB of RAM.
PERF_HISTORY_MAX_ROWS = 3900

# perception.<source_id>.<metric> — source ids never contain a dot, and the
# metric suffix is anchored, so the greedy group only swallows the source id.
_PERCEPTION_RE = re.compile(
    r"^perception\.(.+)\.(infer_ms|cycle_ms|attribute_ms|frame_age_ms)$"
)

_history: deque[dict[str, Any]] = deque(maxlen=PERF_HISTORY_MAX_ROWS)
_last_recorded_updated_at: Optional[float] = None


def _num(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) else None


def _med(perf_ms: dict[str, Any], key: str) -> Optional[float]:
    """Representative latency for a metric: median if present, else average."""
    entry = perf_ms.get(key)
    if not isinstance(entry, dict):
        return None
    value = entry.get("med_ms")
    if value is None:
        value = entry.get("avg_ms")
    return _num(value)


def extractRow(snapshot: dict[str, Any], captured_at: float) -> dict[str, Any]:
    perf_ms = snapshot.get("perf_ms")
    perf_ms = perf_ms if isinstance(perf_ms, dict) else {}
    counts = snapshot.get("perf_total_counts")
    counts = counts if isinstance(counts, dict) else {}
    throughput = snapshot.get("throughput")
    throughput = throughput if isinstance(throughput, dict) else {}
    snap_counts = snapshot.get("counts")
    snap_counts = snap_counts if isinstance(snap_counts, dict) else {}

    cameras: dict[str, dict[str, Optional[float]]] = {}
    for key in perf_ms:
        match = _PERCEPTION_RE.match(key)
        if not match:
            continue
        source_id, metric = match.group(1), match.group(2)
        cameras.setdefault(source_id, {})[metric] = _med(perf_ms, key)

    # Cumulative call-counts per metric key are the true event counters (the
    # perf_ms sample lists are capped, so their sample_count saturates — these
    # don't). Rates over a window come from differencing two rows' counters.
    row_counts: dict[str, Optional[int]] = {
        "loop": counts.get("main.loop.interval_ms"),
        "decision": counts.get("coordinator.step.classification_ms"),
        "distribution": counts.get("coordinator.step.distribution_ms"),
        "feeder": counts.get("coordinator.step.feeder_ms"),
    }
    for source_id in cameras:
        row_counts[f"infer.{source_id}"] = counts.get(
            f"perception.{source_id}.infer_ms"
        )

    return {
        "t": captured_at,
        "lifecycle_state": snapshot.get("lifecycle_state"),
        "is_running": bool(snapshot.get("is_running")),
        # control loop / decision timing (ms)
        "loop_interval_ms": _med(perf_ms, "main.loop.interval_ms"),
        "controller_step_ms": _med(perf_ms, "main.loop.controller_step_ms"),
        "coord_total_ms": _med(perf_ms, "coordinator.step.total_ms"),
        "coord_cpu_ms": _med(perf_ms, "coordinator.step.cpu_ms"),
        "coord_gil_stall_ms": _med(perf_ms, "coordinator.step.gil_stall_ms"),
        "distribution_ms": _med(perf_ms, "coordinator.step.distribution_ms"),
        "classification_ms": _med(perf_ms, "coordinator.step.classification_ms"),
        "feeder_ms": _med(perf_ms, "coordinator.step.feeder_ms"),
        # the headline "how stale is the data we decide on" metric
        "decision_frame_age_ms": _med(perf_ms, "classification.decision_frame_age_ms"),
        "perception_read_ms": _med(
            perf_ms, "classification.rev01.idle.perception_read_ms"
        ),
        "cameras": cameras,
        "counts": row_counts,
        # throughput
        "rolling_5min_ppm": _num(throughput.get("rolling_5min_ppm")),
        "overall_ppm": _num(throughput.get("overall_ppm")),
        "running_time_s": _num(throughput.get("running_time_s")),
        "pieces_seen": snap_counts.get("pieces_seen"),
        "distributed": snap_counts.get("distributed"),
    }


def record(snapshot: dict[str, Any], captured_at: float) -> None:
    global _last_recorded_updated_at
    if not isinstance(snapshot, dict):
        return
    updated_at = snapshot.get("updated_at")
    if updated_at is not None and updated_at == _last_recorded_updated_at:
        return
    _last_recorded_updated_at = updated_at
    try:
        _history.append(extractRow(snapshot, captured_at))
    except Exception:
        pass


def window(window_s: float, now: float) -> list[dict[str, Any]]:
    cutoff = now - max(0.0, window_s)
    return [row for row in _history if row["t"] >= cutoff]


def _rate(rows: list[dict[str, Any]], count_key: str) -> Optional[float]:
    """Events/sec for a cumulative counter across the window: take the first and
    last rows that carry the counter and divide the delta by the time span."""
    first: Optional[dict[str, Any]] = None
    last: Optional[dict[str, Any]] = None
    for row in rows:
        value = row.get("counts", {}).get(count_key)
        if not isinstance(value, (int, float)):
            continue
        if first is None:
            first = row
        last = row
    if first is None or last is None or first is last:
        return None
    dt = last["t"] - first["t"]
    if dt <= 0:
        return None
    delta = last["counts"][count_key] - first["counts"][count_key]
    # A counter reset (process restart mid-window) shows up as a negative delta.
    if delta < 0:
        return None
    return delta / dt


def computeRates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Window-summary rates (Hz) plus the most recent latency readings."""
    if not rows:
        return {"hz": {}, "current": {}, "span_s": 0.0, "sample_count": 0}

    camera_keys: set[str] = set()
    for row in rows:
        for key in row.get("counts", {}):
            if key.startswith("infer."):
                camera_keys.add(key)

    hz: dict[str, Optional[float]] = {
        "loop": _rate(rows, "loop"),
        "decision": _rate(rows, "decision"),
        "distribution": _rate(rows, "distribution"),
        "feeder": _rate(rows, "feeder"),
    }
    cameras_hz: dict[str, Optional[float]] = {}
    for key in camera_keys:
        cameras_hz[key[len("infer."):]] = _rate(rows, key)

    latest = rows[-1]
    return {
        "hz": hz,
        "cameras_hz": cameras_hz,
        "current": {
            "loop_interval_ms": latest.get("loop_interval_ms"),
            "controller_step_ms": latest.get("controller_step_ms"),
            "decision_frame_age_ms": latest.get("decision_frame_age_ms"),
            "coord_total_ms": latest.get("coord_total_ms"),
            "coord_gil_stall_ms": latest.get("coord_gil_stall_ms"),
            "distribution_ms": latest.get("distribution_ms"),
            "classification_ms": latest.get("classification_ms"),
            "feeder_ms": latest.get("feeder_ms"),
            "cameras": latest.get("cameras", {}),
            "rolling_5min_ppm": latest.get("rolling_5min_ppm"),
            "lifecycle_state": latest.get("lifecycle_state"),
            "is_running": latest.get("is_running"),
        },
        "span_s": rows[-1]["t"] - rows[0]["t"],
        "sample_count": len(rows),
    }
