"""The feeder fitting itself to the pieces it feeds.

Two things decide how often two pieces fall onto the classification channel
together, and the machine can measure both while it runs.

Room on C3. Pieces ride C3's rotor, so the gap between two of them is set when
the second lands and holds until the first falls off C3's exit. A piece close
behind another goes over the edge with it far more often (on one machine, 14%
of hand-offs with the next piece under 20 degrees behind doubled, against about
1% at 20 to 120 degrees). C2 dropping as soon as C3's landing zone is clear
leaves that gap to chance: a piece can land at the front of the zone, right
behind one that has only just left it. So C2 drops only once the back of every
piece ahead of the landing zone is at least ``margin`` degrees past the front
of where pieces land. Where they land is measured, from where new pieces are
first seen in the landing zone just after C2 dropped one (a new track id
elsewhere is a tracker switch, not a landing), and a piece's back comes from
its box, so a long piece takes more room by itself. The margin follows the double feeds: it
grows while pieces that left C3 close behind another double more often than
the rest, and eases back toward its floor while none leave that close and the
room is what keeps C2 waiting.

The hold after a fall. A channel pushes nothing off its exit for a while after
a piece falls, so the next channel sees it land first. How long a piece takes
to land is measured from the pieces seen to fall and then land (zones/watch.py),
so a machine with a long drop or a ramp holds longer, and a quick one
no longer than it needs.

What it decided and why is in ``report()``, on the feeder's tuning page.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable, Optional

from perception.arcs import backGapToExitDeg, forwardGapToExitDeg, sectionGapToExitDeg

_DROP_ZONE = 1

# Where pieces land on C3: the distance to the exit of the front of each new
# piece first seen in the landing zone within LANDING_AFTER_FALL_S of C2's
# gate seeing a piece fall. The front of where they land is this share of
# them, counted from the most forward, once there are enough; until then, the
# front of the landing zone.
LANDINGS_KEPT = 60
LANDINGS_NEEDED = 10
LANDING_FRONT_SHARE = 0.25
LANDING_AFTER_FALL_S = 2.5
# A track id is remembered this long after it was last seen.
SEEN_KEPT_S = 30.0

# The margin moves at most every TUNE_EVERY_S, judged on the hand-offs to the
# classification channel since it last moved (at least TUNE_CYCLES of them),
# up by MARGIN_UP_DEG or down by MARGIN_DOWN_DEG, never past MARGIN_MAX_DEG.
MARGIN_MAX_DEG = 30.0
MARGIN_UP_DEG = 2.0
MARGIN_DOWN_DEG = 1.0
TUNE_EVERY_S = 60.0
TUNE_CYCLES = 40
# A hand-off left close behind another when the next piece on C3 sat this
# close behind the leaving one (centers) as it went.
CLOSE_GAP_DEG = 25.0
CLOSE_NEEDED = 5
# Close hand-offs double "more often" than the rest when at least this much
# more often, and at least twice as often.
CLOSE_EXCESS = 0.05
# The room is "what keeps C2 waiting" when it alone held back a piece C2 had
# ready for this share of the time C2 had one ready.
WAITING_SHARE = 0.2

# The hold after a fall: the time nine in ten pieces took to land, plus
# HOLD_MARGIN_S, within HOLD_MIN_S and HOLD_MAX_S, once HOLD_LANDINGS_NEEDED
# falls have been seen to land. A landing slower than SLOW_LANDING_S is left
# out: that is another piece turning up, not the one that fell.
HOLD_MARGIN_S = 0.3
HOLD_MIN_S = 0.5
HOLD_MAX_S = 2.5
HOLD_LANDINGS_NEEDED = 20
SLOW_LANDING_S = 3.0
HOLD_EVERY_S = 5.0


def _quantile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(share * (len(ordered) - 1))))]


def _doubled(rows: list[dict[str, Any]]) -> float:
    """The share of these hand-offs that doubled."""
    return sum(1 for r in rows if r.get("multi_drop")) / len(rows) if rows else 0.0


def _cycleGap(row: dict[str, Any]) -> Optional[float]:
    head, nxt = row.get("c3_head_deg"), row.get("c3_next_deg")
    if head is None or nxt is None:
        return None
    return float(nxt) - float(head)


def _loadRoom() -> Optional[dict[str, Any]]:
    import local_state

    return local_state.getFeederRoom()


def _saveRoom(record: dict[str, Any]) -> None:
    import local_state

    local_state.setFeederRoom(record)


def _cyclesSince(since: float) -> list[dict[str, Any]]:
    import piece_cycles

    return piece_cycles.listCycles(since)


def _landingDelays(channel: int) -> list[float]:
    from zones import watch

    current = watch.current()
    if current is None:
        return []
    return [h.delay_s for h in current.handoffs(channel)]


class Adapt:
    def __init__(
        self,
        *,
        load: Callable[[], Optional[dict[str, Any]]] = _loadRoom,
        save: Callable[[dict[str, Any]], None] = _saveRoom,
        cycles: Callable[[float], list[dict[str, Any]]] = _cyclesSince,
        landing_delays: Callable[[int], list[float]] = _landingDelays,
    ) -> None:
        self._save = save
        self._cycles = cycles
        self._landing_delays = landing_delays
        self._lock = threading.Lock()
        self._landings: deque[float] = deque(maxlen=LANDINGS_KEPT)
        self._seen: dict[int, float] = {}
        self._front: Optional[float] = None
        self._front_measured = False
        self._margin: Optional[float] = None
        self._floor = 0.0
        self._changed_at = time.time()
        self._why = ""
        self._tuned_at: Optional[float] = None
        self._ready_s = 0.0
        self._waiting_s = 0.0
        self._last_tick: Optional[float] = None
        self._waiting_now = False
        self._holds: dict[int, dict[str, Any]] = {}
        self._held_at: dict[int, float] = {}
        try:
            stored = load() or {}
        except Exception:
            stored = {}
        if isinstance(stored.get("margin_deg"), (int, float)):
            self._margin = float(stored["margin_deg"])
            self._why = str(stored.get("why") or "")

    # --- room on C3 -------------------------------------------------------

    def observe(self, state: Any, channel: Any, now: float, fell_at: Optional[float] = None) -> None:
        """Note the pieces first seen in C3's landing zone this frame, when C2
        saw a piece fall off its exit at ``fell_at`` (same clock as ``now``)
        just before."""
        if channel is None:
            return
        landing = fell_at is not None and 0.0 <= now - fell_at <= LANDING_AFTER_FALL_S
        with self._lock:
            for piece in getattr(state, "pieces", ()) or ():
                track_id = getattr(piece, "sv_bt_track_id", None)
                if track_id is None:
                    continue
                new = track_id not in self._seen
                self._seen[track_id] = now
                if new and landing and piece.zone_code == _DROP_ZONE:
                    self._landings.append(forwardGapToExitDeg(piece.bbox, channel))
            for track_id in [t for t, at in self._seen.items() if now - at > SEEN_KEPT_S]:
                del self._seen[track_id]
            self._front, self._front_measured = self._landingFront(channel)

    def _landingFront(self, channel: Any) -> tuple[Optional[float], bool]:
        if len(self._landings) >= LANDINGS_NEEDED:
            return _quantile(list(self._landings), LANDING_FRONT_SHARE), True
        gaps = [sectionGapToExitDeg(s, channel) for s in getattr(channel, "drop_sections", ())]
        gaps = [g for g in gaps if g is not None]
        return (min(gaps), False) if gaps else (None, False)

    def margin(self, floor_deg: float) -> float:
        """The margin, never under the configured floor."""
        with self._lock:
            self._floor = max(0.0, float(floor_deg))
            if self._margin is None or self._margin < self._floor:
                self._margin = self._floor
            return self._margin

    def roomClear(self, state: Any, channel: Any, floor_deg: float) -> bool:
        """C2 may drop: every piece on C3 ahead of where pieces land has its
        back at least the margin past the front of where they land. A floor of
        0 turns the room off."""
        if floor_deg <= 0 or channel is None:
            return True
        margin = self.margin(floor_deg)
        with self._lock:
            front = self._front
        if front is None:
            return True
        for piece in getattr(state, "pieces", ()) or ():
            # A piece still in the landing zone holds C2 by itself; one behind
            # where pieces land is not ahead of the next one.
            if piece.zone_code == _DROP_ZONE or piece.com_forward_to_exit_deg >= front:
                continue
            if backGapToExitDeg(piece.bbox, channel) > front - margin:
                return False
        return True

    def noteWait(self, ready: bool, held: bool, now: float) -> None:
        """C2 had a piece ready to drop and C3 could take it, and whether the
        room alone held it back."""
        with self._lock:
            if self._last_tick is not None:
                dt = min(1.0, max(0.0, now - self._last_tick))
                if ready:
                    self._ready_s += dt
                    if held:
                        self._waiting_s += dt
            self._last_tick = now
            self._waiting_now = bool(ready and held)

    def tune(self, now: float, mono: float) -> None:
        """Move the margin after the double feeds since it last moved."""
        if self._margin is None or (self._tuned_at is not None and mono - self._tuned_at < TUNE_EVERY_S):
            return
        self._tuned_at = mono
        try:
            rows = [r for r in self._cycles(self._changed_at) if r.get("landed_at") is not None]
        except Exception:
            return
        if len(rows) < TUNE_CYCLES:
            return
        close, rest = [], []
        for row in rows:
            gap = _cycleGap(row)
            (close if gap is not None and gap < CLOSE_GAP_DEG else rest).append(row)
        close_rate, rest_rate = _doubled(close), _doubled(rest)
        with self._lock:
            waiting = self._waiting_s / self._ready_s if self._ready_s > 0 else 0.0
            margin = self._margin
            if margin is None:
                return
            if (
                len(close) >= CLOSE_NEEDED
                and close_rate >= rest_rate + CLOSE_EXCESS
                and close_rate >= 2 * rest_rate
                and margin < MARGIN_MAX_DEG
            ):
                margin = min(MARGIN_MAX_DEG, margin + MARGIN_UP_DEG)
                why = (
                    f"{100 * close_rate:.0f}% of {len(close)} pieces that left C3 close behind another "
                    f"doubled, against {100 * rest_rate:.0f}% of the other {len(rest)}"
                )
            elif len(close) < CLOSE_NEEDED and waiting >= WAITING_SHARE and margin > self._floor:
                margin = max(self._floor, margin - MARGIN_DOWN_DEG)
                why = (
                    f"{len(close)} of {len(rows)} pieces left C3 close behind another, and the room kept "
                    f"C2 waiting {100 * waiting:.0f}% of the time it had a piece ready"
                )
            else:
                return
            self._margin = margin
            self._why = why
            self._changed_at = now
            self._ready_s = self._waiting_s = 0.0
            record = {"margin_deg": margin, "why": why, "changed_at": now}
        try:
            self._save(record)
        except Exception:
            pass

    # --- the hold after a fall ---------------------------------------------

    def holdS(self, channel: int, configured_s: float, follows_landings: bool, mono: float) -> float:
        """How long the exit of ``channel`` holds after a piece falls: from how
        long pieces have taken to land, or the configured hold until enough
        have been seen (or when it should not follow them)."""
        if not follows_landings:
            with self._lock:
                self._holds[channel] = {"hold_s": configured_s, "measured": False, "follows": False, "landings": 0}
                self._held_at.pop(channel, None)
            return configured_s
        if mono - self._held_at.get(channel, -1e9) >= HOLD_EVERY_S:
            try:
                delays = [d for d in self._landing_delays(channel) if 0.0 <= d <= SLOW_LANDING_S]
            except Exception:
                delays = []
            entry: dict[str, Any] = {"hold_s": None, "measured": False, "follows": True, "landings": len(delays)}
            if len(delays) >= HOLD_LANDINGS_NEEDED:
                p90 = _quantile(delays, 0.9)
                entry.update(hold_s=min(HOLD_MAX_S, max(HOLD_MIN_S, p90 + HOLD_MARGIN_S)), measured=True, p90_s=p90)
            with self._lock:
                self._holds[channel] = entry
                self._held_at[channel] = mono
        entry = self._holds[channel]
        return entry["hold_s"] if entry["measured"] else configured_s

    # --- what it decided ----------------------------------------------------

    def report(self) -> dict[str, Any]:
        with self._lock:
            waiting = self._waiting_s / self._ready_s if self._ready_s > 0 else None
            return {
                "room": {
                    "margin_deg": self._margin,
                    "floor_deg": self._floor,
                    "max_deg": MARGIN_MAX_DEG,
                    "landing_front_deg": self._front,
                    "landing_front_measured": self._front_measured,
                    "landings": len(self._landings),
                    "why": self._why,
                    "changed_at": self._changed_at,
                    "waiting_now": self._waiting_now,
                    "waiting_share": waiting,
                },
                "hold": {str(ch): dict(entry) for ch, entry in self._holds.items()},
            }


_adapt: Optional[Adapt] = None
_adapt_lock = threading.Lock()


def get() -> Adapt:
    global _adapt
    with _adapt_lock:
        if _adapt is None:
            _adapt = Adapt()
        return _adapt
