"""A piece its own channel cannot move.

A piece rides its rotor, so when a channel has turned well under a piece and
the piece has not moved, it rests on something else. In this channel's landing
area it still hangs off the channel above: that holds back the channel above
(a channel drops only into a clear landing area), so it opens the `piece_held`
incident, and its recovery procedure works to free it (recovery/procedures.py).
At this channel's exit it hangs onto the channel below, so the feeder turns that
one a little; if a few such turns do not move it, it gives up on that piece and
sorting goes on around it. Either way the piece is listed on the Cycle time page.

A box that touches the edge of the picture is not watched: part of the piece is
out of sight, so its center does not follow it. On a machine whose generation has
``held_at_landing_edge`` one is watched where pieces land, where the edge is the
very case: a piece hanging off the channel above reaches in from outside the
picture and stays put at its edge (clean, November 21, 2026: a piece off C1's
lip sat at the top of C2's picture for nine minutes while C2 turned under it,
and nothing was tried).

A recovery can end while the piece still hangs there (its judge sees the box
move when the channel above nudges the piece, and takes that for freed: clean,
November 22, 2026, a piece off C2's lip lay in C3's landing area for nine
minutes after a 3 degree nudge was judged to have freed it, nothing came down
behind it, and the machine paused blaming C1). On a machine whose generation
has ``held_keeps_trying``, the watch is the judge. Each time the piece is
handed over, its recovery makes one move, the next of its procedure, and the
machine sorts on; if the piece has still not moved once its channel has turned
HELD_AFTER_DEG again, it is handed over again, so each try pushes the channel
above harder. That is for a piece whose box touches the picture's edge, the one
that can hang off the channel above. A piece whole in the picture lies on its
own channel without riding (a flat piece slipping on the floor): no move of
the channel above frees it and none is made, and it creeps on as its channel
turns. Either kind is the operator's only when it has still not moved STUCK_S
after the last thing tried: it is then handed over with no move left, and its
card stays (again every STUCK_S while it lies there).

Each piece found held, each turn and how it ended go to the control-data log,
so the record says how often it happens and whether the turns free it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import held_piece_records

# The piece moved at least this much (degrees): it rides its rotor.
MOVED_DEG = 3.0
# Its channel turned this much under it while it did not move: it is held.
HELD_AFTER_DEG = 45.0
# Where pieces land, it is handed to its incident only once it has stayed put
# this long too: a piece that has just landed often settles for a second or two
# before it rides.
LANDING_HELD_S = 4.0
# For a piece held at an exit: how far the channel below turns to free it (only
# C3 is turned this way: the classification channel turns on its own schedule),
# how long to wait before judging a turn, and how many turns to try.
FREE_TURN_DEG = {3: 8.0}
FREE_SETTLE_S = 1.0
FREE_TURNS = 3
# With every move of its recovery made, a piece that has still not moved this
# long after the last one is the operator's.
STUCK_S = 120.0

_DROP_ZONE = 1
_EXIT_ZONE = 2
_PRECISE_ZONE = 3


@dataclass
class _Watch:
    gap: float
    odometer: float
    since: float
    turns: int = 0
    turned_at: Optional[float] = None
    given_up: bool = False
    zone: str = ""
    # Times it was handed to its incident where pieces land, and when last.
    handovers: int = 0
    handed_at: float = 0.0


@dataclass(frozen=True)
class HeldAtLanding:
    channel: int  # the channel the piece is on
    track_id: int
    box: tuple[float, float, float, float]
    # How many times it was handed over before: its recovery starts that many
    # moves in.
    tries: int = 0


@dataclass(frozen=True)
class FreeTurn:
    channel: int  # the channel to turn
    held_on: int  # the channel the piece is on
    track_id: int
    degrees: float


class HeldPieces:
    def __init__(self, gc: Any, landing_edge: bool = False, keeps_trying: bool = False, moves: int = 0) -> None:
        self.gc = gc
        self._landing_edge = landing_edge
        # ``moves``: how many moves the recovery of a piece held where pieces
        # land has.
        self.keeps_trying = keeps_trying
        self._moves = moves
        self._watch: dict[tuple[int, int], _Watch] = {}

    def reset(self) -> None:
        now = time.monotonic()
        for (channel, track_id), watch in self._watch.items():
            self._end(channel, track_id, watch, "stopped", now)
        self._watch.clear()

    def check(
        self,
        channel: int,
        state: Any,
        odometer: float,
        now: float,
        frame_size: Optional[tuple[int, int]] = None,
    ) -> Optional[FreeTurn | HeldAtLanding]:
        """Watch every tracked piece on ``channel``. Returns a piece held where
        pieces land (once per piece), or the turn of the channel below to make
        now for a piece held at the exit."""
        wanted: Optional[FreeTurn | HeldAtLanding] = None
        seen: set[tuple[int, int]] = set()
        for p in getattr(state, "pieces", ()) or ():
            tid = getattr(p, "sv_bt_track_id", None)
            gap = getattr(p, "com_forward_to_exit_deg", None)
            if tid is None or gap is None:
                continue
            landing = int(getattr(p, "zone_code", 0) or 0) == _DROP_ZONE
            if not (self._landing_edge and landing) and _atEdge(getattr(p, "bbox", None), frame_size):
                continue
            key = (channel, int(tid))
            seen.add(key)
            watch = self._watch.get(key)
            if watch is None or abs(float(gap) - watch.gap) >= MOVED_DEG:
                if watch is not None:
                    self._end(channel, int(tid), watch, "freed", now)
                self._watch[key] = _Watch(float(gap), odometer, now)
                continue
            if odometer - watch.odometer < HELD_AFTER_DEG:
                continue
            if watch.turned_at is not None and now - watch.turned_at < FREE_SETTLE_S:
                continue
            zone = int(getattr(p, "zone_code", 0) or 0)
            if zone == _DROP_ZONE:
                watch.zone = "landing"
                if watch.given_up and self.keeps_trying:
                    # This runs only while no incident is open, so its incident
                    # has ended and it has not moved since.
                    if watch.handovers < self._moves:
                        watch.given_up = False  # watched again from here, for the next move
                        watch.odometer = odometer
                        continue
                    if now - watch.handed_at < STUCK_S:
                        continue
                    watch.given_up = False  # every move made and still here: the operator's
                if not watch.given_up and now - watch.since >= LANDING_HELD_S:
                    box = getattr(p, "bbox", None)
                    if self.keeps_trying and watch.handovers == 0 and frame_size and not _atEdge(box, frame_size):
                        # Whole in the picture: it lies on this channel, it does
                        # not hang off the one above, and no move of that one
                        # frees it. It is left to move on as the channel turns.
                        watch.given_up = True
                        watch.handovers = self._moves
                        watch.handed_at = now
                        self._log("lies where pieces land without riding", channel, int(tid), watch, now)
                        continue
                    taken = wanted is None or isinstance(wanted, FreeTurn)
                    if taken or not self.keeps_trying:
                        watch.given_up = True
                        self._log("held where pieces land", channel, int(tid), watch, now)
                    if taken:
                        wanted = HeldAtLanding(
                            channel, int(tid), tuple(float(v) for v in (box or (0, 0, 0, 0))), watch.handovers
                        )
                        watch.handovers += 1
                        watch.handed_at = now
                continue
            if zone not in (_EXIT_ZONE, _PRECISE_ZONE):
                continue
            other = channel + 1
            watch.zone = "exit"
            if other not in FREE_TURN_DEG:
                # C3's channel below is the classification channel, which turns
                # on its own schedule and takes a piece that lands on it: give up
                # on one that stays put through as much turning as the free turns
                # would have taken.
                if odometer - watch.odometer < HELD_AFTER_DEG * (FREE_TURNS + 1):
                    continue
            elif watch.turns < FREE_TURNS:
                if wanted is None:
                    wanted = FreeTurn(other, channel, int(tid), FREE_TURN_DEG[other])
                continue
            if not watch.given_up:
                watch.given_up = True
                self._log("gave up", channel, int(tid), watch, now)
        for key in [k for k in self._watch if k[0] == channel and k not in seen]:
            self._end(channel, key[1], self._watch.pop(key), "gone", now)
        return wanted

    def turned(self, turn: FreeTurn, now: float) -> None:
        """The feeder made ``turn``."""
        watch = self._watch.get((turn.held_on, turn.track_id))
        if watch is None:
            return
        watch.turns += 1
        watch.turned_at = now
        self._log(f"turned C{turn.channel}", turn.held_on, turn.track_id, watch, now)

    def _end(self, channel: int, track_id: int, watch: _Watch, how: str, now: float) -> None:
        if watch.turns or watch.given_up:
            self._log(how, channel, track_id, watch, now)
            wall = time.time()
            held_piece_records.record(
                channel=channel,
                track_id=track_id,
                zone=watch.zone,
                started_at=wall - (now - watch.since),
                ended_at=wall,
                turns=watch.turns,
                gave_up=int(watch.given_up),
                outcome=how,
            )

    def _log(self, what: str, channel: int, track_id: int, watch: _Watch, now: float) -> None:
        held_s = now - watch.since
        try:
            self.gc.logger.info(
                f"PulsePerception: held piece on C{channel} track={track_id}: {what} "
                f"(held {held_s:.1f} s, {watch.turns} turns)"
            )
        except Exception:
            pass
        try:
            import control_data_store

            control_data_store.record(
                {
                    "type": "event",
                    "kind": "held_piece",
                    "what": what,
                    "ch": channel,
                    "track": track_id,
                    "turns": watch.turns,
                    "held_s": round(held_s, 2),
                    "t": time.time(),
                    "mono": now,
                }
            )
        except Exception:
            pass


def _atEdge(bbox: Any, frame_size: Optional[tuple[int, int]]) -> bool:
    """The box touches the picture's edge (``frame_size`` is width, height)."""
    if not bbox or frame_size is None:
        return False
    w, h = frame_size
    x1, y1, x2, y2 = bbox
    return x1 <= 1 or y1 <= 1 or x2 >= w - 2 or y2 >= h - 2
