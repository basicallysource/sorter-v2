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

Every move is one fin pitch forward. The chute is aimed for a piece before the
turn that takes it into the EXIT pocket and stays on it until it is counted as
dropped. Which pocket holds which piece is the flow's own record, moved one
pocket per turn; the camera adds pieces to it and is evidence, never the truth.
Two pieces in one pocket go to the discard together.
"""

from __future__ import annotations

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

# After a turn the camera gets this long, and this many frames, to show whether
# a swept piece was carried round into the RECEIVE pocket.
_LOOK_S = 0.3
_LOOK_FRAMES = 3
# A piece carried round this many times will not fall: the channel stops for
# the stall watchdog (it sweeps the channel, or asks for help).
_CARRY_MAX = 3
# The rotor is turned more gently than the motor's default: turning its floor
# and fins directly, the motor slipped a few steps on about one turn in eight
# at the default (the fin check found it 7.2 degrees short each time).
_TURN_ACCEL_USTEPS_PER_S2 = 4000
# The firmware can report "stopped" before a move it was just given starts.
_START_GRACE_S = 0.15
# A piece drawn as several fused boxes in half its frames at rest, of at least
# this many, is taken for two pieces that landed together.
_MERGED_MIN_FRAMES = 4
# A box must be in this many frames in a row to become a piece.
_NEW_FRAMES = 3
# Two boxes this close are one piece drawn twice, not two pieces.
_SAME_PIECE_DEG = 8.0
# A box in the RECEIVE pocket that was never photographed and is gone this long
# was not a piece.
_UNSEEN_DROP_S = 0.7
# With no new piece for this long, the pieces already on the channel move on.
_FLUSH_AFTER_S = 6.0
# The fins within this of the rest pose are at rest; off by up to
# _CORRECT_MAX_DEG, the rotor is turned to it (steps were lost).
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
    AIM = "aim"
    TURN = "turn"
    LOOK = "look"
    COMMIT = "commit"


# What the runtime stats call the channel's state.
_PHASE_NAMES = {
    _P.REST: "waiting",
    _P.AIM: "staging",
    _P.TURN: "ejecting",
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
        self._members: list[_TrackedPiece] = []
        self._pp = _P.VERIFY
        self._started = False
        self._halted = False
        self._serial = 0
        self._move_cmd_at = 0.0
        self._rest_since = 0.0
        self._rest_wall = 0.0
        self._last_state_ts = -1.0
        self._new_seen: dict[tuple[int, int], int] = {}
        self._merged: dict = {}
        self._cycle_start_pos: Optional[int] = None
        self._look_from = 0.0
        self._look_wall = 0.0
        self._look_frames = 0
        self._carry_frames = 0
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

    def attemptStallAutoClear(self, *, max_output_deg: float) -> ChannelClearResult:
        result = super().attemptStallAutoClear(max_output_deg=max_output_deg)
        if result.cleared:
            self._pockets = [[] for _ in range(self._n)]
            self._swept = []
            self._members = []
            self._aim_target = None
            self._halted = False
            self._started = False  # The sweep left the rotor anywhere: find rest again
            self._last_step_at = None
        return result

    def pause(self) -> None:
        self.transport.clearPieceForDistribution()
        for tp in self._pieces.values():
            if tp.placed and not tp.ejected:
                self._unplace(tp)
        self._paused_mid_cycle = self._pp in (_P.AIM, _P.TURN)
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
        # A box in RECEIVE that never became a photographed piece and is gone.
        for tp in list(self._pockets[0]):
            if not tp.capture_done and (now - tp.last_seen) > _UNSEEN_DROP_S:
                self.logger.info(f"{LOG_TAG} track={tp.track_id} left the receive pocket unphotographed; dropped")
                tp.worker.abandonInFlightObject("gone from the receive pocket before it was photographed")
                self._forget(tp)

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
        self.logger.warning(f"{LOG_TAG} track={tp.track_id} -> discard ({kind})")
        self._markDoubleFeed(tp, group, kind, message)

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
        if receive:
            if not all(tp.capture_done for tp in receive):
                return  # Still being photographed
            for tp in receive:
                frames = getattr(tp, "rest_frames", 0)
                if not tp.double_feed and frames >= _MERGED_MIN_FRAMES and 2 * getattr(tp, "merged_frames", 0) >= frames:
                    self._toDiscard(
                        tp,
                        "merged",
                        "The camera drew it as more than one piece lying together in the receive pocket "
                        "in most of its frames, so it went to the discard as a double drop.",
                    )
        elif not ahead and not exit_ and (now - self._rest_since) < _FLUSH_AFTER_S:
            return  # The feeder may add a piece: it gets its chance first
        # Two pockets in a row at the exit would empty on the same turn: no bin
        # is right for both, so both go to the discard. (Pieces are admitted an
        # empty pocket apart; this is a piece that was carried round, or a stray.)
        if exit_ and last_queue:
            for tp in exit_ + last_queue:
                self._toDiscard(
                    tp,
                    "together",
                    "It reached the classification channel's exit right behind another piece, so the "
                    "two fell together; both went to the discard.",
                )
        # The piece this turn can drop needs the chute on it first.
        going = exit_ + last_queue
        if going:
            if not all(tp.result_applied for tp in going):
                return  # Not identified yet
            lead = going[0]
            if not lead.placed:
                if self.transport.getPieceForDistributionPositioning() is None:
                    self._place(lead)
                return
            if not self._headReady(lead):
                return  # The chute is not on it yet
        self._cycle_start_pos = int(stepper.position)
        self.noteProgress()
        try:
            self._cycles.rotated(time.time(), ejecting=bool(exit_))
        except Exception:
            pass
        self._move(stepper, self._pitch_us, self.ctx.config.rotate_speed_usteps_per_s, now, "turn")
        self._enter(_P.TURN)

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
        if not bool(stepper.move_steps(direction * microsteps, acceleration=_TURN_ACCEL_USTEPS_PER_S2)):
            self.logger.error(f"{LOG_TAG} {what} was not acknowledged")
        self._move_cmd_at = now

    # --------------------------------------------------------------- TURN, LOOK

    def _turn(self, state, perception_service, stepper, now: float, moving: bool) -> None:
        if moving:
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
        self._new_seen = {}
        self._enter(_P.LOOK)

    def _look(self, state, perception_service, stepper, now: float, moving: bool) -> None:
        """At rest after a turn that swept the EXIT pocket: is its piece in the
        RECEIVE pocket? Nothing else can be there: the feeder was held."""
        if moving:
            return
        if not self._swept:
            self._finishCycle(now)
            return
        if self._fresh(state, self._look_wall):
            self._look_frames += 1
            if any(self._station(po.com_forward_to_exit_deg) == 0 for po in getattr(state, "pieces", ())):
                self._carry_frames += 1
        waited = now - self._look_from
        if waited < _LOOK_S or (self._look_frames < _LOOK_FRAMES and waited < 3 * _LOOK_S):
            return
        if self._carry_frames >= 2:
            self._carriedRound(now)
            return
        lead = self._swept[0]
        self._commitToDistribution(lead)
        self.logger.info(f"{LOG_TAG} ejected track={lead.track_id}")
        self._members = self._swept[1:]
        self._swept = []
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

    def _carriedRound(self, now: float) -> None:
        """The swept pocket's piece did not fall: it is in the RECEIVE pocket,
        and goes round again. To the discard this time: the same look cannot
        tell it from a piece that landed late, and no bin is right for that."""
        swept, self._swept = self._swept, []
        for tp in swept:
            tp.carried = getattr(tp, "carried", 0) + 1
            if tp.placed and not tp.ejected:
                self.transport.clearPieceForDistribution(tp.known_object)
                self._unplace(tp)
            self._toDiscard(
                tp,
                "did_not_fall",
                "It was still on the classification channel after the turn that sweeps the exit, so it "
                "went round again, to the discard.",
            )
            tp.zone = _ZONE_DROP
        self.logger.warning(
            f"{LOG_TAG} track={'+'.join(str(tp.track_id) for tp in swept)} did not fall: carried round into the receive pocket"
        )
        self._pockets[0] = swept + self._pockets[0]
        if any(getattr(tp, "carried", 0) >= _CARRY_MAX for tp in swept):
            self.logger.error(
                f"{LOG_TAG} a piece has gone round {_CARRY_MAX} times without falling: the channel stops until it is cleared"
            )
            self._halted = True
        self._finishCycle(now)

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
        self._startVerify(now)

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
            if not self._headReady(tp):
                return
        self._aim_target = None
        what = "correction" if self._after_aim_phase == _P.CORRECT else "turn"
        self._move(
            stepper, self._after_aim_us, self.ctx.config.rotate_speed_usteps_per_s, now, what, back=self._after_aim_back
        )
        self._enter(self._after_aim_phase)

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
        empty = not any(self._pockets)
        if not empty and abs(off) > _CORRECT_MAX_DEG:
            self.logger.error(f"{LOG_TAG} the fins stand {abs(off):.1f}° off rest with pieces on the channel; not corrected")
            self._off_seen = None
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
        self._toRest(now)

    def _toRest(self, now: float) -> None:
        self._rest_since = now
        self._rest_wall = time.time()
        self._new_seen = {}
        self._enter(_P.REST)
