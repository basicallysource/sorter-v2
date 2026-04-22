"""In-memory LRU store for drop-zone burst frames keyed by global_id.

Ring 2 of the drop-zone burst capture feature. Each burst entry is a list of
frame dicts (role, captured_ts, jpeg_b64) produced by VisionManager.captureBurst
from the pre/post capture-thread ring buffers. Capped to avoid unbounded
growth during long runs.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import TypedDict


class BurstFrame(TypedDict):
    role: str
    captured_ts: float
    jpeg_b64: str


class BurstFrameStore:
    """Thread-safe OrderedDict-based LRU keyed by ``global_id``.

    When capacity is exceeded the oldest (least-recently-stored) entry is
    evicted. ``store`` appends to an existing entry if one is already present
    for that ``global_id`` — this lets the caller stage pre-event frames
    immediately and then merge post-event frames from a timer.
    """

    def __init__(self, max_pieces: int = 50) -> None:
        self._max_pieces = max(1, int(max_pieces))
        self._entries: "OrderedDict[int, list[dict]]" = OrderedDict()
        self._lock = threading.Lock()

    def store(self, global_id: int, frames: list[dict]) -> None:
        """Store or append ``frames`` to the entry for ``global_id``.

        If an entry already exists, the new frames are appended in order
        (useful for merging post-event frames onto the pre-event batch).
        Moves the entry to the MRU position either way.
        """
        if not isinstance(global_id, int):
            return
        with self._lock:
            existing = self._entries.pop(global_id, None)
            if existing is None:
                self._entries[global_id] = list(frames)
            else:
                existing.extend(frames)
                self._entries[global_id] = existing
            self._evict_oldest()

    def get(self, global_id: int) -> list[dict] | None:
        with self._lock:
            entry = self._entries.get(global_id)
            if entry is None:
                return None
            # Return a shallow copy so callers can't mutate the stored list.
            return list(entry)

    def _evict_oldest(self) -> None:
        while len(self._entries) > self._max_pieces:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, global_id: int) -> bool:
        with self._lock:
            return global_id in self._entries
