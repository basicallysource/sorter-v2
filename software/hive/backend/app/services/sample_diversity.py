"""The samples diversity overview, added up from a table the stats worker keeps.

The overview (GET /api/samples/diversity) shows, per capture reason and
source, how many samples show 0, 1, ... 13+ pieces against a target per
bucket, how many machines contributed, and how that coverage grew. Counting it
per request read every sample and fetched each one's upload time (650k rows by
October 2026). Now the stats worker keeps one row per machine, week, capture
reason and source (``sample_diversity_weekly``, ``refresh``) and a request adds
up the rows of the machines it may see (``overview``): a few thousand narrow
rows, whatever the size of the samples table.

The coverage trend is drawn from the weekly rows: within a row, its samples are
taken to be spread evenly between its first and last upload, which is as fine
as a 24-point line over months can show anyway.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.sample import Sample
from app.models.sample_diversity import SampleDiversityWeek

BUCKET_KEYS = ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9-12", "13+")
TARGET_PER_BUCKET = 50
TREND_POINTS = 24
# How many distinct machines should contribute samples for a (capture reason,
# source) before its coverage stops being penalised: a piece seen by one rig
# only overfits the model to that rig's lighting, optics and wear.
MACHINE_TARGET = 3

_TARGETS_DEFAULT: dict[str, int] = {k: TARGET_PER_BUCKET for k in BUCKET_KEYS}
# classification_channel only sees single pieces under the camera: above 8 is a
# counting error and 6-8 are rare, so 9+ is out of scope and 6-8 weigh less.
_TARGETS_PER_ROLE: dict[str, dict[str, int]] = {
    "classification_channel": {
        "0": 50, "1": 50, "2": 50, "3": 50, "4": 50, "5": 50,
        "6": 25, "7": 25, "8": 25,
        "9-12": 0, "13+": 0,
    },
}


def targets_for_role(source_role: str | None) -> dict[str, int]:
    return _TARGETS_PER_ROLE.get(source_role or "", _TARGETS_DEFAULT)


def bucket_of(count: int | None) -> int:
    """The bucket index of a piece count; len(BUCKET_KEYS) for no count."""
    if count is None:
        return len(BUCKET_KEYS)
    if 0 <= count <= 8:
        return count
    return 9 if count <= 12 else 10


# --- Kept by the stats worker -------------------------------------------------------

_REFRESH_SQL = """
INSERT INTO sample_diversity_weekly (machine_id, week, capture_reason, source_role, buckets, samples,
                                     score_sum, scored, first_at, last_at, computed_at)
SELECT machine_id, (date_trunc('week', uploaded_at AT TIME ZONE 'UTC'))::date, capture_reason,
       coalesce(source_role, 'unknown'),
       jsonb_build_array(
           count(*) FILTER (WHERE detection_count = 0), count(*) FILTER (WHERE detection_count = 1),
           count(*) FILTER (WHERE detection_count = 2), count(*) FILTER (WHERE detection_count = 3),
           count(*) FILTER (WHERE detection_count = 4), count(*) FILTER (WHERE detection_count = 5),
           count(*) FILTER (WHERE detection_count = 6), count(*) FILTER (WHERE detection_count = 7),
           count(*) FILTER (WHERE detection_count = 8),
           count(*) FILTER (WHERE detection_count <= 12 AND detection_count NOT BETWEEN 0 AND 8),
           count(*) FILTER (WHERE detection_count > 12),
           count(*) FILTER (WHERE detection_count IS NULL)),
       count(*), coalesce(sum(detection_score), 0), count(detection_score), min(uploaded_at), max(uploaded_at),
       :now
