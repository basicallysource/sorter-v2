"""A piece its own channel cannot move.

A piece rides its rotor, so when a channel has turned well under a piece and
the piece has not moved, it rests on something else. In this channel's landing
area it still hangs off the channel above; at this channel's exit it hangs onto
the channel below. So the feeder turns that other channel a little. If a few
such turns do not move it either, it gives up on that piece and sorting goes on
around it; the piece is listed on the Cycle time page.

A held piece blocks the channel above by itself (a channel only drops into a
clear landing area), which is why turning the channel above is the one move
that frees it and the one move the feeder would otherwise never make.

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
# How far the other channel turns to free it (C1 moves the whole bulk pile, so
# less), how long to wait before judging a turn, and how many turns to try.
FREE_TURN_DEG = {1: 3.0, 2: 8.0, 3: 8.0}
FREE_SETTLE_S = 1.0
FREE_TURNS = 3

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


@dataclass(frozen=True)
class FreeTurn:
    channel: int  # the channel to turn
    held_on: int  # the channel the piece is on
    track_id: int
    degrees: float


class HeldPieces:
    def __init__(self, gc: Any) -> None:
        self.gc = gc
        self._watch: dict[tuple[int, int], _Watch] = {}

    def reset(self) -> None:
        now = time.monotonic()
        for (channel, track_id), watch in self._watch.items():
            self._end(channel, track_id, watch, "stopped", now)
        self._watch.clear()

    def check(self, channel: int, state: Any, odometer: float, now: float) -> Optional[FreeTurn]:
        """Watch every tracked piece on ``channel``. Returns the turn of the
        channel above or below to make now, when one of them is held."""
        wanted: Optional[FreeTurn] = None
        seen: set[tuple[int, int]] = set()
        for p in getattr(state, "pieces", ()) or ():
            tid = getattr(p, "sv_bt_track_id", None)
            gap = getattr(p, "com_forward_to_exit_deg", None)
            if tid is None or gap is None:
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
                other = channel - 1
            elif zone in (_EXIT_ZONE, _PRECISE_ZONE):
                other = channel + 1
            else:
                continue
            watch.zone = "landing" if zone == _DROP_ZONE else "exit"
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
