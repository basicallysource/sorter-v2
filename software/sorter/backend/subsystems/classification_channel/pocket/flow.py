"""The classification channel's flow for a rotor whose fins make fixed pockets.

The rotor is a floor with fins on it, turning inside a fixed wall: a piece rides
where it lies in its pocket, or slides back until the fin behind pushes it. The
wall is open over the exit, and a piece falls when it is carried into the
opening. The rotor only ever rests in one pose: a fin standing on the far edge
of the opening, walling it off from the pocket pieces drop into. In travel
order the pockets at rest are then RECEIVE (pieces land here), the QUEUE
pockets, and EXIT, which lies over the opening.

Where in the EXIT pocket a piece falls depends on where it lay in its pocket:
toward the front it falls as the pocket turns in, at the back it waits by the
pushing fin and falls on the next turn, when that fin sweeps the whole pocket
across the opening and ends as the fin that walls it off. The camera cannot see
all of the exit, so the flow does not look there. It needs two things instead:

  one piece at a time through the exit. A piece is admitted only when the
  pocket ahead of it is empty, so pieces ride with an empty pocket between
  them, and the pocket behind a piece is empty for the two turns it takes that
  piece to be surely out.

  a look at the RECEIVE pocket right after the sweep. The swept pocket's piece
  can only be gone or have been carried round past the opening into RECEIVE,
  where the camera sees well and the feeder has had no chance to add one. Empty
  means it fell, and only then is it counted as dropped.

Every turn that drops a piece goes first only as far as it takes that piece
into the opening, looks, and shakes it there if it is still on the rotor; then
the turn is finished. The rotor never turns back. Every move is one fin pitch
forward in all. The chute is aimed for a piece before the
turn that takes it into the EXIT pocket and stays on it until it is counted as
dropped. Which pocket holds which piece is the flow's own record, moved one
pocket per turn; the camera adds pieces to it and is evidence, never the truth.
Two pieces in one pocket go to the discard together.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import replace
from enum import Enum
from typing import Optional

from defs.known_object import ClassificationStatus, notePieceProblem
from runtime_stats import C4_WAITING_FOR_PIECE
from subsystems.classification_channel.five_sector_platter import C4FiveSectorPlatter
from subsystems.classification_channel.two_piece.channel_clear import (
    ChannelClearResult,
    _advanceOneStep,
    channelOccupied,
    openAllLayerDoors,
    routeSweep,
)
from subsystems.classification_channel.two_piece.constants import C4_TRAVEL_SIGN
from subsystems.classification_channel.two_piece.flow import (
    _ZONE_DROP,
    _ZONE_PRECISE,
    TwoPieceClassificationChannel,
    _TrackedPiece,
)

LOG_TAG = "[C4-POCKET]"

# After a turn the camera gets this long, and this many frames, to show whether
# a swept piece was carried round into the RECEIVE pocket.
_LOOK_S = 0.3
_LOOK_FRAMES = 3
# A piece that is still on the channel after its pocket crossed the opening
# stuck to the rotor (a tire's rubber grips it): it rides round into the
# RECEIVE pocket as the piece it is, and is shaken harder on its next pass.
# After this many passes the channel stops for the stall watchdog, which
# clears the whole channel with shakes or asks for help.
_CARRY_MAX = 4
# Every turn that drops a piece first turns only as far as it takes that piece
# this far into the opening, then looks whether it fell. A piece still there is
# turned _PUSH_DEG further and looked at again, as deep as the opening goes
# (short of its far edge by _FAR_MARGIN_DEG) and the piece behind allows; only
# there is it shaken, up to _CHECK_SHAKES times (more for one that rode round
# before), before the turn is finished. A piece the turn ends before taking that
# deep is left for the next turn, not shaken. The rotor never turns back.
_FALL_IN_DEG = 30.0
_PUSH_DEG = 10.0
_FAR_MARGIN_DEG = 8.0
# The opening's width when the zones do not say.
_OPENING_DEG = 58.0
# The next piece is kept at least this far short of the opening while the one
# ahead of it is taken in.
_NEXT_MARGIN_DEG = 8.0
_CHECK_SHAKES = 3
# Most pieces fall while the rotor is still turning them in: this many frames in
# a row taken after the move with nothing where the piece should be, and it fell.
_GONE_FRAMES = 3
# A piece takes this long to slide off once it is over the opening: the look
# waits for it before taking the piece for one that stayed.
_CHECK_S = 0.6
_CHECK_SETTLE_S = 0.35
# A piece within this of where the dropping piece should be is taken for it.
_CHECK_NEAR_DEG = 14.0
# A piece that slid back in its pocket as the rotor turned sits short of where it
# was aimed, as far back as this: it is still this piece, and is turned on until
# its middle is where it was aimed (the middle of the opening), within
# _CHECK_CENTER_TOL_DEG.
_CHECK_SHORT_DEG = 40.0
_CHECK_CENTER_TOL_DEG = 4.0
# Pieces in two pockets at least this far apart are dropped one at a time with
# the chute aimed for each; closer, they fall together and go to the discard.
# Two in one pocket are always a double drop.
_SPLIT_MIN_DEG = 22.0
_SHAKE_PARTS = 3
_SHAKE_ROTOR_DEG = 6.0
_SHAKE_CYCLES = 8
# The firmware can report "stopped" before a move it was just given starts.
_START_GRACE_S = 0.15
# A box must be in this many frames in a row to become a piece.
_NEW_FRAMES = 3
# Two boxes this close are one piece drawn twice, not two pieces.
_SAME_PIECE_DEG = 8.0
# A box in the RECEIVE pocket that was never photographed and is gone this long
# was not a piece.
_UNSEEN_DROP_S = 0.7
# With no new piece for this long, the pieces already on the channel move on.
_FLUSH_AFTER_S = 6.0
# The fins within this of the rest pose are at rest; further off, the rotor is
# turned to it (steps were lost, or it was moved by hand).
_ALIGN_TOL_DEG = 2.0
# A piece C3 lets go lands on this channel within this long.
_C3_LANDING_S = 1.5
# Turned back toward rest by at most this while the RECEIVE pocket holds a
# piece: further back, that piece is carried toward the opening.
_BACK_WITH_PIECE_DEG = 8.0
# Distribution must see its slot empty before a piece that was taken back is
# handed to it again: handed back at once, it still reads as the piece the
# chute is already on, and the chute never moves to where the piece goes now.
_HAND_BACK_AFTER_S = 0.5
# A piece handed to distribution whose chute is not on it after this long is
# taken back and handed over again.
_AIM_TIMEOUT_S = 8.0
# With pieces on the channel and nothing happening for this long, the channel
# is cleared (the stall watchdog's own wait is for the other flows).
STALL_AFTER_MS = 15000.0
# Clearing the channel: every pocket goes across the opening with shakes, for
# this many turns of the rotor, harder each turn. Only a piece that stays
# through all of it is left for a person.
_CLEAR_SHAKE_LAPS = 2
# The fins are read after every turn that could have lost steps (a shake, a
# piece going round again, a correction, a start), and otherwise after every
# this many turns.
_VERIFY_EVERY = 4
# Fin readings that keep disagreeing are given up on after this many.
_VERIFY_READS_MAX = 4
# A longer gap between steps means the machine was paused or held.
_RESUME_GAP_S = 1.0


class _P(Enum):
    VERIFY = "verify"
    CORRECT = "correct"
    REST = "rest"
    AIM = "aim"
    TURN = "turn"
    CHECK = "check"
    LOOK = "look"
    COMMIT = "commit"


# What the runtime stats call the channel's state.
_PHASE_NAMES = {
    _P.REST: "waiting",
    _P.AIM: "staging",
    _P.TURN: "ejecting",
    _P.CHECK: "ejecting",
    _P.LOOK: "ejecting",
    _P.COMMIT: "ejecting",
    _P.VERIFY: "staging",
    _P.CORRECT: "staging",
}


class PocketClassificationChannel(TwoPieceClassificationChannel):
    """The pocket flow. It takes the two-piece flow's piece handling (photos,
    identification, the hand-over to distribution) and none of its motion."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cfg = self.ctx.config
        self._n = max(3, int(cfg.fin_count))
        self._pitch_deg = 360.0 / self._n
        # pockets[0] is RECEIVE, pockets[-1] is EXIT.
        self._pockets: list[list[_TrackedPiece]] = [[] for _ in range(self._n)]
        # The EXIT pocket's pieces after the turn that swept it, until the look.
        self._swept: list[_TrackedPiece] = []
        # Pieces gone at the opening out of the last queue pocket, which rode
        # into the EXIT pocket with the turn: dropped once it is seen empty.
        self._exit_pending: list[_TrackedPiece] = []
        self._exit_frames = 0
        # The RECEIVE pocket's pieces and where they lay as a turn began: one
        # still lying there after the turn did not ride the rotor, it hangs off
        # C3's exit. Frames after the turn that showed it there.
        self._receive_before: list[tuple[_TrackedPiece, tuple[int, int, int, int]]] = []
        self._held_seen: dict[int, int] = {}
        self._members: list[_TrackedPiece] = []
        self._pp = _P.VERIFY
        self._started = False
        self._halted = False
        self._taken_back_at = float("-inf")
        self._cycle_started_mono = float("-inf")
        self._check_tp: Optional[_TrackedPiece] = None
        self._check_group: list[_TrackedPiece] = []
        self._targets: list[list[_TrackedPiece]] = []
        self._planning = False
        self._turned_deg = 0.0
        self._check_gap = 0.0
        self._check_short = 0.0
        self._check_room = 0.0
        self._check_turn_ends = False
        self._opening_deg = _OPENING_DEG
        self._check_shakes = 0
        self._check_shakes_max = _CHECK_SHAKES
        self._check_from = 0.0
        self._check_wall = 0.0
        self._check_frames = 0
        self._check_seen = 0
        self._check_empty = 0
        self._turns_since_verify = 0
        self._needs_verify = True
        self._serial = 0
        self._move_cmd_at = 0.0
        self._rest_since = 0.0
        self._rest_wall = 0.0
        self._last_state_ts = -1.0
        self._new_seen: dict[tuple[int, int], int] = {}
        self._merged: dict = {}
        self._doubt_frame_at = None
        # When the last piece off C3 was taken into the RECEIVE pocket.
        self._landed_at = float("-inf")
        # Boxes seen in the exit margin while the rotor stood still: something
        # that does not move with the rotor, never a piece it carries.
        self._margin_still: deque = deque(maxlen=60)
        self._cycle_start_pos: Optional[int] = None
        self._look_from = 0.0
        self._look_wall = 0.0
        self._look_frames = 0
        self._carry_frames = 0
        # A sweep made in parts: what is left of it ("shake", or microsteps to turn).
        self._sweep_steps: list = []
        self._shaking = False
        self._shake_cycles = _SHAKE_CYCLES
        self._aim_target: Optional[_TrackedPiece] = None
        self._after_aim_us = 0
        self._after_aim_back = False
        self._after_aim_phase = _P.TURN
        # A fin read off rest once: corrected only when a second reading agrees.
        self._off_seen: Optional[float] = None
        self._verify_reads = 0
        self._verify_thread: Optional[threading.Thread] = None
        self._verify_result: tuple[str, Optional[float]] = ("none", None)
        self._paused_mid_cycle = False
        self._geometry_error_logged = False
        self._fins: list[float] = []
        self._pitch_us = 0
        self._per_deg = 1.0
        self._loadGeometry()
        self._releaseBucket("pocket flow start")

    # ---------------------------------------------------------------- geometry

    def _loadGeometry(self) -> bool:
        """Where the fins rest, as gaps to the exit zone's entry edge (the measure
        the camera gives every piece), and one pitch in motor microsteps."""
        from subsystems.classification_channel.two_piece.spoke_home import _finOverExitAngle

        cfg = self.ctx.config
        try:
            from zones.store import loadChannel

            zones = loadChannel(4)
            target = _finOverExitAngle(cfg)
            if zones is None or target is None:
                raise ValueError("the classification channel's zones are not saved")
            block = (360.0 - float(zones.exit.width) - float(cfg.fin_width_deg) / 2.0) % 360.0
            perception = getattr(self.gc, "perception_service", None)
            channel = perception.channel_def(4) if perception is not None else None
            if channel is not None:
                # The same sums the camera's gaps are made with.
                from perception.arcs import _orderedCircularSections, exitOnlySections
                from perception.channel import SECTION_DEG

                ordered = _orderedCircularSections(exitOnlySections(channel))
                if ordered:
                    reverse = bool(getattr(channel, "reverse", False))
                    entry = float(ordered[-1] if reverse else ordered[0]) * SECTION_DEG
                    fin_rel = (float(target[0]) - float(channel.radius1_angle_image)) % 360.0
                    block = (fin_rel - entry) % 360.0 if reverse else (entry - fin_rel) % 360.0
            self._fins = sorted((block - k * self._pitch_deg) % 360.0 for k in range(self._n))
            self._opening_deg = float(zones.exit.width)
            platter = C4FiveSectorPlatter.from_irl_config(self.irl_config)
            per_rev = float(platter.motor_microsteps_per_output_revolution)
            self._per_deg = per_rev / 360.0
            self._pitch_us = int(round(per_rev / self._n))
            self.logger.info(
                f"{LOG_TAG} {self._n} pockets of {self._pitch_deg:.1f}°, one piece through the exit at a time"
            )
            return True
        except Exception as exc:
            if not self._geometry_error_logged:
                self._geometry_error_logged = True
                self.logger.error(f"{LOG_TAG} cannot work out the pockets ({exc}); the channel will not run")
            self._fins = []
            return False

    def _station(self, gap: Optional[float]) -> Optional[int]:
        """Which pocket a piece this far from the exit zone's entry is in, at
        rest: 0 is RECEIVE, the last is EXIT."""
        if gap is None or not self._fins:
            return None
        gap = float(gap)
        if gap < 0.0:
            return self._n - 1
        below = sum(1 for fin in self._fins if fin <= gap)
        if below >= self._n:
            return self._n - 1  # Past the fin that walls the opening off: at the opening
        return (self._n - 1) - below

    # ------------------------------------------------------------- watchdog API

    def phaseName(self) -> str:
        if self._pp == _P.REST and self.shared.classification_ready:
            return C4_WAITING_FOR_PIECE
        return _PHASE_NAMES[self._pp]

    @property
    def stall_after_ms(self) -> float:
        return STALL_AFTER_MS

    @property
    def holds_piece(self) -> bool:
        """Stopped on a piece that would not leave, seen or not: the stall
        watchdog then raises its incident even when the camera sees nothing
        (the piece hides at the opening)."""
        return self._halted and any(self._pockets)

    def attemptStallAutoClear(self, *, max_output_deg: float) -> ChannelClearResult:
        """Clear the channel into the discard: every pocket across the opening
        with shakes while it is over it, harder on each turn of the rotor. A
        piece is only left for a person after the machine has tried to shake
        it off."""
        shaken_deg = 0.0
        hidden = self._halted
        if hidden or channelOccupied(self.gc) is not False:
            try:
                routeSweep(self.gc, self.irl, LOG_TAG)
            except Exception as exc:
                self.logger.warning(f"{LOG_TAG} channel clear: routing the sweep failed ({exc}); opening every door")
                openAllLayerDoors(self.gc, self.irl, LOG_TAG)
            shaken_deg = self._shakeOut(full=hidden)
        after = super().attemptStallAutoClear(max_output_deg=self._pitch_deg)
        result = ChannelClearResult(
            after.cleared, after.occupied_at_start or shaken_deg > 0, shaken_deg + after.output_deg_moved, after.reason
        )
        if result.cleared:
            self._pockets = [[] for _ in range(self._n)]
            self._swept = []
            self._members = []
            self._aim_target = None
            self._halted = False
            self._started = False  # The sweep left the rotor anywhere: find rest again
            self._last_step_at = None
        return result

    def _shakeOut(self, full: bool = False) -> float:
        """Turn the rotor with a shake before each part of every pocket's sweep
        across the opening, until the camera sees the channel empty. Blocking.
        Returns the output degrees turned."""
        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is None or not self._fins:
            return 0.0
        cfg = self.ctx.config
        speed = int(cfg.rotate_speed_usteps_per_s)
        amplitude = max(1, int(round(_SHAKE_ROTOR_DEG * self._per_deg)))
        part = self._pitch_us // _SHAKE_PARTS
        parts = [part] * (_SHAKE_PARTS - 1) + [self._pitch_us - part * (_SHAKE_PARTS - 1)]
        turned = 0.0
        for lap in range(1, _CLEAR_SHAKE_LAPS + 1):
            self.logger.warning(
                f"{LOG_TAG} channel clear: every pocket across the opening with shakes (turn {lap} of {_CLEAR_SHAKE_LAPS})"
            )
            for _pocket in range(self._n):
                for microsteps in parts:
                    try:
                        stepper.jitter(
                            amplitude,
                            _SHAKE_CYCLES * lap,
                            int(cfg.jitter_speed_usteps_per_s),
                            int(cfg.jitter_accel_usteps_per_s2),
                        )
                        deadline = time.monotonic() + 5.0
                        time.sleep(_START_GRACE_S)
                        while stepper.is_jittering() and time.monotonic() < deadline:
                            time.sleep(0.02)
                    except Exception as exc:
                        self.logger.warning(f"{LOG_TAG} channel clear: shake failed: {exc}")
                    if not _advanceOneStep(stepper, int(C4_TRAVEL_SIGN) * microsteps, speed):
                        self.logger.warning(f"{LOG_TAG} channel clear: a turn was not acknowledged")
                        return turned
                    turned += microsteps / self._per_deg
                # A piece out of sight does not count as gone: the shakes run
                # their full laps for it.
                if not full and channelOccupied(self.gc) is False:
                    self.logger.info(f"{LOG_TAG} channel clear: the channel is empty")
                    return turned
        return turned

    def _takeBack(self, tp: _TrackedPiece) -> None:
        """Take a piece back from distribution, which was aiming the chute for it."""
        self.transport.clearPieceForDistribution(tp.known_object)
        self._unplace(tp)
        self._taken_back_at = time.monotonic()

    def pause(self) -> None:
        self.transport.clearPieceForDistribution()
        self._taken_back_at = time.monotonic()
        for tp in self._pieces.values():
            if tp.placed and not tp.ejected:
                self._unplace(tp)
        self._paused_mid_cycle = self._pp in (_P.AIM, _P.TURN, _P.CHECK)
        self._cycles.drop()
        self._was_ready = False
        self._ready_since = None
        self.last_progress_at = time.monotonic()

    def cleanup(self) -> None:
        super().cleanup()
        self._pockets = [[] for _ in range(self._n)]
        self._swept = []
        self._members = []
        self._aim_target = None
        self._new_seen = {}
        self._started = False
        self._halted = False
        self._paused_mid_cycle = False
        self._pp = _P.VERIFY

    # --------------------------------------------------------------------- step

    def step(self) -> None:
        perception_service = getattr(self.gc, "perception_service", None)
        stepper = getattr(self.irl, "carousel_stepper", None)
        if perception_service is None or stepper is None:
            return
        if not self._fins and not self._loadGeometry():
            self.setClassificationReady(False, "pockets unknown")
            return
        state = perception_service.read_state(4)
        now = time.monotonic()
        if self._last_step_at is None or now - self._last_step_at > _RESUME_GAP_S:
            self._afterGap(stepper, now)
        self._last_step_at = now
        moving = (now - self._move_cmd_at) < _START_GRACE_S or not bool(getattr(stepper, "stopped", True))

        self._applyResults(now)
        handler = {
            _P.VERIFY: self._verify,
            _P.CORRECT: self._correct,
            _P.REST: self._rest,
            _P.AIM: self._aim,
            _P.TURN: self._turn,
            _P.CHECK: self._check,
            _P.LOOK: self._look,
            _P.COMMIT: self._commit,
        }[self._pp]
        handler(state, perception_service, stepper, now, moving)

        ready = self._pp == _P.REST and not moving and self._admits(state)
        self.setClassificationReady(ready, "at rest, room for a piece")
        if not ready:
            self._ready_since = None
        elif self._ready_since is None:
            self._ready_since = now
        self._recordCycle(perception_service, state, ready)

    def _admits(self, state) -> bool:
        """Whether the feeder may add a piece now: the RECEIVE pocket is empty,
        so is the pocket ahead of it (pieces ride an empty pocket apart), and no
        piece is in the EXIT pocket waiting for the turn that sweeps it."""
        if self._halted or self._pockets[0] or self._pockets[1] or self._pockets[-1]:
            return False
        return not any(
            self._station(po.com_forward_to_exit_deg) == 0 for po in getattr(state, "pieces", ())
        )

    def _enter(self, phase: _P) -> None:
        if phase != self._pp:
            self.logger.info(f"{LOG_TAG} {self._pp.value} -> {phase.value}  [{self._pocketsText()}]")
        self._pp = phase

    def _pocketsText(self) -> str:
        names = ["receive"] + [f"queue {i}" for i in range(1, self._n - 1)] + ["exit"]
        return ", ".join(
            f"{name}: {'+'.join(str(tp.track_id) for tp in pocket) or '-'}"
            for name, pocket in zip(names, self._pockets)
        )

    def _afterGap(self, stepper, now: float) -> None:
        """The first step, or the first after a pause or a hold."""
        # Hands may have moved the rotor meanwhile: the fins are read again.
        self._needs_verify = True
        self._receive_before = []
        for tp in self._pieces.values():
            tp.last_seen = now
            if tp.known_object is not None:
                tp.worker.emitKnownObject()
        self._ready_since = None
        self.last_progress_at = now
        self._new_seen = {}
        self._sweep_steps = []
        self._targets = []
        self._planning = False
        self._check_tp = None
        self._shaking = False
        if not self._started:
            self._started = True
            self._paused_mid_cycle = False
            self._startVerify(now)
            return
        self.logger.info(f"{LOG_TAG} resumed  [{self._pocketsText()}]")
        # Pieces swept out before the stop but not yet counted: they fell where
        # the chute stood for them.
        for tp in self._swept + self._members:
            self._place(tp)
            self._commitToDistribution(tp)
        for tp in list(self._swept + self._members):
            self._forget(tp)
        if not self._paused_mid_cycle:
            self._startVerify(now)
            return
        # Stopped part way through a turn: whether the pieces at the exit fell,
        # and into what, is not known. They go to the discard, and the turn is
        # finished from where the motor stands.
        self._paused_mid_cycle = False
        for tp in self._pockets[-1] + self._pockets[-2]:
            self._toDiscard(
                tp,
                "interrupted",
                "The machine stopped while the classification channel was turning it toward the "
                "exit, so where it fell is not known; it went to the discard.",
            )
        done = 0
        if self._cycle_start_pos is not None:
            done = abs(int(stepper.position) - int(self._cycle_start_pos))
        lead = (self._pockets[-1] or self._pockets[-2] or [None])[0]
        self._aimThen(lead, max(0, self._pitch_us - done), _P.TURN, now)

    # ------------------------------------------------------------ what is seen

    def _fresh(self, state, since_wall: float) -> bool:
        """A frame taken since `since_wall` that has not been read yet."""
        ts = float(getattr(state, "ts", 0.0) or 0.0)
        if ts <= since_wall or ts == self._last_state_ts:
            return False
        self._last_state_ts = ts
        return True

    def _observeAtRest(self, state, now: float) -> None:
        """Match the frame's boxes to the pockets' records and add the pieces
        that have newly landed."""
        self._noteMarginStill(state)
        by_id = {tp.track_id: tp for pocket in self._pockets for tp in pocket}
        # The boxes the camera fused into one (it draws them as one "merged" piece).
        self._merged = {
            tuple(int(v) for v in box): tuple(tuple(int(v) for v in b) for b in members)
            for box, members in getattr(state, "merged", ())
        }
        matched: set[int] = set()
        unmatched: list[tuple[int, object]] = []
        for po in getattr(state, "pieces", ()):
            tid = po.sv_bt_track_id
            station = self._station(po.com_forward_to_exit_deg)
            if tid is None or station is None:
                continue
            tp = by_id.get(tid)
            if tp is None:
                unmatched.append((station, po))
                continue
            self._seen(tp, po, now)
            matched.add(id(tp))
        seen_now: set[tuple[int, int]] = set()
        for station, po in unmatched:
            pocket = self._pockets[station]
            gap = float(po.com_forward_to_exit_deg)
            # The tracker gave a piece a new id: the record in this pocket that
            # is not in the frame takes it. (Wherever in the pocket: the turn
            # that brought it here moved it, and the tracker often renames a
            # piece it saw move that far.)
            lost = next((tp for tp in pocket if id(tp) not in matched), None)
            if lost is not None:
                self.logger.info(f"{LOG_TAG} track={lost.track_id} is now track={po.sv_bt_track_id}")
                lost.track_id = int(po.sv_bt_track_id)
                self._seen(lost, po, now)
                matched.add(id(lost))
                continue
            if any(
                tp.gap_to_exit is not None and abs(float(tp.gap_to_exit) - gap) <= _SAME_PIECE_DEG
                for tp in pocket
            ):
                continue  # One piece drawn twice
            key = (station, int(po.sv_bt_track_id))
            seen_now.add(key)
            count = self._new_seen.get(key, 0) + 1
            self._new_seen[key] = count
            if count >= _NEW_FRAMES:
                self._newPiece(station, po, now)
                self._new_seen.pop(key, None)
        self._new_seen = {key: n for key, n in self._new_seen.items() if key in seen_now}
        # A piece that hung off C3 and is gone from RECEIVE went back onto C3.
        for tp in list(self._pockets[0]):
            if getattr(tp, "held_from_above", False) and (now - tp.last_seen) > _UNSEEN_DROP_S:
                self.logger.info(f"{LOG_TAG} track={tp.track_id} that hung off C3 is gone from the receive pocket: back on C3")
                tp.worker.abandonInFlightObject("went back onto C3")
                self._forget(tp)
        # A box in RECEIVE that never became a photographed piece and is gone.
        for tp in list(self._pockets[0]):
            if not tp.capture_done and (now - tp.last_seen) > _UNSEEN_DROP_S:
                self.logger.info(f"{LOG_TAG} track={tp.track_id} left the receive pocket unphotographed; dropped")
                tp.worker.abandonInFlightObject("gone from the receive pocket before it was photographed")
                self._forget(tp)

    def _noteMarginStill(self, state) -> None:
        for po in getattr(state, "margin_pieces", ()):
            self._margin_still.append(tuple(int(v) for v in po.bbox))

    def _stillInMargin(self, bbox) -> bool:
        """Whether a box in the exit margin is where one stood while the rotor
        stood still: the opening's own shadows and edges, not a piece."""
        return any(_iou(bbox, still) > 0.5 for still in self._margin_still)

    def _seen(self, tp: _TrackedPiece, po, now: float) -> None:
        b = po.bbox
        tp.bbox = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
        tp.boxes = self._merged.get(tp.bbox, (tp.bbox,))
        if tp.zone == _ZONE_DROP:
            # At rest in the RECEIVE pocket: how often it is drawn as more than one.
            tp.rest_boxes.append(tp.boxes)
            tp.rest_frames = getattr(tp, "rest_frames", 0) + 1
            if len(tp.boxes) > 1:
                tp.merged_frames = getattr(tp, "merged_frames", 0) + 1
        tp.gap_to_exit = po.com_forward_to_exit_deg
        tp.last_seen = now

    def _newPiece(self, station: int, po, now: float) -> None:
        pocket = self._pockets[station]
        self._serial += 1
        tp = self._createPiece(-self._serial, now)  # Keyed apart from track ids
        tp.track_id = int(po.sv_bt_track_id)
        self._seen(tp, po, now)
        # The inherited photographing takes pieces "in the drop zone": here that
        # is the RECEIVE pocket and nowhere else.
        tp.zone = _ZONE_DROP if station == 0 else _ZONE_PRECISE
        if station == 0:
            self._landed_at = now
        others = list(pocket)
        pocket.append(tp)
        if others:
            # Two pieces in one pocket came off C3 together: a double drop, however
            # far apart they lie.
            self._multi_drop_seq += 1
            for member in pocket:
                self._toDiscard(
                    member,
                    "double_feed",
                    "Two pieces were in one pocket of the classification channel: they came off C3 "
                    "together, a double drop. Both went to the discard.",
                    group=self._multi_drop_seq,
                )
            return
        if station != 0:
            # Seen first past the pocket pieces land in: it arrived unseen, beside
            # or behind another piece, so it counts as a double drop.
            self._toDiscard(
                tp,
                "stray",
                "The camera first saw it in a pocket past the one pieces land in, so it was never "
                "photographed or identified; it came off C3 unseen, a double drop, and went to the discard.",
            )
            self.logger.warning(f"{LOG_TAG} track={tp.track_id} appeared in pocket {station}, unphotographed -> discard")

    def _toDiscard(self, tp: _TrackedPiece, kind: str, message: str, group: Optional[int] = None) -> None:
        if tp.double_feed:
            return
        if group is None:
            self._multi_drop_seq += 1
            group = self._multi_drop_seq
        if tp.placed and not tp.ejected:
            self._takeBack(tp)
        self.logger.warning(f"{LOG_TAG} track={tp.track_id} -> discard ({kind})")
        self._markDoubleFeed(tp, group, kind, message)
        if kind != "interrupted":
            self._recordDoubt(tp, kind)

    def _recordDoubt(self, tp: _TrackedPiece, kind: str) -> None:
        """Keep the camera's frame of a piece that may not be one piece, with its
        boxes, as a sample (capture reason "maybe_multiple") that goes to Hive
        with the machine's other samples, so what it was can be labelled and
        trained on later. One frame is kept once, however many pieces it shows."""
        vision = getattr(self, "vision", None)
        role, capture = None, None
        if vision is not None and hasattr(vision, "getCaptureThreadForRole"):
            for role in ("classification_channel", "carousel"):
                capture = vision.getCaptureThreadForRole(role)
                if capture is not None:
                    break
        frame = getattr(capture, "latest_frame", None) if capture is not None else None
        if frame is None:
            return
        stamp = getattr(frame, "timestamp", None)
        if stamp is not None and stamp == self._doubt_frame_at:
            return
        self._doubt_frame_at = stamp
        obj = tp.known_object
        doubt = {
            "kind": kind,
            "piece_uuid": getattr(obj, "uuid", None),
            "part_id": getattr(obj, "part_id", None),
            "track_id": tp.track_id,
            "pocket": next((i for i, pocket in enumerate(self._pockets) if tp in pocket), None),
            "rest_frames": getattr(tp, "rest_frames", 0),
            "merged_frames": getattr(tp, "merged_frames", 0),
            "bbox": [int(v) for v in tp.bbox],
            "boxes": [[int(v) for v in box] for box in (tp.boxes or ())],
            "rest_boxes": [[[int(v) for v in box] for box in boxes] for boxes in list(tp.rest_boxes)[-8:]],
        }

        def save() -> None:
            try:
                import sample_store
                from sample_ingest import buildSample

                sample = buildSample(self.gc, role, capture, frame, annotate=False)
                if sample is None:
                    return
                jpeg, row = sample
                row["meta"]["capture_reason"] = "maybe_multiple"
                row["meta"]["piece_doubt"] = doubt
                sample_store.enqueue(jpeg, row)
            except Exception as exc:
                self.logger.warning(f"{LOG_TAG} keeping the frame of track={doubt['track_id']} failed: {exc}")

        threading.Thread(target=save, daemon=True, name="c4-doubt-frame").start()

    def _forget(self, tp: _TrackedPiece) -> None:
        for pocket in self._pockets:
            if tp in pocket:
                pocket.remove(tp)
        for group in (self._members, self._swept):
            if tp in group:
                group.remove(tp)
        for key in [key for key, value in self._pieces.items() if value is tp]:
            self._pieces.pop(key, None)

    # --------------------------------------------------------------------- REST

    def _rest(self, state, perception_service, stepper, now: float, moving: bool) -> None:
        if moving:
            return
        if self._fresh(state, self._rest_wall):
            self._observeAtRest(state, now)
        self._captureDropPieces(perception_service, now)
        self._maybeStartCycle(stepper, now)

    def _maybeStartCycle(self, stepper, now: float) -> None:
        receive, ahead, last_queue, exit_ = self._pockets[0], self._pockets[1], self._pockets[-2], self._pockets[-1]
        if self._halted or not any(self._pockets):
            return
        # Every piece this turn can drop, nearest the opening first. Two too
        # close to part fall together: both go to the discard.
        going = sorted(
            exit_ + last_queue,
            key=lambda tp: float(tp.gap_to_exit) if tp.gap_to_exit is not None else -1e9,
        )
        for a, b in zip(going, going[1:]):
            if a.gap_to_exit is None or b.gap_to_exit is None or float(b.gap_to_exit) - float(a.gap_to_exit) < _SPLIT_MIN_DEG:
                self._multi_drop_seq += 1
                for tp in (a, b):
                    self._toDiscard(
                        tp,
                        "together",
                        "It reached the classification channel's exit right beside another piece, too "
                        "close to drop on its own, so the two fell together; both went to the discard.",
                        group=self._multi_drop_seq,
                    )
        # The piece this turn drops first needs the chute on it. The chute goes
        # there now, while a piece that has just landed is photographed: the
        # rotor stands still either way. A turn that takes no piece into the
        # opening does not wait for it: the chute moves while the rotor turns.
        reaches = any(tp.gap_to_exit is None or float(tp.gap_to_exit) < self._pitch_deg - 0.5 for tp in going)
        if going and going[0].result_applied:
            self._aimedFor(going[0])
        chute_on = not reaches or (all(tp.result_applied for tp in going) and self._aimedFor(going[0]))
        if receive:
            if not all(tp.capture_done for tp in receive):
                return  # Still being photographed
            need = int(getattr(self.ctx.config, "merged_double_drop_frames", 0) or 0)
            for tp in receive:
                frames = getattr(tp, "rest_frames", 0)
                merged = getattr(tp, "merged_frames", 0)
                if tp.double_feed or merged == 0:
                    continue
                if need > 0 and merged >= need:
                    self._toDiscard(
                        tp,
                        "merged",
                        f"The camera drew it as more than one piece lying together in the receive pocket "
                        f"({merged} of {frames} frames), so it went to the discard as a double drop.",
                    )
                elif not getattr(tp, "doubt_recorded", False):
                    # Two pieces, an assembly, or one oddly shaped piece: it
                    # sorts as one, and its frame is kept to be labelled.
                    tp.doubt_recorded = True
                    self.logger.info(
                        f"{LOG_TAG} track={tp.track_id} drawn as more than one box ({merged} of {frames} frames): "
                        "maybe multiple, sorted as one piece, frame kept"
                    )
                    notePieceProblem(
                        tp.known_object,
                        "maybe_multiple",
                        f"The camera drew it as more than one box in {merged} of {frames} frames at rest: two "
                        "pieces, an assembly or one oddly shaped piece. It was sorted as one piece, and its "
                        "frame was kept so what it was can be labelled.",
                    )
                    self._recordDoubt(tp, "merged")
        elif not ahead and not exit_ and (now - self._rest_since) < _FLUSH_AFTER_S:
            return  # The feeder may add a piece: it gets its chance first
        if not chute_on:
            return  # Not identified yet, or the chute is not on it yet
        self._cycle_start_pos = int(stepper.position)
        self._cycle_started_mono = now
        self.noteProgress()
        try:
            self._cycles.rotated(time.time(), ejecting=bool(exit_))
        except Exception:
            pass
        # The turn is made piece by piece: as far as each takes it into the
        # opening, a look, the chute aimed for the next; then the rest of it.
        self._targets = []
        for tp in going:
            if tp.gap_to_exit is None:
                self._targets = []
                break
            if self._targets and tp.double_feed and self._targets[-1][0].double_feed and float(tp.gap_to_exit) - float(self._targets[-1][0].gap_to_exit) < _SPLIT_MIN_DEG:
                self._targets[-1].append(tp)  # Falls with the one beside it
            else:
                self._targets.append([tp])
        self._receive_before = [(tp, tuple(int(v) for v in tp.bbox)) for tp in receive if any(tp.bbox)]
        self._planning = True
        self._turned_deg = 0.0
        self._sweep_steps = []
        self._check_tp = None
        self._enter(_P.TURN)

    def _planNext(self) -> None:
        """The next part of the turn: up to the next piece's drop and a look at
        it, with the chute aimed for it first; or, with none left that this
        turn reaches, the rest of the turn."""
        while self._targets:
            group = self._targets[0]
            lead = group[0]
            if not any(lead in pocket for pocket in self._pockets):
                self._targets.pop(0)  # Already fell
                continue
            # As deep as the piece may go: short of the opening's far edge, and
            # no further in than leaves the next piece short of the opening.
            deepest = max(_NEXT_MARGIN_DEG, self._opening_deg - _FAR_MARGIN_DEG)
            behind = [g[0] for g in self._targets[1:]]
            if behind:
                deepest = min(deepest, float(behind[0].gap_to_exit) - float(lead.gap_to_exit) - _NEXT_MARGIN_DEG)
                deepest = max(deepest, _NEXT_MARGIN_DEG)
            fall_in = min(_FALL_IN_DEG, deepest)
            left = self._pitch_deg - self._turned_deg
            gap = float(lead.gap_to_exit) - self._turned_deg
            if gap >= left - 0.5:
                self._targets = []  # It reaches the opening on a later turn
                break
            # Into the opening, at most to the end of the turn: a piece that is
            # only just in at rest is looked at there, and is the first the
            # next turn drops.
            need = min(max(0.0, gap + fall_in), left)
            furthest = min(max(0.0, gap + deepest), left)
            self._targets.pop(0)
            need_us = int(round(need * self._per_deg))
            self._check_tp = lead
            self._check_group = group
            self._check_gap = gap - need
            self._check_room = max(0.0, furthest - need)
            self._check_turn_ends = gap + deepest > left + 0.5
            self._check_shakes_max = _CHECK_SHAKES + getattr(lead, "carried", 0)
            self._check_shakes = 0
            self._turned_deg += need
            self._sweep_steps = ["aim"] + ([need_us] if need_us > 0 else []) + ["check"]
            return
        rest_us = self._pitch_us - int(round(self._turned_deg * self._per_deg))
        self._sweep_steps = [rest_us] if rest_us > 0 else []
        self._planning = False

    # -------------------------------------------------------------------- moves

    def _move(self, stepper, microsteps: int, speed: int, now: float, what: str, back: bool = False) -> None:
        microsteps = int(microsteps)
        if microsteps <= 0:
            return
        try:
            stepper.set_speed_limits(16, max(16, int(speed)))
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} set_speed_limits failed: {exc}")
        self.logger.info(f"{LOG_TAG} {what}: {microsteps / self._per_deg:.1f}°")
        direction = -int(C4_TRAVEL_SIGN) if back else int(C4_TRAVEL_SIGN)
        # The move carries its own acceleration: the motor puts its default
        # back before any move that does not.
        accel = int(getattr(self.ctx.config, "rotate_accel_usteps_per_s2", 0) or 0)
        kwargs = {"acceleration": accel} if accel > 0 else {}
        if not bool(stepper.move_steps(direction * microsteps, **kwargs)):
            self.logger.error(f"{LOG_TAG} {what} was not acknowledged")
        self._move_cmd_at = now

    # --------------------------------------------------------------- TURN, LOOK

    def _startShake(self, stepper, now: float) -> None:
        cfg = self.ctx.config
        amplitude = max(1, int(round(_SHAKE_ROTOR_DEG * self._per_deg)))
        self.logger.info(f"{LOG_TAG} shake: {_SHAKE_ROTOR_DEG:g}° at the rotor, {self._shake_cycles} times")
        try:
            stepper.jitter(
                amplitude, self._shake_cycles, int(cfg.jitter_speed_usteps_per_s), int(cfg.jitter_accel_usteps_per_s2)
            )
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} shake failed: {exc}")
        self._shaking = True
        self._needs_verify = True
        self._move_cmd_at = now

    def _turn(self, state, perception_service, stepper, now: float, moving: bool) -> None:
        if moving:
            return
        if self._shaking:
            try:
                if bool(stepper.is_jittering()):
                    return
            except Exception:
                pass
            self._shaking = False
        if not self._sweep_steps and self._planning:
            self._planNext()
        if self._sweep_steps and self._sweep_steps[0] == "aim":
            tp = self._check_tp
            if tp is not None and any(tp in pocket for pocket in self._pockets):
                if not tp.result_applied or not self._aimedFor(tp):
                    return
            self._sweep_steps.pop(0)
        if self._sweep_steps:
            step = self._sweep_steps.pop(0)
            if step == "shake":
                self._startShake(stepper, now)
            elif step == "check":
                self._startCheck(now)
            else:
                self._move(stepper, int(step), self.ctx.config.rotate_speed_usteps_per_s, now, "turn")
            return
        # One pocket on. The EXIT pocket was swept across the whole opening.
        self._swept = self._pockets[-1]
        self._pockets = [[]] + self._pockets[:-1]
        for index, pocket in enumerate(self._pockets):
            for tp in pocket:
                tp.zone = _ZONE_DROP if index == 0 else _ZONE_PRECISE
                if tp.gap_to_exit is not None:
                    tp.gap_to_exit = float(tp.gap_to_exit) - self._pitch_deg  # Until it is seen again
        rest = getattr(self.irl, "c4_fin_rest_microsteps", None)
        if rest is not None:
            self.irl.c4_fin_rest_microsteps = int(rest) + int(C4_TRAVEL_SIGN) * self._pitch_us
        self._cycle_start_pos = None
        self._look_from = now
        self._look_wall = time.time()
        self._look_frames = 0
        self._carry_frames = 0
        self._exit_frames = 0
        self._held_seen = {}
        self._exit_pending = [tp for tp in self._pockets[-1] if getattr(tp, "fell_pending", False)]
        self._new_seen = {}
        self._enter(_P.LOOK)

    def _startCheck(self, now: float) -> None:
        self._check_from = now
        self._check_wall = time.time()
        self._check_frames = 0
        self._check_seen = 0
        self._check_empty = 0
        self._check_short = 0.0
        self._enter(_P.CHECK)

    def _check(self, state, perception_service, stepper, now: float, moving: bool) -> None:
        """Part way through a turn, with the dropping piece where it should be
        in the opening: did it fall? Still there, it is shaken where it is;
        gone, it is counted as dropped into the bin the chute stands at."""
        if moving:
            return
        if self._shaking:
            try:
                if bool(stepper.is_jittering()):
                    return
            except Exception:
                pass
            self._shaking = False
            self._startCheck(now)
            return
        if self._fresh(state, self._check_wall):
            # On the channel, or hanging past its rim over the opening (the exit
            # margin), where the camera's boxes are not pieces but one that
            # moved there with the rotor is this piece.
            # Where it was aimed, or short of it: slid back in its pocket.
            offsets = [
                float(po.com_forward_to_exit_deg) - self._check_gap
                for po in getattr(state, "pieces", ())
                if po.com_forward_to_exit_deg is not None
            ] + [
                float(po.com_forward_to_exit_deg) - self._check_gap
                for po in getattr(state, "margin_pieces", ())
                if po.com_forward_to_exit_deg is not None and not self._stillInMargin(po.bbox)
            ]
            offsets = [off for off in offsets if -_CHECK_NEAR_DEG <= off <= _CHECK_SHORT_DEG]
            near = bool(offsets)
            self._check_empty = 0 if near else self._check_empty + 1
            # That it is still there counts only from after it has had time to
            # slide off.
            if float(getattr(state, "ts", 0.0) or 0.0) >= self._check_wall + _CHECK_SETTLE_S:
                self._check_frames += 1
                if near:
                    self._check_seen += 1
                    self._check_short = max(offsets)
        # Gone in every frame since the move: it fell while turning in.
        gone = self._check_empty >= _GONE_FRAMES
        waited = now - self._check_from
        if not gone and (waited < _CHECK_S or (self._check_frames < _LOOK_FRAMES and waited < 2 * _CHECK_S)):
            return
        tp = self._check_tp
        if gone:
            self._check_seen = 0
        if self._check_seen >= 2 and self._check_short > _CHECK_CENTER_TOL_DEG and self._check_room >= 1.0:
            # Short of the middle of the opening (it slid back in its pocket):
            # on until its middle is there, before anything is shaken.
            push = min(self._check_short, self._check_room)
            push_us = int(round(push * self._per_deg))
            self._check_room -= push
            self._check_gap -= push
            self._turned_deg += push
            self.logger.info(
                f"{LOG_TAG} track={tp.track_id if tp else '?'} {self._check_short:.1f}° short of the middle of the opening: "
                f"turning it {push:.1f}° further in"
            )
            self._sweep_steps = ([push_us] if push_us > 0 else []) + ["check"]
            self._enter(_P.TURN)
            return
        if self._check_seen >= 2 and self._check_room >= 1.0:
            # Still on: further into the opening first, to see if it slides off.
            push = min(_PUSH_DEG, self._check_room)
            push_us = int(round(push * self._per_deg))
            self._check_room -= push
            self._check_gap -= push
            self._turned_deg += push
            self.logger.info(
                f"{LOG_TAG} track={tp.track_id if tp else '?'} still on at the opening: turning it {push:.1f}° further in"
            )
            self._sweep_steps = ([push_us] if push_us > 0 else []) + ["check"]
            self._enter(_P.TURN)
            return
        if self._check_seen >= 2 and self._check_turn_ends:
            # The turn ends before it is as deep as it may go: the next turn
            # takes it further, so it is not shaken here.
            self.logger.info(
                f"{LOG_TAG} track={tp.track_id if tp else '?'} still on at the end of the turn: the next turn takes it further"
            )
        elif self._check_seen >= 2:
            if self._check_shakes < self._check_shakes_max:
                self._check_shakes += 1
                self._shake_cycles = _SHAKE_CYCLES
                self.logger.warning(
                    f"{LOG_TAG} track={tp.track_id if tp else '?'} did not fall at the opening: shaking it there "
                    f"({self._check_shakes} of {self._check_shakes_max})"
                )
                self._startShake(stepper, now)
                return
            self.logger.warning(f"{LOG_TAG} track={tp.track_id if tp else '?'} still did not fall: finishing the turn")
        elif (gone or self._check_frames >= 2) and tp is not None and any(tp in pocket for pocket in self._pockets):
            # It rode round before, or was missed here twice: out of sight is no
            # proof it fell, so it is shaken where it is anyway. Missed once is
            # most often a piece that slid back in its pocket and was looked
            # for in the wrong place: the turn just takes it on.
            carried = int(getattr(tp, "carried", 0)) + max(0, int(getattr(tp, "missed", 0)) - 1)
            if carried and self._check_shakes < min(carried, self._check_shakes_max):
                self._check_shakes += 1
                self._shake_cycles = _SHAKE_CYCLES
                self.logger.warning(
                    f"{LOG_TAG} track={tp.track_id} went round before and is out of sight at the opening: shaking it there anyway"
                )
                self._startShake(stepper, now)
                return
            group = [m for m in (self._check_group or [tp]) if any(m in pocket for pocket in self._pockets)]
            later = any(any(g[0] in pocket for pocket in self._pockets) for g in self._targets)
            home = next((p for p in (self._pockets[-1], self._pockets[-2]) if tp in p), None)
            if not later and home is not None and all(m in home for m in group):
                # Gone from where the camera looks, but the camera cannot see all
                # of the opening, and a piece stuck to the rotor rides on: from
                # the EXIT pocket round into the RECEIVE pocket, from the last
                # queue pocket on into the EXIT pocket. It counts as dropped once
                # the look after the turn finds the pocket it rode in empty. The
                # chute stays on it till then, and its trip down the chute is
                # timed from now.
                at = time.time()
                for member in group:
                    member.fell_pending = True
                    if member.known_object is not None:
                        member.known_object.fell_at = at
                home.remove(tp)
                home.insert(0, tp)
                self.logger.info(
                    f"{LOG_TAG} track={tp.track_id} gone at the opening: dropped once the pocket it rode in is seen empty"
                )
            else:
                # Another piece drops later in this turn and the chute must go
                # to it: this one is counted now, into the bin the chute was
                # aimed at for it, with any piece too close beside it.
                for member in group:
                    if member is not tp:
                        self._place(member)
                    self._commitToDistribution(member)
                    self.logger.info(f"{LOG_TAG} ejected track={member.track_id} (fell at the opening)")
                    self._forget(member)
                self.noteProgress()
                try:
                    self._cycles.ejected(time.time())
                except Exception:
                    pass
        self._check_tp = None
        self._enter(_P.TURN)

    def _look(self, state, perception_service, stepper, now: float, moving: bool) -> None:
        """At rest after a turn. The EXIT pocket it swept across the opening: is
        its piece in the RECEIVE pocket? A piece gone at the opening out of the
        last queue pocket: is it in the EXIT pocket? Nothing else can be in
        either: the EXIT pocket arrives empty, and C3 stands still while the
        rotor turns (a piece it let go just before is told apart, c3_fell_at)."""
        if moving:
            return
        if not self._swept and not self._exit_pending and not self._receive_before:
            self._finishCycle(now)
            return
        if self._fresh(state, self._look_wall):
            self._noteMarginStill(state)
            self._look_frames += 1
            stations = set()
            for po in getattr(state, "pieces", ()):
                station = self._station(po.com_forward_to_exit_deg)
                stayed = self._stayedPut(po.bbox) if station == 0 else None
                if stayed is not None:
                    self._held_seen[id(stayed)] = self._held_seen.get(id(stayed), 0) + 1
                    continue
                stations.add(station)
            if 0 in stations:
                self._carry_frames += 1
            if self._n - 1 in stations:
                self._exit_frames += 1
        waited = now - self._look_from
        if not self._swept and not self._exit_pending:
            # Only whether the RECEIVE pocket's piece rode the turn: two fresh
            # frames tell.
            if self._look_frames < 2 and waited < 3 * _LOOK_S:
                return
        elif waited < _LOOK_S or (self._look_frames < _LOOK_FRAMES and waited < 3 * _LOOK_S):
            return
        before, self._receive_before = self._receive_before, []
        held = [(tp, box) for tp, box in before if self._held_seen.get(id(tp), 0) >= 2]
        fell = getattr(self.shared, "c3_fell_at", None)
        if held and fell is not None and fell >= self._cycle_started_mono - _C3_LANDING_S and fell > self._landed_at:
            held = []  # C3 let a piece go around this turn: what lies there may be it
        if held:
            self._heldFromAbove(held)
        dropped: list[_TrackedPiece] = []
        pending, self._exit_pending = self._exit_pending, []
        # The EXIT pocket lies at the edge of the picture, where a piece is only
        # partly seen: seen there once, it is still there. Wrongly kept costs a
        # turn; wrongly counted as dropped sends a piece to a bin it never
        # reached.
        if pending and self._exit_frames >= 1:
            self._stillInExit(pending)
        else:
            dropped += [tp for tp in pending if any(tp in pocket for pocket in self._pockets)]
        if self._swept and not pending and self._exit_frames >= 1 and not self._pockets[-1]:
            # The EXIT pocket came round empty, yet a piece lies there: the
            # swept piece neither fell nor rode on, it is stuck at the opening.
            # It is the piece it was, and the next turn takes it off.
            stuck, self._swept = self._swept, []
            self._pockets[-1] = stuck + self._pockets[-1]
            self._stillInExit(stuck)
        if self._swept:
            carried = False
            if self._carry_frames >= 2:
                fell = getattr(self.shared, "c3_fell_at", None)
                if fell is not None and fell >= self._cycle_started_mono - _C3_LANDING_S and fell > self._landed_at:
                    # A piece came off C3 around this turn that has not landed in
                    # the record yet: what is in RECEIVE may be it, not the swept
                    # piece, so the swept piece counts as fallen and the newcomer
                    # is taken in at rest like any other.
                    self.logger.warning(
                        f"{LOG_TAG} a piece in the receive pocket after the sweep, but C3 let one go "
                        "around this turn: taken as a new piece, not turned back"
                    )
                else:
                    self._carriedRound(now)
                    carried = True
            if not carried:
                dropped += self._swept
            self._swept = []
        if not dropped:
            self._finishCycle(now)
            return
        lead = dropped[0]
        self._commitToDistribution(lead)
        self.logger.info(f"{LOG_TAG} ejected track={lead.track_id}")
        self._members = dropped[1:]
        self._forget(lead)
        self.noteProgress()
        try:
            self._cycles.ejected(time.time())
        except Exception:
            pass
        if self._members:
            self._enter(_P.COMMIT)
        else:
            self._finishCycle(now)

    def _stayedPut(self, bbox) -> Optional[_TrackedPiece]:
        """The RECEIVE pocket's piece from before the turn that lay where this
        box lies now, if any."""
        cx, cy = (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0
        for tp, box in self._receive_before:
            near = max(15.0, 0.25 * max(box[2] - box[0], box[3] - box[1]))
            if abs((box[0] + box[2]) / 2.0 - cx) <= near and abs((box[1] + box[3]) / 2.0 - cy) <= near:
                return tp
        return None

    def _heldFromAbove(self, held: list) -> None:
        """A piece in the RECEIVE pocket lay where it lay through the turn: it
        did not ride the rotor, it hangs off C3's exit. Its record goes back to
        the RECEIVE pocket, and its incident moves C3 to free it (never this
        channel, which does not move a piece C3 holds)."""
        for tp, box in held:
            for pocket in self._pockets:
                if tp in pocket:
                    pocket.remove(tp)
            self._pockets[0].insert(0, tp)
            tp.zone = _ZONE_DROP
            tp.held_from_above = True
            if tp.placed and not tp.ejected:
                self._takeBack(tp)
            notePieceProblem(
                tp.known_object,
                "hangs_off_c3",
                "It lay where it lay through a turn of the classification channel: it hung off C3's exit.",
            )
            self.logger.warning(f"{LOG_TAG} track={tp.track_id} stayed put through the turn: it hangs off C3")
        self._reportHangingOffC3(held[0][0], held[0][1])

    def _reportHangingOffC3(self, tp: _TrackedPiece, box) -> None:
        import incidents

        kind = "piece_held_c4"
        mode = incidents.handling(kind)
        if mode == incidents.OFF:
            return
        if not incidents.report(
            self.gc, kind, subject="C4", channel="c4", channel_label="C4", track_id=tp.track_id, box=list(box)
        ):
            return
        if mode != incidents.AUTOMATIC:
            return
        perception = getattr(self.gc, "perception_service", None)
        motor = self._c3Motor()
        if perception is None or motor is None:
            return
        import recovery
        from recovery.judges import pieceGoneFrom

        recovery.start(
            self.gc, "c3_exit_held", kind=kind, motors={"above": motor}, judge=pieceGoneFrom(perception, 4, box)
        )

    def _c3Motor(self):
        try:
            from hardware_settings.feeder import feederDrive
            from recovery.motors import ChannelMotor, gearedMicrosteps
            from subsystems.feeder.pulse_perception.config import channelMoveSpeed, configFromDict
            from toml_config import getPulsePerceptionConfig

            cfg = configFromDict(getPulsePerceptionConfig())
            ratio = feederDrive().gear_ratio
            stepper = self.irl.c_channel_3_rotor_stepper
            sign = 1 if cfg.forward_direction_sign >= 0 else -1
            return ChannelMotor(
                "C3", stepper, gearedMicrosteps(stepper, ratio, sign), speed=channelMoveSpeed(cfg, 3), gear_ratio=ratio
            )
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} no C3 motor for the recovery: {exc}")
            return None

    def _stillInExit(self, pending: list[_TrackedPiece]) -> None:
        """Pieces gone at the opening out of the last queue pocket are in the
        EXIT pocket after the turn: they did not fall. Most slid back in their
        pocket and were looked for in the wrong place: the next turn drops
        them; missed again, it shakes them at the opening even out of sight."""
        for tp in pending:
            tp.fell_pending = False
            tp.missed = getattr(tp, "missed", 0) + 1
            if tp.placed and not tp.ejected:
                self._takeBack(tp)
            if tp.known_object is not None:
                tp.known_object.fell_at = None
            notePieceProblem(
                tp.known_object,
                "did_not_fall",
                "It went out of sight at the classification channel's opening but was still in the exit "
                f"pocket after the turn, so it was taken there again (time {tp.missed}).",
            )
        self._needs_verify = True
        names = "+".join(str(tp.track_id) for tp in pending)
        self.logger.warning(f"{LOG_TAG} track={names} did not fall: still in the exit pocket after the turn")
        if any(getattr(tp, "missed", 0) >= _CARRY_MAX for tp in pending):
            self.logger.error(
                f"{LOG_TAG} a piece has failed to fall {_CARRY_MAX} times: the channel stops until it is cleared"
            )
            self._halted = True

    def _carriedRound(self, now: float) -> None:
        """The swept pocket's piece is still on the channel: it stuck to the
        rotor and rode round into the RECEIVE pocket. It goes on as the piece
        it is, and is shaken harder at the opening on its next pass."""
        swept, self._swept = self._swept, []
        for tp in swept:
            tp.fell_pending = False
            tp.carried = getattr(tp, "carried", 0) + 1
            if tp.placed and not tp.ejected:
                self._takeBack(tp)
            if tp.known_object is not None:
                tp.known_object.fell_at = None
            notePieceProblem(
                tp.known_object,
                "did_not_fall",
                "It was still on the classification channel after its pocket crossed the exit, shaken "
                f"there, so it went round again (time {tp.carried}).",
            )
            tp.zone = _ZONE_DROP
        self._needs_verify = True
        names = "+".join(str(tp.track_id) for tp in swept)
        self.logger.warning(f"{LOG_TAG} track={names} did not fall: carried round into the receive pocket")
        self._pockets[0] = swept + self._pockets[0]
        if any(getattr(tp, "carried", 0) >= _CARRY_MAX for tp in swept):
            self.logger.error(
                f"{LOG_TAG} a piece has gone round {_CARRY_MAX} times without falling: the channel stops until it is cleared"
            )
            self._halted = True

    def _commit(self, state, perception_service, stepper, now: float, moving: bool) -> None:
        """The rest of a group that fell with its first piece: each is handed to
        distribution in turn, so every one is recorded where it went."""
        if not self._members:
            self._finishCycle(now)
            return
        member = self._members[0]
        if not member.placed:
            if self.transport.getPieceForDistributionPositioning() is None:
                self._place(member)
            return
        if self._headReady(member):
            self._commitToDistribution(member)
            self._forget(member)

    def _finishCycle(self, now: float) -> None:
        """Aim for the piece the next turn takes into the EXIT pocket, and check
        the fins."""
        nxt = self._pockets[-1] or self._pockets[-2]
        if nxt and nxt[0].result_applied and self.transport.getPieceForDistributionPositioning() is None:
            self._place(nxt[0])
        try:
            self._cycles.staged(time.time())
        except Exception:
            pass
        self._turns_since_verify += 1
        if self._needs_verify or self._turns_since_verify >= _VERIFY_EVERY:
            self._startVerify(now)
        else:
            self._toRest(now)

    # ---------------------------------------------------------------------- AIM

    def _place(self, tp: _TrackedPiece) -> None:
        """Hand the piece to distribution, which aims the chute for it."""
        if tp.placed or time.monotonic() - self._taken_back_at < _HAND_BACK_AFTER_S:
            return
        self._ensureKnownObject(tp)
        obj = tp.known_object
        if obj is None:
            return
        if obj.part_id is None and obj.classification_status in (
            ClassificationStatus.pending,
            ClassificationStatus.classifying,
        ):
            obj.classification_status = ClassificationStatus.unknown
        self.transport.placePieceForDistribution(obj)
        tp.placed = True
        tp.placed_at = time.monotonic()
        self.logger.info(f"{LOG_TAG} aiming chute for track={tp.track_id} (status={obj.classification_status})")

    def _aimedFor(self, tp: _TrackedPiece) -> bool:
        """Whether the chute is on this piece; if not, it is handed to
        distribution, taking back any other piece distribution holds (one
        aimed for earlier that now drops after it)."""
        if not tp.placed:
            for other in self._pieces.values():
                if other is not tp and other.placed and not other.ejected:
                    self._takeBack(other)
            if self.transport.getPieceForDistributionPositioning() is None:
                self._place(tp)
            return False
        return self._chuteOn(tp)

    def _chuteOn(self, tp: _TrackedPiece) -> bool:
        """Whether the chute is on this piece. A piece handed over that the
        chute never comes to is taken back, to be handed over again."""
        if self._headReady(tp):
            return True
        if tp.placed and time.monotonic() - getattr(tp, "placed_at", time.monotonic()) > _AIM_TIMEOUT_S:
            self.logger.warning(f"{LOG_TAG} the chute did not come to track={tp.track_id}: handing it over again")
            self._takeBack(tp)
        return False

    def _aimThen(self, tp: Optional[_TrackedPiece], microsteps: int, then: _P, now: float, back: bool = False) -> None:
        """Wait until the chute is on `tp`, then turn `microsteps` and go on to
        `then`. With no piece there is nothing to wait for."""
        self._aim_target = tp
        self._after_aim_us = int(microsteps)
        self._after_aim_back = bool(back)
        self._after_aim_phase = then
        self._enter(_P.AIM)

    def _aim(self, state, perception_service, stepper, now: float, moving: bool) -> None:
        if moving:
            return
        tp = self._aim_target
        if tp is not None and any(tp in pocket for pocket in self._pockets):
            if not tp.placed:
                if self.transport.getPieceForDistributionPositioning() is None:
                    self._place(tp)
                return
            if not self._chuteOn(tp):
                return
        self._aim_target = None
        what = "correction" if self._after_aim_phase == _P.CORRECT else "turn"
        self._move(
            stepper, self._after_aim_us, self.ctx.config.rotate_speed_usteps_per_s, now, what, back=self._after_aim_back
        )
        self._enter(self._after_aim_phase)

    # ----------------------------------------------------------- VERIFY, CORRECT

    def _startVerify(self, now: float) -> None:
        self._needs_verify = False
        self._turns_since_verify = 0
        self._verify_result = ("none", None)
        self._verify_thread = None  # Started by _verify once the rotor stands still
        self._enter(_P.VERIFY)

    def _readFins(self) -> None:
        """How far on a fin must turn to stand at rest, read off the camera."""
        try:
            from subsystems.classification_channel.two_piece.spoke_home import (
                DETECTOR_PARAMS,
                finMoveToExit,
                loadSpokeHomeGeometry,
                readFinAngle,
            )

            vision = getattr(self, "vision", None)
            capture = None
            if vision is not None and hasattr(vision, "getCaptureThreadForRole"):
                capture = vision.getCaptureThreadForRole("classification_channel") or vision.getCaptureThreadForRole(
                    "carousel"
                )
            frame = getattr(getattr(capture, "latest_frame", None), "raw", None)
            geometry = loadSpokeHomeGeometry(frame.shape[:2]) if frame is not None else None
            if geometry is None:
                return
            params = replace(DETECTOR_PARAMS, fin_count=self._n)
            result = readFinAngle(
                capture, geometry[0], params, newer_than=time.time() + 0.1, reads=2, timeout_s=1.5
            )
            if result is None:
                return
            move = finMoveToExit(result.angle_deg, self.ctx.config)
            if move is not None:
                self._verify_result = ("ok", float(move))
        except Exception as exc:
            self._verify_result = ("error", None)
            self.logger.warning(f"{LOG_TAG} reading the fins off the camera failed: {exc}")

    def _verify(self, state, perception_service, stepper, now: float, moving: bool) -> None:
        if moving:
            return
        if self._verify_thread is None:
            self._verify_thread = threading.Thread(target=self._readFins, daemon=True, name="c4-pocket-fins")
            self._verify_thread.start()
            return
        if self._verify_thread.is_alive():
            return
        kind, move = self._verify_result
        pitch = self._pitch_deg
        if kind != "ok" or move is None:
            # The camera gave no steady reading: the step count stands.
            self._off_seen = None
            self._verify_reads = 0
            if getattr(self.irl, "c4_fin_rest_microsteps", None) is None:
                self.irl.c4_fin_rest_microsteps = int(stepper.position)
            self._toRest(now)
            return
        # Signed: forward to rest when short of it, back when past it.
        off = float(move) if float(move) <= pitch / 2.0 else float(move) - pitch
        if abs(off) <= _ALIGN_TOL_DEG:
            self._off_seen = None
            self._verify_reads = 0
            if getattr(self.irl, "c4_fin_rest_microsteps", None) is None:
                self.irl.c4_fin_rest_microsteps = int(stepper.position)
            self._toRest(now)
            return
        if off < 0 and abs(off) > _BACK_WITH_PIECE_DEG and self._pockets[0]:
            self.logger.warning(
                f"{LOG_TAG} a fin stands {abs(off):.1f}° past rest with a piece in the receive pocket: "
                "not turned back, which would carry it toward the opening"
            )
            self._off_seen = None
            self._verify_reads = 0
            self._toRest(now)
            return
        if self._off_seen is None or abs(self._off_seen - off) > _ALIGN_TOL_DEG:
            # One reading is not enough to turn the rotor: read again.
            self._verify_reads += 1
            if self._verify_reads > _VERIFY_READS_MAX:
                self.logger.error(f"{LOG_TAG} the fin readings do not agree ({off:+.1f}° now); leaving the rotor where it is")
                self._off_seen = None
                self._verify_reads = 0
                self._toRest(now)
                return
            self._off_seen = off
            self._startVerify(now)
            return
        self._off_seen = None
        self._verify_reads = 0
        self.logger.warning(
            f"{LOG_TAG} a fin stands {abs(off):.1f}° {'short of' if off > 0 else 'past'} rest (steps were lost?): turning to it"
        )
        # Forward pushes whatever is by the exit toward the opening: the chute
        # is on that piece first.
        lead = (self._pockets[-1] or [None])[0] if off > 0 else None
        self._aimThen(lead, int(round(abs(off) * self._per_deg)), _P.CORRECT, now, back=off < 0)

    def _correct(self, state, perception_service, stepper, now: float, moving: bool) -> None:
        if moving:
            return
        self.irl.c4_fin_rest_microsteps = int(stepper.position)
        # The correction itself can lose steps: read the fins after the next turn too.
        self._needs_verify = True
        self._toRest(now)

    def _toRest(self, now: float) -> None:
        self._rest_since = now
        self._rest_wall = time.time()
        self._new_seen = {}
        self._enter(_P.REST)


def _iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0
