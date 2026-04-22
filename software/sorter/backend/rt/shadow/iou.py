"""Rolling IoU metric for shadow-mode vs. legacy tracker comparison.

The tracker rolls a ring buffer of ``(timestamp, iou_value)`` samples inside
``window_sec`` and reports the mean. Matching between the two track sets
uses Hungarian on an IoU cost with a minimum-IoU gate at 0.3 — pairs below
that are treated as unmatched. Score semantics:

* Each matched pair contributes its pairwise IoU.
* Unmatched tracks on either side contribute 0.0.
* Frame IoU = average over ``max(count_new, count_legacy)`` contributions;
  an empty-empty frame contributes 1.0 (perfect agreement).

No numpy dep for the bbox math (plain Python) — the Hungarian solver is
taken from scipy only when there is at least one pair to match, which is
already a hard dep of the polar tracker.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable

from rt.contracts.events import Event, EventBus


# Minimum pairwise IoU we accept as "matched". Below this, the pair is a
# mismatch and the bbox counts as unmatched on both sides.
_MATCH_THRESHOLD = 0.3


def bbox_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    """Return IoU of two xyxy boxes. Degenerate inputs return 0.0."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    if ax2 <= ax1 or ay2 <= ay1 or bx2 <= bx1 or by2 <= by1:
        return 0.0
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    iw = max(0, inter_x2 - inter_x1)
    ih = max(0, inter_y2 - inter_y1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return float(inter) / float(union)


def _extract_bbox(obj: Any) -> tuple[int, int, int, int] | None:
    """Best-effort adapter: take a new-rt ``Track`` or a legacy
    ``TrackedPiece`` (or any dict-like) and return its xyxy bbox.
    """
    if obj is None:
        return None
    # rt.contracts.tracking.Track
    bbox = getattr(obj, "bbox_xyxy", None)
    if bbox is None:
        # legacy TrackedPiece
        bbox = getattr(obj, "bbox", None)
    if bbox is None and isinstance(obj, dict):
        bbox = obj.get("bbox_xyxy") or obj.get("bbox")
    if bbox is None:
        return None
    try:
        x1, y1, x2, y2 = bbox
    except (TypeError, ValueError):
        return None
    try:
        return int(x1), int(y1), int(x2), int(y2)
    except (TypeError, ValueError):
        return None


def compute_frame_iou(
    new_tracks: Iterable[Any],
    legacy_tracks: Iterable[Any],
) -> float:
    """Compute a frame-level IoU score between two track lists.

    Returns a value in [0, 1]. Empty-empty = 1.0 (perfect agreement).
    """
    new_boxes = [bb for bb in (_extract_bbox(t) for t in new_tracks) if bb is not None]
    legacy_boxes = [bb for bb in (_extract_bbox(t) for t in legacy_tracks) if bb is not None]
    if not new_boxes and not legacy_boxes:
        return 1.0
    if not new_boxes or not legacy_boxes:
        return 0.0

    rows = len(new_boxes)
    cols = len(legacy_boxes)
    # Build cost matrix as (1 - IoU). scipy minimizes, and we want to
    # maximize IoU while respecting the match threshold.
    large = 10.0  # anything ≥ 1.0 is outside the cost-space for a valid IoU
    # Compute iou matrix first (for the threshold check on each pair).
    iou_matrix: list[list[float]] = [
        [bbox_iou(new_boxes[r], legacy_boxes[c]) for c in range(cols)]
        for r in range(rows)
    ]
    # Lazy import: only pay for scipy once we know we need Hungarian.
    try:
        from scipy.optimize import linear_sum_assignment
    except Exception:  # pragma: no cover - scipy is a hard dep
        # Fall back to greedy row-wise max matching if scipy is missing.
        return _greedy_iou_match(iou_matrix, rows, cols)

    cost = [[large] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            iou = iou_matrix[r][c]
            if iou >= _MATCH_THRESHOLD:
                cost[r][c] = 1.0 - iou
    row_ind, col_ind = linear_sum_assignment(cost)
    accepted_pairs = 0
    iou_sum = 0.0
    matched_rows: set[int] = set()
    matched_cols: set[int] = set()
    for r, c in zip(row_ind, col_ind):
        if cost[r][c] >= large:
            continue
        iou_sum += iou_matrix[r][c]
        matched_rows.add(int(r))
        matched_cols.add(int(c))
        accepted_pairs += 1
    unmatched = (rows - len(matched_rows)) + (cols - len(matched_cols))
    total_contributions = accepted_pairs + unmatched
    if total_contributions <= 0:
        return 0.0
    return iou_sum / float(total_contributions)


def _greedy_iou_match(
    iou_matrix: list[list[float]], rows: int, cols: int
) -> float:
    taken_cols: set[int] = set()
    iou_sum = 0.0
    matched = 0
    for r in range(rows):
        best_c = -1
        best_iou = _MATCH_THRESHOLD
        for c in range(cols):
            if c in taken_cols:
                continue
            if iou_matrix[r][c] > best_iou:
                best_iou = iou_matrix[r][c]
                best_c = c
        if best_c >= 0:
            taken_cols.add(best_c)
            iou_sum += best_iou
            matched += 1
    unmatched = (rows - matched) + (cols - len(taken_cols))
    total = matched + unmatched
    if total <= 0:
        return 0.0
    return iou_sum / float(total)


@dataclass(frozen=True, slots=True)
class IouSample:
    ts: float
    iou: float


class RollingIouTracker:
    """Stores IoU samples in a ring bounded by a wall-clock window.

    Thread-safe: samples can be recorded from the perception thread while
    the FastAPI request thread reads ``mean_iou``.
    """

    def __init__(self, window_sec: float = 10.0, max_samples: int = 4096) -> None:
        self._window = max(0.1, float(window_sec))
        self._samples: deque[IouSample] = deque(maxlen=int(max_samples))
        self._lock = threading.Lock()

    # ---- Recording ---------------------------------------------------

    def record(
        self,
        new_tracks: Iterable[Any],
        legacy_tracks: Iterable[Any],
        *,
        timestamp: float | None = None,
    ) -> float:
        """Record one frame-comparison sample. Returns the computed IoU."""
        iou = compute_frame_iou(new_tracks, legacy_tracks)
        ts = float(timestamp) if timestamp is not None else time.monotonic()
        with self._lock:
            self._samples.append(IouSample(ts=ts, iou=float(iou)))
            self._evict_expired(ts)
        return iou

    def _evict_expired(self, now: float) -> None:
        cutoff = now - self._window
        while self._samples and self._samples[0].ts < cutoff:
            self._samples.popleft()

    # ---- Readers -----------------------------------------------------

    def mean_iou(self, *, now: float | None = None) -> float:
        ts = float(now) if now is not None else time.monotonic()
        with self._lock:
            self._evict_expired(ts)
            if not self._samples:
                return 0.0
            total = sum(s.iou for s in self._samples)
            return total / float(len(self._samples))

    def sample_count(self, *, now: float | None = None) -> int:
        ts = float(now) if now is not None else time.monotonic()
        with self._lock:
            self._evict_expired(ts)
            return len(self._samples)

    def window_sec(self) -> float:
        return self._window

    def snapshot(self) -> dict[str, float | int]:
        """Thread-safe snapshot for API/events."""
        now = time.monotonic()
        with self._lock:
            self._evict_expired(now)
            count = len(self._samples)
            if count == 0:
                return {"mean_iou": 0.0, "sample_count": 0, "window_sec": self._window}
            total = sum(s.iou for s in self._samples)
            return {
                "mean_iou": total / float(count),
                "sample_count": count,
                "window_sec": self._window,
            }

    # ---- Optional EventBus publish -----------------------------------

    def publish_event(
        self,
        event_bus: EventBus,
        *,
        topic: str,
        role: str,
        source: str = "rt.shadow.iou",
    ) -> None:
        snapshot = self.snapshot()
        payload = {"role": role, **snapshot}
        event_bus.publish(
            Event(
                topic=topic,
                payload=payload,
                source=source,
                ts_mono=time.monotonic(),
            )
        )


__all__ = [
    "IouSample",
    "RollingIouTracker",
    "bbox_iou",
    "compute_frame_iou",
]
