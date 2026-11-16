"""The classification channel's flow for a rotor whose fins make fixed pockets.

The rotor's fins divide the channel into as many pockets as it has fins. It
only ever rests in one pose: a fin standing on the far edge of the exit hole,
walling the hole off from the pocket pieces drop into. In travel order the
pockets at rest are then RECEIVE (pieces land here), the QUEUE pockets, and
EXIT, whose floor ends in the hole: the fin that pushes a piece into it rests a
ledge short of the hole, so a piece carried in waits on the ledge and falls
when the next turn begins.

One cycle is exactly one fin pitch, always forward, in two fixed strokes:

  REST     the feeder may add one piece, only into an empty RECEIVE pocket; it
           is photographed there and identified while it rides the queue.
  EJECT    a fixed stroke pushes the piece on the ledge over the hole, then a
           short shake. The hole's lip can be outside the camera's view, so a
           piece is only counted as gone after the stroke and the shake.
  AIM      the chute is aimed for the piece that enters the EXIT pocket next,
           before it can get there when it is too long to rest on the ledge.
  ALIGN    the rest of the pitch, back to REST. The fins are read off the
           camera and the pose corrected if steps were lost.

Which pocket holds which piece is the flow's own record, moved one pocket per
cycle. The camera adds pieces to it and is evidence, never the truth: a piece
the detector loses for a while stays in its pocket and is ejected on schedule.

Rules kept in code: one piece (or one group that landed together) in the EXIT
pocket at a time; the chute is aimed for a piece before it can fall and stays
on it until it is counted as gone; nothing is fed while the rotor is off REST
or the RECEIVE pocket is occupied; two pieces in one pocket go to the discard
together; no move is ever reversed.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import replace
from enum import Enum
from typing import Optional

from defs.known_object import ClassificationStatus, notePieceProblem
from runtime_stats import C4_WAITING_FOR_PIECE
from subsystems.classification_channel.five_sector_platter import C4FiveSectorPlatter
from subsystems.classification_channel.two_piece.channel_clear import ChannelClearResult
from subsystems.classification_channel.two_piece.constants import C4_TRAVEL_SIGN
from subsystems.classification_channel.two_piece.flow import (
    _ZONE_DROP,
    _ZONE_PRECISE,
    TwoPieceClassificationChannel,
    _TrackedPiece,
)

LOG_TAG = "[C4-POCKET]"

# How far past the hole's entry edge the eject stroke carries the pushing fin.
_EJECT_PAST_EDGE_DEG = 20.0
# The shake after an eject stroke, at the rotor, and how often it is repeated
# for a piece still seen at the hole before the piece is given up on.
_SHAKE_OUTPUT_DEG = 3.0
_SHAKE_CYCLES = 4
_SHAKE_TRIES = 3
# A piece is counted as gone when nothing is seen at the hole for this long
# after the stroke and its shake.
_CONFIRM_S = 0.4
# The firmware can report "stopped" before a move it was just given starts.
_START_GRACE_S = 0.15
# A box must be in this many frames in a row to become a piece.
_NEW_FRAMES = 3
# Two boxes this close are one piece drawn twice, not two pieces.
_SAME_PIECE_DEG = 8.0
# A piece the tracker gave a new id is found this close to where it was.
_RELINK_DEG = 25.0
# A piece stuck at the hole this many cycles running stops the cycling: the
# channel's stall watchdog takes over (it sweeps the channel, or asks for help).
_STUCK_CYCLES_MAX = 2
# A box in the RECEIVE pocket that was never photographed and is gone this long
# was not a piece.
_UNSEEN_DROP_S = 0.7
# With no new piece for this long, the pieces already on the channel move on.
_FLUSH_AFTER_S = 6.0
# The fins within this of the rest pose are at rest; a fin short of it by up
# to _CORRECT_MAX_DEG is turned on to it (steps were lost).
_ALIGN_TOL_DEG = 2.0
_CORRECT_MAX_DEG = 30.0
# Fin readings that keep disagreeing are given up on after this many.
_VERIFY_READS_MAX = 4
# A longer gap between steps means the machine was paused or held.
_RESUME_GAP_S = 1.0


class _P(Enum):
    VERIFY = "verify"
    CORRECT = "correct"
    REST = "rest"
    EJECT = "eject"
    SHAKE = "shake"
    CONFIRM = "confirm"
    COMMIT = "commit"
    AIM = "aim"
    ALIGN = "align"


# What the runtime stats call the channel's state.
_PHASE_NAMES = {
    _P.REST: "waiting",
    _P.EJECT: "ejecting",
    _P.SHAKE: "ejecting",
    _P.CONFIRM: "ejecting",
    _P.COMMIT: "ejecting",
    _P.AIM: "staging",
    _P.ALIGN: "staging",
    _P.VERIFY: "staging",
    _P.CORRECT: "staging",
}


class PocketClassificationChannel(TwoPieceClassificationChannel):
    """The pocket flow. It takes the two-piece flow's piece handling (photos,
    identification, the hand-over to distribution) and none of its motion."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cfg = self.ctx.config
        self._n = max(2, int(cfg.fin_count))
        self._pitch_deg = 360.0 / self._n
        # pockets[0] is RECEIVE, pockets[-1] is EXIT.
        self._pockets: list[list[_TrackedPiece]] = [[] for _ in range(self._n)]
        self._pp = _P.VERIFY
        self._started = False
        self._serial = 0
        self._move_cmd_at = 0.0
        self._rest_since = 0.0
        self._rest_wall = 0.0
        self._last_state_ts = -1.0
        self._new_seen: dict[tuple[int, int], int] = {}
        # This cycle: where the motor stood when it began, and what is left.
        self._cycle_start_pos: Optional[int] = None
        self._members: list[_TrackedPiece] = []
        self._aim_target: Optional[_TrackedPiece] = None
        self._after_aim_us = 0
        self._after_aim_phase = _P.ALIGN
        self._shake_tries = 0
        self._stuck_frames = 0
        self._stuck_cycles = 0
        # A fin read short of rest once: corrected only when a second reading agrees.
        self._short_seen: Optional[float] = None
        self._verify_reads = 0
        self._confirm_from = 0.0
        self._confirm_wall = 0.0
        self._verify_thread: Optional[threading.Thread] = None
        self._verify_result: tuple[str, Optional[float]] = ("none", None)
        self._paused_mid_cycle = False
        self._geometry_error_logged = False
        self._fins: list[float] = []
        self._ledge_deg = 0.0
        self._eject_us = 0
        self._pitch_us = 0
        self._per_deg = 1.0
        self._loadGeometry()
        self._releaseBucket("pocket flow start")

    # ---------------------------------------------------------------- geometry

    def _loadGeometry(self) -> bool:
        """Where the fins rest, as gaps to the hole's entry edge (the measure the
        camera gives every piece), and the two strokes in motor microsteps."""
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
            self._ledge_deg = self._fins[0]
            platter = C4FiveSectorPlatter.from_irl_config(self.irl_config)
            per_rev = float(platter.motor_microsteps_per_output_revolution)
            self._per_deg = per_rev / 360.0
            self._pitch_us = int(round(per_rev / self._n))
            eject_deg = min(max(self._ledge_deg + _EJECT_PAST_EDGE_DEG, 5.0), self._pitch_deg - 5.0)
            self._eject_us = int(round(eject_deg * self._per_deg))
            self.logger.info(
                f"{LOG_TAG} {self._n} pockets of {self._pitch_deg:.1f}°; the pushing fin rests "
                f"{self._ledge_deg:.1f}° short of the hole; eject stroke {self._eject_us / self._per_deg:.1f}°, "
                f"align stroke {(self._pitch_us - self._eject_us) / self._per_deg:.1f}°"
            )
            return True
        except Exception as exc:
            if not self._geometry_error_logged:
                self._geometry_error_logged = True
                self.logger.error(f"{LOG_TAG} cannot work out the pockets ({exc}); the channel will not run")
            self._fins = []
            return False

    def _station(self, gap: Optional[float]) -> Optional[int]:
        """Which pocket a piece this far from the hole's entry is in, at rest:
        0 is RECEIVE, the last is EXIT."""
        if gap is None or not self._fins:
            return None
        gap = float(gap)
        if gap < 0.0:
            return self._n - 1
        below = sum(1 for fin in self._fins if fin <= gap)
        if below >= self._n:
            return self._n - 1  # Past the fin that walls the hole off: at the hole
        return (self._n - 1) - below

    # ------------------------------------------------------------- watchdog API

    def phaseName(self) -> str:
        if self._pp == _P.REST and self.shared.classification_ready:
            return C4_WAITING_FOR_PIECE
        return _PHASE_NAMES[self._pp]

    def attemptStallAutoClear(self, *, max_output_deg: float) -> ChannelClearResult:
        result = super().attemptStallAutoClear(max_output_deg=max_output_deg)
        if result.cleared:
            self._pockets = [[] for _ in range(self._n)]
            self._members = []
            self._aim_target = None
            self._stuck_cycles = 0
            self._started = False  # The sweep left the rotor anywhere: find rest again
            self._last_step_at = None
        return result

    def pause(self) -> None:
        self.transport.clearPieceForDistribution()
        for tp in self._pieces.values():
            if tp.placed and not tp.ejected:
                self._unplace(tp)
        self._paused_mid_cycle = self._pp not in (_P.REST, _P.VERIFY, _P.CORRECT)
        self._cycles.drop()
        self._was_ready = False
        self._ready_since = None
        self.last_progress_at = time.monotonic()

    def cleanup(self) -> None:
        super().cleanup()
        self._pockets = [[] for _ in range(self._n)]
        self._members = []
        self._aim_target = None
        self._new_seen = {}
        self._started = False
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
            _P.EJECT: self._eject,
            _P.SHAKE: self._shake,
            _P.CONFIRM: self._confirm,
            _P.COMMIT: self._commit,
            _P.AIM: self._aim,
            _P.ALIGN: self._align,
        }[self._pp]
        handler(state, perception_service, stepper, now, moving)

        ready = self._pp == _P.REST and not moving and self._receiveClear(state)
        self.setClassificationReady(ready, "at rest, receive pocket empty")
        if not ready:
            self._ready_since = None
        elif self._ready_since is None:
            self._ready_since = now
        self._recordCycle(perception_service, state, ready)

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
        for tp in self._pieces.values():
            tp.last_seen = now
            if tp.known_object is not None:
                tp.worker.emitKnownObject()
        self._ready_since = None
        self.last_progress_at = now
        self._new_seen = {}
        if not self._started:
            self._started = True
            self._paused_mid_cycle = False
            self._startVerify(now)
            return
        self.logger.info(f"{LOG_TAG} resumed  [{self._pocketsText()}]")
        if not self._paused_mid_cycle:
            self._startVerify(now)
            return
        # Stopped part way through a cycle: whether the piece being ejected fell,
        # and where the one behind it lies, is not known. Both go to the discard,
        # and the cycle is finished from where the motor stands.
        self._paused_mid_cycle = False
        for tp in self._pockets[-1] + self._pockets[-2] + self._members:
            self._toDiscard(
                tp,
                "interrupted",
                "The machine stopped while the classification channel was turning it toward the "
                "exit, so where it fell is not known; it went to the discard.",
            )
        self._pockets[-1] = self._members + self._pockets[-1]
        self._members = []
        done = 0
        if self._cycle_start_pos is not None:
            done = abs(int(stepper.position) - int(self._cycle_start_pos))
        remaining = max(0, self._pitch_us - done)
        lead = (self._pockets[-1] or self._pockets[-2] or [None])[0]
        self._aimThen(lead, remaining, _P.ALIGN, now)

    # ------------------------------------------------------------ what is seen

    def _fresh(self, state, since_wall: float) -> bool:
        """A frame taken since `since_wall` that has not been read yet."""
        ts = float(getattr(state, "ts", 0.0) or 0.0)
        if ts <= since_wall or ts == self._last_state_ts:
            return False
        self._last_state_ts = ts
        return True

    def _receiveClear(self, state) -> bool:
        if self._pockets[0]:
            return False
        return not any(
            self._station(po.com_forward_to_exit_deg) == 0 for po in getattr(state, "pieces", ())
        )

    def _observeAtRest(self, state, now: float) -> None:
        """Match the frame's boxes to the pockets' records and add the pieces
        that have newly landed."""
        by_id = {tp.track_id: tp for pocket in self._pockets for tp in pocket}
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
            # is not in the frame takes it.
            lost = next(
                (
                    tp
                    for tp in pocket
                    if id(tp) not in matched
                    and (tp.gap_to_exit is None or abs(float(tp.gap_to_exit) - gap) <= _RELINK_DEG)
                ),
                None,
            )
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
        # A box in RECEIVE that never became a photographed piece and is gone.
        for tp in list(self._pockets[0]):
            if not tp.capture_done and (now - tp.last_seen) > _UNSEEN_DROP_S:
                self.logger.info(f"{LOG_TAG} track={tp.track_id} left the receive pocket unphotographed; dropped")
                tp.worker.abandonInFlightObject("gone from the receive pocket before it was photographed")
                self._forget(tp)

    def _seen(self, tp: _TrackedPiece, po, now: float) -> None:
        b = po.bbox
        tp.bbox = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
        tp.boxes = (tp.bbox,)
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
        pocket.append(tp)
        if len(pocket) > 1:
            self._multi_drop_seq += 1
            for member in pocket:
                self._toDiscard(
                    member,
                    "double_feed",
                    "Two pieces were in one pocket of the classification channel, so neither could be "
                    "sent to a bin of its own; both went to the discard.",
                    group=self._multi_drop_seq,
                )
            return
        if station != 0:
            self._ensureKnownObject(tp)
            obj = tp.known_object
            if obj is not None:
                obj.classification_status = ClassificationStatus.unknown
                obj.part_id = None
                notePieceProblem(
                    obj,
                    "stray",
                    "The camera first saw it in a pocket past the one pieces land in, so it was "
                    "never photographed or identified; it went to the discard.",
                )
                tp.worker.emitKnownObject()
            tp.capture_done = True
            tp.result_applied = True
            self.logger.warning(f"{LOG_TAG} track={tp.track_id} appeared in pocket {station}, unphotographed -> discard")

    def _toDiscard(self, tp: _TrackedPiece, kind: str, message: str, group: Optional[int] = None) -> None:
        if tp.double_feed:
            return
        if group is None:
            self._multi_drop_seq += 1
            group = self._multi_drop_seq
        if tp.placed and not tp.ejected:
            self.transport.clearPieceForDistribution(tp.known_object)
            self._unplace(tp)
        self._markDoubleFeed(tp, group, kind, message)

    def _forget(self, tp: _TrackedPiece) -> None:
        for pocket in self._pockets:
            if tp in pocket:
                pocket.remove(tp)
        if tp in self._members:
            self._members.remove(tp)
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
        receive, last_queue, exit_ = self._pockets[0], self._pockets[-2], self._pockets[-1]
        if not any(self._pockets):
            return
        if self._stuck_cycles >= _STUCK_CYCLES_MAX:
            return  # No progress from here: the stall watchdog takes over
        if receive:
            if not all(tp.capture_done for tp in receive):
                return  # Still being photographed
        elif (now - self._rest_since) < _FLUSH_AFTER_S:
            return  # The feeder gets its chance to add a piece first
        if exit_:
            lead = exit_[0]
            if not lead.placed:
                self._place(lead)
                return
            if not self._headReady(lead):
                return  # The chute is not on it yet
        if last_queue and not all(tp.result_applied for tp in last_queue):
            return  # The piece about to enter the exit pocket is not identified yet
        self._cycle_start_pos = int(stepper.position)
        self._shake_tries = 0
        self.noteProgress()
        try:
            self._cycles.rotated(time.time(), ejecting=bool(exit_))
        except Exception:
            pass
        if exit_:
            self._move(stepper, self._eject_us, self.ctx.config.discharge_speed_usteps_per_s, now, "eject stroke")
            self._enter(_P.EJECT)
        else:
            self._afterEject(stepper, now, done_us=0)

    # -------------------------------------------------------------------- moves

    def _move(self, stepper, microsteps: int, speed: int, now: float, what: str) -> None:
        microsteps = int(microsteps)
        if microsteps <= 0:
            return
        try:
            stepper.set_speed_limits(16, max(16, int(speed)))
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} set_speed_limits failed: {exc}")
        self.logger.info(f"{LOG_TAG} {what}: {microsteps / self._per_deg:.1f}°")
        if not bool(stepper.move_steps(int(C4_TRAVEL_SIGN) * microsteps)):
            self.logger.error(f"{LOG_TAG} {what} was not acknowledged")
        self._move_cmd_at = now

    def _startShake(self, stepper, now: float) -> None:
        cfg = self.ctx.config
        amplitude = max(1, int(round(_SHAKE_OUTPUT_DEG * self._per_deg)))
        try:
            stepper.jitter(amplitude, _SHAKE_CYCLES, int(cfg.jitter_speed_usteps_per_s), int(cfg.jitter_accel_usteps_per_s2))
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} shake failed: {exc}")
        self._move_cmd_at = now
        self._enter(_P.SHAKE)

    # ----------------------------------------------------- EJECT, SHAKE, CONFIRM

    def _eject(self, state, perception_service, stepper, now: float, moving: bool) -> None:
        if not moving:
            self._startShake(stepper, now)

    def _shake(self, state, perception_service, stepper, now: float, moving: bool) -> None:
        if moving:
            return
        try:
            if bool(stepper.is_jittering()):
                return
        except Exception:
            pass
        self._confirm_from = now
        self._confirm_wall = time.time()
        self._stuck_frames = 0
        self._enter(_P.CONFIRM)

    def _confirm(self, state, perception_service, stepper, now: float, moving: bool) -> None:
        if moving:
            return
        if self._fresh(state, self._confirm_wall):
            # Ahead of the pushing fin, which now stands past the hole's edge.
            edge = self._ledge_deg - self._eject_us / self._per_deg - 2.0
            ahead = any(
                po.com_forward_to_exit_deg is not None and float(po.com_forward_to_exit_deg) < edge
                for po in getattr(state, "pieces", ())
            )
            self._stuck_frames = self._stuck_frames + 1 if ahead else 0
        if self._stuck_frames >= 2:
            self._shake_tries += 1
            if self._shake_tries < _SHAKE_TRIES:
                self.logger.warning(f"{LOG_TAG} a piece is still at the hole: shaking again ({self._shake_tries + 1} of {_SHAKE_TRIES})")
                self._startShake(stepper, now)
                return
            self._exitStuck(stepper, now)
            return
        if (now - self._confirm_from) < _CONFIRM_S:
            return
        exit_ = self._pockets[-1]
        lead = exit_[0]
        self._commitToDistribution(lead)
        self._stuck_cycles = 0
        self.logger.info(f"{LOG_TAG} ejected track={lead.track_id}")
        self._members = exit_[1:]
        self._pockets[-1] = []
        self._forget(lead)
        self.noteProgress()
        try:
            self._cycles.ejected(time.time())
        except Exception:
            pass
        if self._members:
            self._enter(_P.COMMIT)
        else:
            self._afterEject(stepper, now, done_us=self._eject_us)

    def _exitStuck(self, stepper, now: float) -> None:
        """The piece will not leave the hole's lip. Nothing may land in a sorted
        bin it was not aimed for: it and the piece arriving behind it go to the
        discard together, with the chute on the discard before anything turns."""
        self._stuck_cycles += 1
        self.logger.error(f"{LOG_TAG} a piece is stuck at the hole after {_SHAKE_TRIES} shakes: it and the next piece go to the discard")
        for tp in self._pockets[-1] + self._pockets[-2]:
            self._toDiscard(
                tp,
                "stuck_at_exit",
                "A piece stayed on the lip of the classification channel's exit after it was shaken, "
                "so it and the piece behind it went to the discard together.",
            )
        lead = self._pockets[-1][0]
        self._aimThen(lead, self._pitch_us - self._eject_us, _P.ALIGN, now)

    def _commit(self, state, perception_service, stepper, now: float, moving: bool) -> None:
        """The rest of a group that fell with its first piece: each is handed to
        distribution in turn, so every one is recorded where it went."""
        if not self._members:
            self._afterEject(stepper, now, done_us=self._eject_us)
            return
        member = self._members[0]
        if not member.placed:
            if self.transport.getPieceForDistributionPositioning() is None:
                self._place(member)
            return
        if self._headReady(member):
            self._commitToDistribution(member)
            self._forget(member)

    def _afterEject(self, stepper, now: float, *, done_us: int) -> None:
        """Nothing is left in the EXIT pocket. Aim for the piece that enters it
        with the align stroke, and wait for the chute first unless that piece is
        short enough to rest on the ledge."""
        remaining = self._pitch_us - int(done_us)
        arriving = self._pockets[-2]
        if not arriving:
            self._startAlign(stepper, remaining, now)
            return
        lead = arriving[0]
        if self._fitsLedge(arriving):
            self._place(lead)
            self._startAlign(stepper, remaining, now)
        else:
            self._aimThen(lead, remaining, _P.ALIGN, now)

    def _fitsLedge(self, pocket: list[_TrackedPiece]) -> bool:
        """One whole piece whose box, seen from the rotor's centre, is narrower
        than the ledge: it cannot reach the hole when the fin stops."""
        if len(pocket) != 1 or pocket[0].double_feed:
            return False
        perception = getattr(self.gc, "perception_service", None)
        channel = perception.channel_def(4) if perception is not None else None
        x1, y1, x2, y2 = pocket[0].bbox
        if channel is None or (x2 - x1) <= 0 or (y2 - y1) <= 0:
            return False
        cx, cy = channel.center
        angles = sorted(
            math.degrees(math.atan2(y - cy, x - cx)) % 360.0 for x, y in ((x1, y1), (x2, y1), (x1, y2), (x2, y2))
        )
        widest_gap = max((angles[(i + 1) % 4] - angles[i]) % 360.0 for i in range(4))
        return (360.0 - widest_gap) <= self._ledge_deg - 2.0

    # ---------------------------------------------------------------------- AIM

    def _place(self, tp: _TrackedPiece) -> None:
        """Hand the piece to distribution, which aims the chute for it."""
        if tp.placed:
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
        self.logger.info(f"{LOG_TAG} aiming chute for track={tp.track_id} (status={obj.classification_status})")

    def _aimThen(self, tp: Optional[_TrackedPiece], microsteps: int, then: _P, now: float) -> None:
        """Wait until the chute is on `tp`, then turn `microsteps` and go on to
        `then`. With no piece there is nothing to wait for."""
        self._aim_target = tp
        self._after_aim_us = int(microsteps)
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
            if not self._headReady(tp):
                return
        self._aim_target = None
        if self._after_aim_phase == _P.CORRECT:
            self._move(stepper, self._after_aim_us, self.ctx.config.rotate_speed_usteps_per_s, now, "correction")
            self._enter(_P.CORRECT)
        else:
            self._startAlign(stepper, self._after_aim_us, now)

    # -------------------------------------------------------------------- ALIGN

    def _startAlign(self, stepper, microsteps: int, now: float) -> None:
        self._move(stepper, microsteps, self.ctx.config.rotate_speed_usteps_per_s, now, "align stroke")
        self._enter(_P.ALIGN)

    def _align(self, state, perception_service, stepper, now: float, moving: bool) -> None:
        if moving:
            return
        # One pocket on: what stayed in EXIT (a stuck piece) is joined by the
        # pocket behind it.
        left = self._pockets[-1]
        self._pockets = [[]] + self._pockets[:-1]
        self._pockets[-1] = left + self._pockets[-1]
        for index, pocket in enumerate(self._pockets):
            for tp in pocket:
                tp.zone = _ZONE_DROP if index == 0 else _ZONE_PRECISE
        rest = getattr(self.irl, "c4_fin_rest_microsteps", None)
        if rest is not None:
            self.irl.c4_fin_rest_microsteps = int(rest) + int(C4_TRAVEL_SIGN) * self._pitch_us
        self._cycle_start_pos = None
        try:
            self._cycles.staged(time.time())
        except Exception:
            pass
        self._startVerify(now)

    # ----------------------------------------------------------- VERIFY, CORRECT

    def _startVerify(self, now: float) -> None:
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
            # The camera gave no steady reading: go by the step count.
            rest = getattr(self.irl, "c4_fin_rest_microsteps", None)
            if rest is None:
                self.logger.warning(f"{LOG_TAG} the fins could not be read and the rotor was never homed on them; taking this pose as rest")
                self._toRest(now)
                return
            past = (C4_TRAVEL_SIGN * (float(stepper.position) - float(rest)) / self._per_deg) % pitch
            move = (pitch - past) % pitch
            self.logger.warning(f"{LOG_TAG} the fins could not be read off the camera; going by the step count")
        short, over = float(move), pitch - float(move)
        if short <= _ALIGN_TOL_DEG or over <= _ALIGN_TOL_DEG:
            self._short_seen = None
            self._verify_reads = 0
            if getattr(self.irl, "c4_fin_rest_microsteps", None) is None:
                self.irl.c4_fin_rest_microsteps = int(stepper.position)
            self._toRest(now)
            return
        empty = not any(self._pockets)
        if (empty or short <= _CORRECT_MAX_DEG) and (
            self._short_seen is None or abs(self._short_seen - short) > _ALIGN_TOL_DEG
        ):
            # One reading is not enough to turn the rotor on: read again.
            self._verify_reads += 1
            if self._verify_reads > _VERIFY_READS_MAX:
                self.logger.error(f"{LOG_TAG} the fin readings do not agree ({short:.1f}° short now); leaving the rotor where it is")
                self._short_seen = None
                self._verify_reads = 0
                self._toRest(now)
                return
            self._short_seen = short
            self._startVerify(now)
            return
        self._short_seen = None
        self._verify_reads = 0
        if empty or short <= _CORRECT_MAX_DEG:
            self.logger.warning(f"{LOG_TAG} a fin stands {short:.1f}° short of rest (steps were lost?): turning it on")
            lead = (self._pockets[-1] or [None])[0]
            self._aimThen(lead, int(round(short * self._per_deg)), _P.CORRECT, now)
            return
        self.logger.error(
            f"{LOG_TAG} the fins stand {over:.1f}° past rest ({short:.1f}° short of the next); "
            f"not corrected with pieces on the channel"
        )
        self._toRest(now)

    def _correct(self, state, perception_service, stepper, now: float, moving: bool) -> None:
        if moving:
            return
        self.irl.c4_fin_rest_microsteps = int(stepper.position)
        self._toRest(now)

    def _toRest(self, now: float) -> None:
        self._rest_since = now
        self._rest_wall = time.time()
        self._new_seen = {}
        self._enter(_P.REST)
