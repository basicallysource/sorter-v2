"""Pieces the camera cannot see.

Part of a channel's ring can lie outside its camera's picture: a piece rides
through that arc unseen, vanishing where it begins and reappearing where it
ends. Seeing nothing, the feeder would stop moving the channel and strand it
there. So a piece that vanishes where the arc begins is remembered, and its
expected position follows the channel's own moves. A piece that appears where
the arc ends accounts for the oldest one expected (pieces keep their order on a
rotor, so not by id, only by order); one that never appears after the channel
has turned it well past the arc's end is given up.

Angles are the channel's sections (degrees in its travel direction).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# A track counts as gone after being unseen this long.
VANISH_S = 0.4
# How close to the arc's start a track must vanish (before / after it), and how
# close to its end a new one must appear, to be matched.
ENTER_BEFORE_DEG = 20.0
ENTER_AFTER_DEG = 15.0
APPEAR_BEFORE_DEG = 15.0
APPEAR_AFTER_DEG = 30.0
# Give a hidden piece up once its expected position is this far past the end:
# by then it would be in view, so not seeing it means it is not there.
GIVE_UP_PAST_END_DEG = 15.0


def forward(a: float, b: float) -> float:
    """Degrees travelled going forward from a to b, in [0, 360)."""
    return (b - a) % 360.0


@dataclass
class _Seen:
    section: float
    at: float
    odometer: float


@dataclass
class BlindArc:
    start_deg: float = 0.0
    end_deg: float = 0.0
    _tracks: dict[int, _Seen] = field(default_factory=dict)
    # (section it vanished at, channel odometer then), oldest first.
    _hidden: list[tuple[float, float]] = field(default_factory=list)

    @property
    def configured(self) -> bool:
        return forward(self.start_deg, self.end_deg) > 0.0

    def update(self, state, now: float, odometer: float) -> None:
        if not self.configured:
            return
        for p in getattr(state, "pieces", ()):
            tid = getattr(p, "sv_bt_track_id", None)
            if tid is None:
                continue
            section = float(p.com_section)
            if tid not in self._tracks and self._hidden and self._near(
                section, self.end_deg, APPEAR_BEFORE_DEG, APPEAR_AFTER_DEG
            ):
                self._hidden.pop(0)
            self._tracks[tid] = _Seen(section, now, odometer)
        for tid in [t for t, s in self._tracks.items() if now - s.at > VANISH_S]:
            seen = self._tracks.pop(tid)
            if self._near(seen.section, self.start_deg, ENTER_BEFORE_DEG, ENTER_AFTER_DEG):
                self._hidden.append((seen.section, seen.odometer))
        self._hidden = [
            (s, o)
            for s, o in self._hidden
            if odometer - o <= forward(s, self.end_deg) + GIVE_UP_PAST_END_DEG
        ]

    def expected(self, odometer: float) -> list[float]:
        """Where each hidden piece should be now (sections), for those still
        inside the unseen arc."""
        arc = forward(self.start_deg, self.end_deg)
        out = []
        for s, o in self._hidden:
            pos = (s + (odometer - o)) % 360.0
            if forward(self.start_deg, pos) <= arc or forward(pos, self.start_deg) <= ENTER_BEFORE_DEG:
                out.append(pos)
        return out

    def clear(self) -> None:
        self._tracks.clear()
        self._hidden.clear()

    @staticmethod
    def _near(section: float, edge: float, before: float, after: float) -> bool:
        return forward(edge - before, section) <= before + after
