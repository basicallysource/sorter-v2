"""A piece that does not move when its channel turns.

A piece rides its rotor. When a channel has turned ``stuck_after_deg`` under
its leading piece and the piece has not moved, something holds it: it straddles
the gap between rotor and stator, it still hangs on the lip of the channel
above (seen in this channel's drop zone), or it sticks at the exit. Holding
still (the channel below is busy) turns nothing, so it never reads as stuck.

With the feeder jam handled automatically, the remedies are tried in turn: a
nudge of the channel above when the piece sits where that channel drops, and
short shakes of this channel, taking the jitter presets in rotation. Each
attempt and its outcome go to the control log, so the record says over time
which shake frees pieces best. A piece that moves again, or leaves, is free.
After the attempts, or at once when handled manually, the operator gets the
feeder jam card; when they press Done the watch starts over.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import incidents

KIND = "feeder_jam"

# Motor-shaft degrees per stroke, strokes, speed (usteps/s), acceleration
# (usteps/s^2). The same presets as the jitter test page.
JITTER_PRESETS: dict[str, tuple[float, int, int, int]] = {
    "Heavy stuck": (6, 12, 5000, 100000),
    "Quick stuck": (6, 6, 5000, 100000),
    "Brief stuck": (6, 3, 5000, 100000),
    "Sharp & short": (6, 6, 6500, 180000),
    "Hard snap": (6, 3, 7000, 220000),
    "Soft & long": (5, 30, 3500, 55000),
    "Gentle marathon": (4, 50, 3000, 45000),
    "Big travel": (9, 12, 5000, 110000),
    "Big & brief": (9, 5, 6000, 150000),
    "Big & hard": (9, 8, 6500, 200000),
    "Max shake": (13, 12, 6500, 190000),
    "Wide & soft": (9, 16, 3500, 55000),
    "Fast buzz": (6, 24, 6000, 150000),
    "Strong & long": (8, 30, 6000, 140000),
}
# The shakes tried, in rotation across stuck pieces.
TRIAL_PRESETS = ("Sharp & short", "Quick stuck", "Hard snap", "Brief stuck", "Heavy stuck")

# The leading piece moved at least this much: it rides the rotor.
MOVED_DEG = 3.0
# After an attempt, the channel turns this much more before it is judged.
SETTLE_DEG = 8.0
# A piece past the fall edge (in the exit proper) should drop at once; one
# still there after this long hangs on the lip, whether or not the channel is
# turning (it may be waiting on the channel below, which may itself be waiting
# on this very piece), and is stuck too. Attempts on it are this far apart.
EXIT_DWELL_S = 2.0
EXIT_SETTLE_S = 1.5
_DROP_ZONE = 1
_EXIT_ZONE = 2


@dataclass(frozen=True)
class Remedy:
    kind: str  # "nudge_upstream" or "jitter"
    preset: str = ""


@dataclass
class _Watch:
    track_id: Optional[int]
    ref_pos: float
    ref_odometer: float
    attempts: list[str] = field(default_factory=list)
    attempt_odometer: Optional[float] = None
    attempt_at: Optional[float] = None
    since: float = 0.0
    in_exit_since: Optional[float] = None
    raised: bool = False


class StuckPieces:
    def __init__(self, gc: Any) -> None:
        self.gc = gc
        self._watch: dict[int, _Watch] = {}
        self._margin: dict[int, _Watch] = {}
        self._next_preset = 0

    def reset(self) -> None:
        self._watch.clear()
        self._margin.clear()

    def observe(
        self,
        *,
        channel: int,
        label: str,
        upstream_label: str,
        state,
        odometer: float,
        now: float,
        cfg,
        can_nudge: bool = True,
    ) -> Optional[Remedy]:
        """Watch this channel's leading piece, and anything hanging just past its
        exit; return a remedy to run now, if any."""
        hang = self._hanging(channel, label, upstream_label, state, now, cfg)
        if hang is not None:
            return hang
        pieces = getattr(state, "pieces", ())
        lead = pieces[0] if pieces else None
        watch = self._watch.get(channel)
        if lead is None:
            if watch is not None:
                self._finish(channel, label, watch, freed=True, now=now)
            return None
        track_id = getattr(lead, "sv_bt_track_id", None)
        pos = float(lead.com_forward_to_exit_deg)
        if watch is None or (track_id is not None and track_id != watch.track_id):
            if watch is not None:
                self._finish(channel, label, watch, freed=True, now=now)
            self._watch[channel] = _Watch(track_id, pos, odometer, since=now)
            return None
        if watch.raised:
            if incidents.openIncident(self.gc, KIND, subject=label) is None:
                # The operator resolved it: a fresh watch from here.
                self._watch[channel] = _Watch(track_id, pos, odometer, since=now)
            return None
        if abs(watch.ref_pos - pos) >= MOVED_DEG:
            self._finish(channel, label, watch, freed=True, now=now)
            self._watch[channel] = _Watch(track_id, pos, odometer, since=now)
            return None
        turned = odometer - watch.ref_odometer
        if int(lead.zone_code) == _EXIT_ZONE:
            watch.in_exit_since = watch.in_exit_since if watch.in_exit_since is not None else now
        else:
            watch.in_exit_since = None
        hanging = watch.in_exit_since is not None and now - watch.in_exit_since >= EXIT_DWELL_S
        if turned < cfg.stuck_after_deg and not hanging:
            return None
        if hanging:
            if watch.attempt_at is not None and now - watch.attempt_at < EXIT_SETTLE_S:
                return None
        elif watch.attempt_odometer is not None and odometer - watch.attempt_odometer < SETTLE_DEG:
            return None
        mode = incidents.handling(KIND)
        if mode == incidents.OFF:
            return None
        if mode == incidents.AUTOMATIC and len(watch.attempts) < cfg.stuck_max_attempts:
            remedy = self._nextRemedy(watch, lead, can_nudge)
            watch.attempts.append(remedy.preset or remedy.kind)
            watch.attempt_odometer = odometer
            watch.attempt_at = now
            self._record(
                {"kind": "stuck_attempt", "channel": label, "remedy": remedy.kind,
                 "preset": remedy.preset, "params": JITTER_PRESETS.get(remedy.preset),
                 "attempt": len(watch.attempts), "zone": int(lead.zone_code)}
            )
            return remedy
        watch.raised = incidents.report(
            self.gc,
            KIND,
            subject=label,
            upstream_label=upstream_label,
            attempts=list(watch.attempts),
            turned_deg=round(turned, 1),
        )
        self._record({"kind": "stuck_raised", "channel": label, "attempts": list(watch.attempts)})
        return None

    def _hanging(self, channel: int, label: str, upstream_label: str, state, now: float, cfg) -> Optional[Remedy]:
        """A piece wholly past the exit's edge that stays there hangs off the
        lip (the channel below may even be waiting on it): shake this channel."""
        watch = self._margin.get(channel)
        if not getattr(state, "in_margin", False):
            if watch is not None:
                self._margin.pop(channel)
                if watch.attempts and not watch.raised:
                    self._record({"kind": "stuck_outcome", "channel": label, "where": "margin",
                                  "freed": True, "attempts": list(watch.attempts),
                                  "seconds": round(now - watch.since, 1)})
            return None
        if watch is None:
            watch = self._margin[channel] = _Watch(None, 0.0, 0.0, since=now)
        if watch.raised:
            if incidents.openIncident(self.gc, KIND, subject=label) is None:
                self._margin[channel] = _Watch(None, 0.0, 0.0, since=now)
            return None
        if now - watch.since < EXIT_DWELL_S:
            return None
        if watch.attempt_at is not None and now - watch.attempt_at < EXIT_SETTLE_S:
            return None
        mode = incidents.handling(KIND)
        if mode == incidents.OFF:
            return None
        if mode == incidents.AUTOMATIC and len(watch.attempts) < cfg.stuck_max_attempts:
            preset = TRIAL_PRESETS[self._next_preset % len(TRIAL_PRESETS)]
            self._next_preset += 1
            watch.attempts.append(preset)
            watch.attempt_at = now
            self._record({"kind": "stuck_attempt", "channel": label, "where": "margin", "remedy": "jitter",
                          "preset": preset, "params": JITTER_PRESETS.get(preset), "attempt": len(watch.attempts)})
            return Remedy("jitter", preset)
        watch.raised = incidents.report(self.gc, KIND, subject=label, upstream_label=upstream_label,
                                        attempts=list(watch.attempts), where="margin")
        return None

    def _nextRemedy(self, watch: _Watch, lead, can_nudge: bool) -> Remedy:
        # Where the channel above drops, the piece may still hang on its lip:
        # nudge that channel first, once.
        if can_nudge and int(lead.zone_code) == _DROP_ZONE and "nudge_upstream" not in watch.attempts:
            return Remedy("nudge_upstream")
        preset = TRIAL_PRESETS[self._next_preset % len(TRIAL_PRESETS)]
        self._next_preset += 1
        return Remedy("jitter", preset)

    def _finish(self, channel: int, label: str, watch: _Watch, *, freed: bool, now: float) -> None:
        self._watch.pop(channel, None)
        if not watch.attempts or watch.raised:
            return
        self._record({"kind": "stuck_outcome", "channel": label, "freed": freed,
                      "attempts": list(watch.attempts), "seconds": round(now - watch.since, 1)})
        runtime_stats = getattr(self.gc, "runtime_stats", None)
        if freed and runtime_stats is not None:
            wall = time.time()
            runtime_stats.recordAutoResolvedIncident(
                {"kind": KIND, "subject": label, "attempts": list(watch.attempts),
                 "triggered_at": wall - (now - watch.since), "resolved_at": wall},
                resolved_by="auto",
            )

    @staticmethod
    def _record(event: dict[str, Any]) -> None:
        try:
            import control_data_store

            control_data_store.record({"type": "event", "t": time.time(), "mono": time.monotonic(), **event})
        except Exception:
            pass


def jitterSeconds(amplitude_steps: int, cycles: int, speed: int, acceleration: int) -> float:
    """How long a jitter takes, generously: each stroke a trapezoidal move (a
    triangular one when it never reaches speed), out and back per cycle."""
    accel = max(acceleration, 1)
    accel_distance = (speed * speed) / (2.0 * accel)
    if 2.0 * accel_distance >= amplitude_steps:
        stroke_s = 2.0 * math.sqrt(max(amplitude_steps, 1) / accel)
    else:
        stroke_s = 2.0 * (speed / accel) + (amplitude_steps - 2.0 * accel_distance) / speed
    return cycles * 2 * (stroke_s + 0.001)
