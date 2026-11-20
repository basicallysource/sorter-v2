"""How many pieces left a channel's exit in one fall.

The channel below sees what landed, but not always how many: two pieces lying
together can be drawn as one box, and one oddly shaped piece as several. The
channel above saw them before they fell. When its lead falls, every other piece
it saw at the exit just before or during the fall that is gone within a short
window (and not merely drawn again under another track id) fell with it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# A piece at the exit: its center this close to where pieces fall (output deg).
NEAR_DEG = 4.0
# Pieces gone this soon after the lead fell went with it.
WINDOW_S = 0.6
# Seen at the exit this soon before the fall counts.
BEFORE_S = 0.4
# Gone at least this long (a detector blink is not a fall).
CONFIRM_S = 0.15
# A box this close to a vanished one is the same piece under a new id (px).
SAME_PX = 40.0


def _center(bbox) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


@dataclass
class FallCount:
    # When the last fall began (monotonic), and how many pieces it took.
    started: float | None = None
    count: int = 0
    # Pieces seen at the exit lately: id -> (last seen, box).
    _near: dict[int, tuple[float, tuple]] = field(default_factory=dict)
    _counted: set[int] = field(default_factory=set)

    def observe(self, state, now: float, fell_id: int | None = None, fell: bool = False) -> bool:
        """Update from one frame (``fell``: the gate saw the lead fall on it).
        True when the count of the current fall went up."""
        pieces = list(getattr(state, "pieces", ()) or ())
        for p in pieces:
            gap = getattr(p, "com_forward_to_exit_deg", None)
            tid = getattr(p, "sv_bt_track_id", None)
            if tid is not None and gap is not None and float(gap) <= NEAR_DEG:
                self._near[int(tid)] = (now, tuple(p.bbox))
        if fell:
            self.started = now
            self.count = 1
            self._counted = {int(fell_id)} if fell_id is not None else set()
        grew = False
        if self.started is not None and now - self.started <= WINDOW_S + CONFIRM_S:
            present = {getattr(p, "sv_bt_track_id", None) for p in pieces}
            centers = [_center(p.bbox) for p in pieces]
            for tid, (seen, box) in self._near.items():
                if tid in self._counted or tid in present:
                    continue
                if seen < self.started - BEFORE_S or now - seen < CONFIRM_S:
                    continue
                cx, cy = _center(box)
                if any(abs(cx - x) <= SAME_PX and abs(cy - y) <= SAME_PX for x, y in centers):
                    continue  # Drawn again under another id
                self._counted.add(tid)
                self.count += 1
                grew = True
        for tid in [t for t, (seen, _) in self._near.items() if now - seen > 3.0]:
            del self._near[tid]
        return grew