FROM samples
WHERE capture_reason IS NOT NULL AND archived_at IS NULL
GROUP BY 1, 2, 3, 4
"""


def refresh(db: Session) -> int:
    """Rebuild the weekly rows from the samples table (the stats worker's
    pass). Returns rows written; commits."""
    now = datetime.now(timezone.utc)
    db.query(SampleDiversityWeek).delete(synchronize_session=False)
    if db.get_bind().dialect.name == "postgresql":
        written = db.execute(text(_REFRESH_SQL), {"now": now}).rowcount or 0
    else:
        written = _refresh_python(db, now)
    db.commit()
    return written


def _refresh_python(db: Session, now: datetime) -> int:
    """The same rows, folded in Python, for databases without date_trunc (the tests)."""
    rows: dict[tuple, dict[str, Any]] = {}
    for machine_id, reason, role, count, score, uploaded_at in db.query(
        Sample.machine_id,
        Sample.capture_reason,
        Sample.source_role,
        Sample.detection_count,
        Sample.detection_score,
        Sample.uploaded_at,
    ).filter(Sample.capture_reason.isnot(None), Sample.archived_at.is_(None)):
        uploaded_at = _utc(uploaded_at)
        week = (uploaded_at - timedelta(days=uploaded_at.weekday())).date()
        row = rows.setdefault(
            (machine_id, week, reason, role or "unknown"),
            {"buckets": [0] * (len(BUCKET_KEYS) + 1), "samples": 0, "score_sum": 0.0, "scored": 0,
             "first_at": uploaded_at, "last_at": uploaded_at},
        )
        row["buckets"][bucket_of(count)] += 1
        row["samples"] += 1
        if score is not None:
            row["score_sum"] += float(score)
            row["scored"] += 1
        row["first_at"] = min(row["first_at"], uploaded_at)
        row["last_at"] = max(row["last_at"], uploaded_at)
    for (machine_id, week, reason, role), values in rows.items():
        db.add(SampleDiversityWeek(
            machine_id=machine_id, week=week, capture_reason=reason, source_role=role, computed_at=now, **values
        ))
    return len(rows)


# --- Read by the request ------------------------------------------------------------------


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _bucket_fills(buckets: dict[str, float], targets: dict[str, int]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for k in BUCKET_KEYS:
        t = targets.get(k, 0)
        out[k] = None if t <= 0 else min(buckets[k], t) / t  # None: not applicable to this source
    return out


def _avg_fills(per_role: list[dict[str, float | None]]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for k in BUCKET_KEYS:
        relevant = [rf[k] for rf in per_role if rf[k] is not None]
        out[k] = sum(relevant) / len(relevant) if relevant else None
    return out


def _coverage(fills: dict[str, float | None]) -> float:
    relevant = [v for v in fills.values() if v is not None]
    return sum(relevant) / len(relevant) if relevant else 0.0


def _machine_factor(machine_count: int) -> float:
    return 1.0 if MACHINE_TARGET <= 0 else min(machine_count, MACHINE_TARGET) / MACHINE_TARGET


def _boundaries(first: datetime, last: datetime) -> list[datetime]:
    if first == last:
        return [last]
    step = (last - first) / TREND_POINTS
    return [first + step * (i + 1) for i in range(TREND_POINTS)]


def _eta_seconds(coverage: float, trend: list[float], boundaries: list[datetime]) -> float | None:
    """ETA to 100% from the slope of the last quarter of the trend (at least two
    points); None when that stretch made no progress."""
    if coverage >= 1.0:
        return 0.0
    if len(trend) < 2 or len(trend) != len(boundaries):
        return None
    window = max(2, len(trend) // 4)
    delta_t = (boundaries[-1] - boundaries[-window]).total_seconds()
    delta_c = trend[-1] - trend[-window]
    if delta_t <= 0 or delta_c <= 0:
        return None
    return (1.0 - coverage) / (delta_c / delta_t)


def _share_by(row: dict[str, Any], boundary: datetime) -> float:
    """How much of a weekly row lies at or before ``boundary``, its samples
    taken as spread evenly between its first and last upload."""
    if boundary >= row["last_at"]:
        return 1.0
    if boundary < row["first_at"]:
        return 0.0
    return (boundary - row["first_at"]).total_seconds() / (row["last_at"] - row["first_at"]).total_seconds()


def _trend(weeks: list[dict[str, Any]], machine_since: dict[Any, datetime], boundaries: list[datetime],
           targets: dict[str, int]) -> list[float]:
    """The source's coverage at each boundary of its reason's time grid,
    including the machine factor at that time."""
    trend = []
    for boundary in boundaries:
        counts = {k: 0.0 for k in BUCKET_KEYS}
        for week in weeks:
            share = _share_by(week, boundary)
            if share > 0:
                for i, k in enumerate(BUCKET_KEYS):
                    counts[k] += week["buckets"][i] * share
        machines = sum(1 for since in machine_since.values() if since <= boundary)
        trend.append(_coverage(_bucket_fills(counts, targets)) * _machine_factor(machines))
    return trend


def overview(db: Session, machine_ids: Sequence[Any], capture_reason: str | None = None) -> dict[str, Any]:
    """The diversity overview over these machines' samples (one capture
    reason, or all), from the weekly rows."""
    rows = []
    if machine_ids:
        query = db.query(SampleDiversityWeek).filter(SampleDiversityWeek.machine_id.in_(list(machine_ids)))
        if capture_reason:
            query = query.filter(SampleDiversityWeek.capture_reason == capture_reason)
        rows = query.all()

    # (reason, role) -> week -> the machines' rows of that week, merged.
    pairs: dict[tuple[str, str], dict[Any, dict[str, Any]]] = {}
    machine_since: dict[tuple[str, str], dict[Any, datetime]] = {}
    computed_at = None
    for r in rows:
        first, last = _utc(r.first_at), _utc(r.last_at)
        key = (r.capture_reason, r.source_role)
        week = pairs.setdefault(key, {}).setdefault(
            r.week,
            {"buckets": [0] * (len(BUCKET_KEYS) + 1), "samples": 0, "score_sum": 0.0, "scored": 0,
             "first_at": first, "last_at": last},
        )
        week["buckets"] = [a + int(b) for a, b in zip(week["buckets"], r.buckets)]
        week["samples"] += int(r.samples)
        week["score_sum"] += float(r.score_sum or 0.0)
        week["scored"] += int(r.scored or 0)
        week["first_at"] = min(week["first_at"], first)
        week["last_at"] = max(week["last_at"], last)
        since = machine_since.setdefault(key, {})
        since[r.machine_id] = min(since.get(r.machine_id, first), first)
        computed_at = _utc(r.computed_at) if computed_at is None else min(computed_at, _utc(r.computed_at))

    groups = []
    for reason in sorted({reason for reason, _ in pairs}):
        keys = [key for key in pairs if key[0] == reason]
        first = min(w["first_at"] for key in keys for w in pairs[key].values())
        last = max(w["last_at"] for key in keys for w in pairs[key].values())
        boundaries = _boundaries(first, last)
        group_buckets = {k: 0 for k in BUCKET_KEYS}
        roles, role_fills, role_trends, group_targets = [], [], [], {k: 0 for k in BUCKET_KEYS}
        group_scores = [0.0, 0]
        group_unknown = 0
        for key in keys:
            weeks = list(pairs[key].values())
            role = key[1]
            buckets = {k: sum(w["buckets"][i] for w in weeks) for i, k in enumerate(BUCKET_KEYS)}
            unknown = sum(w["buckets"][len(BUCKET_KEYS)] for w in weeks)
            score_sum, scored = sum(w["score_sum"] for w in weeks), sum(w["scored"] for w in weeks)
            targets = targets_for_role(role)
            fills = _bucket_fills(buckets, targets)
            machine_count = len(machine_since[key])
            base = _coverage(fills)
            coverage = base * _machine_factor(machine_count)
            trend = _trend(weeks, machine_since[key], boundaries, targets)
            roles.append({
                "source_role": role,
                "total": sum(w["samples"] for w in weeks),
                "unknown": unknown,
                "buckets": buckets,
                "last_uploaded_at": max(w["last_at"] for w in weeks).isoformat(),
                "bucket_fills": fills,
                "bucket_targets": dict(targets),
                "coverage_base": base,
                "coverage": coverage,
                "machine_count": machine_count,
                "machine_target": MACHINE_TARGET,
                "machine_factor": _machine_factor(machine_count),
                "coverage_trend": trend,
                "eta_seconds": _eta_seconds(coverage, trend, boundaries),
                "avg_score": score_sum / scored if scored else None,
            })
            role_fills.append(fills)
            role_trends.append(trend)
            for k in BUCKET_KEYS:
                group_buckets[k] += buckets[k]
                group_targets[k] = max(group_targets[k], targets.get(k, 0))
            group_unknown += unknown
            group_scores[0] += score_sum
            group_scores[1] += scored
        roles.sort(key=lambda r: (-r["total"], r["source_role"]))
        fills = _avg_fills(role_fills)
        machine_count = len({m for key in keys for m in machine_since[key]})
        base = _coverage(fills)
        coverage = base * _machine_factor(machine_count)
        trend = [sum(t[i] for t in role_trends) / len(role_trends) for i in range(len(boundaries))]
        groups.append({
            "capture_reason": reason,
            "total": sum(r["total"] for r in roles),
            "unknown": group_unknown,
            "buckets": group_buckets,
            "by_source_role": roles,
            "last_uploaded_at": max(r["last_uploaded_at"] for r in roles),
            "bucket_fills": fills,
            "bucket_targets": group_targets,
            "coverage_base": base,
            "coverage": coverage,
            "machine_count": machine_count,
            "machine_target": MACHINE_TARGET,
            "machine_factor": _machine_factor(machine_count),
            "coverage_trend": trend,
            "eta_seconds": _eta_seconds(coverage, trend, boundaries),
            "avg_score": group_scores[0] / group_scores[1] if group_scores[1] else None,
        })
    groups.sort(key=lambda g: (-g["total"], g["capture_reason"]))
    return {
        "generated_at": (computed_at or datetime.now(timezone.utc)).isoformat(),
        "total": sum(g["total"] for g in groups),
        "default_target_per_bucket": TARGET_PER_BUCKET,
        "machine_target": MACHINE_TARGET,
        "bucket_keys": list(BUCKET_KEYS),
        "groups": groups,
    }
