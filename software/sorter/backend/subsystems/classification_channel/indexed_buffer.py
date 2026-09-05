"""Opt-in, optically referenced five-pocket C4 buffer.

Reservations outlive detector IDs. All motion is bounded by the leading wall
of every reserved pocket except the one whose distribution target is ready.
Camera/identity uncertainty closes admission and retains the target bin.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

from .five_sector_platter import angle_deg_for_point
from .simple_state_machine_rev01.channel_clear import ChannelClearResult
from .simple_state_machine_rev01.constants import C4_TRAVEL_SIGN
from .two_piece import TwoPieceClassificationChannel, _exitArcOccupied

PITCH = 72.0
MARGIN = 5.0
MAX_FRAME_AGE = 1.0
INFLIGHT_SETTLE = 1.0


@dataclass(frozen=True)
class PocketGeometry:
    center: tuple[float, float]
    phase: float
    direction: int

    def angle(self, x, y):
        return angle_deg_for_point(x, y, center_xy=self.center)

    def pocket(self, angle):
        return int(((angle - self.phase) % 360.0) // PITCH)

    def box_pocket(self, bbox):
        x1, y1, x2, y2 = bbox
        cx, cy = self.center
        if x2 <= x1 or y2 <= y1 or (x1 <= cx <= x2 and y1 <= cy <= y2):
            return None
        angles = [self.angle(x, y) for x in (x1, x2) for y in (y1, y2)]
        pockets = {self.pocket(a) for a in angles}
        if len(pockets) != 1:
            return None
        # A bbox close to a divider is ambiguous too, even if its COM is clear.
        if any(min((a-self.phase) % PITCH, PITCH-(a-self.phase) % PITCH) < MARGIN for a in angles):
            return None
        return pockets.pop()

    def wall_clearance(self, observation):
        x1, y1, x2, y2 = observation.bbox
        angle = self.angle((x1+x2)/2, (y1+y2)/2)
        offset = (angle-self.phase) % PITCH
        to_wall = PITCH-offset if self.direction > 0 else offset
        return float(observation.com_forward_to_exit_deg) - to_wall - MARGIN


def bounded_move(requested, geometry, observations, released_id=None):
    """Protect the *whole* swept pocket, including an unobserved trailing edge."""
    limit = min(PITCH, max(0.0, requested))
    for observation in observations:
        if observation.sv_bt_track_id != released_id:
            clearance = geometry.wall_clearance(observation)
            if not math.isfinite(clearance):
                return 0.0
            limit = min(limit, max(0.0, clearance))
    return limit


class IndexedBufferClassificationChannel(TwoPieceClassificationChannel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._geometry = None
        self._reservations = {}  # physical pocket -> _TrackedPiece
        self._move = None
        self._move_started = 0.0
        self._settled_at = 0.0
        self._frame_after = 0.0
        self._gate_closed_at = time.monotonic()
        self._admitting = False
        self._last_frame = 0.0
        self._empty_since = None
        self._exit_armed = False
        self._exit_empty_since = None
        self._blocked = "waiting for empty platter and optical reference"
        self._last_phase_attempt = 0.0
        self._index_phase = None
        self._eject_budget = 0.0
        self.status_snapshot = {}
        self._last_status = None

    def phaseName(self):
        return "indexed: " + (self._blocked or ("moving" if self._move else "buffering"))

    def hasReservations(self):
        return bool(self._reservations)

    def attemptStallAutoClear(self, *, max_output_deg):
        self._gate(False, time.monotonic())
        return ChannelClearResult(False, bool(self._reservations), 0.0, "indexed_buffer_requires_inspection")

    def _retireGonePieces(self, now):
        # Only a confirmed exit releases a reservation. A timeout cannot do so.
        pass

    def _aliasOverlappingPiece(self, *args):
        return None

    def _aliasNearestForwardPiece(self, *args):
        return None

    def _headPiece(self):
        candidates = [tp for tp in self._reservations.values() if not tp.ejected]
        return min(candidates, key=lambda tp: tp.gap_to_exit if tp.gap_to_exit is not None else math.inf, default=None)

    def _aimChuteForHead(self, now):
        head = self._headPiece()
        slot = self.transport.getPieceForDistributionPositioning()
        if slot is not None and (head is None or slot is not head.known_object):
            return
        super()._aimChuteForHead(now)

    def _headReady(self, tp):
        return (super()._headReady(tp)
                and self.transport.getPieceForDistributionPositioning() is tp.known_object)

    def _gate(self, ready, now):
        if self._admitting and not ready:
            self._gate_closed_at = now
        self._admitting = ready
        reason = self.phaseName()
        if reason != self._last_status:
            self.logger.info("[C4-INDEXED] %s", reason)
            self._last_status = reason
        self.status_snapshot = {
            "phase": reason, "admission_ready": ready,
            "divider_phase_deg": self._geometry.phase if self._geometry else None,
            "move_output_deg": self._move,
            "pockets": [{"pocket": p, "track_id": tp.track_id,
                         "captured": tp.capture_done, "result_applied": tp.result_applied,
                         "placed": tp.placed, "gap_to_exit_deg": tp.gap_to_exit}
                        for p, tp in sorted(self._reservations.items())],
        }
        self.setClassificationReady(ready, self.phaseName())

    def cleanup(self):
        super().cleanup()
        self._reservations = {}
        self._geometry = None
        self._index_phase = None
        self._move = None
        self._eject_target = None
        self._stage_target = None
        self._empty_since = None
        self._exit_empty_since = None
        self._exit_armed = False
        self._last_frame = 0.0
        self._blocked = "restart requires empty platter and new optical reference"
        self._gate(False, time.monotonic())

    def _reference(self, service, state, now):
        if now - self._last_phase_attempt < 1.0:
            return False
        self._last_phase_attempt = now
        raw = service.read_bboxes_and_frame(4)
        channel = service.channels().get(4)
        if raw is None or channel is None or not channel.has_zones:
            self._blocked = "missing camera or calibrated zones"
            return False
        from vision.c4_wall_phase import detect_c4_wall_phase, calibrated_c4_wall_geometry
        frame = raw[1]
        if frame.timestamp < self._frame_after or abs(time.time()-frame.timestamp) > MAX_FRAME_AGE:
            return False
        try:
            geometry = calibrated_c4_wall_geometry(frame.bgr.shape)
            phase = detect_c4_wall_phase(frame.bgr, **geometry)
        except (ValueError, KeyError, TypeError):
            self._blocked = "invalid divider camera calibration"
            return False
        if not phase.ok or phase.sector_offset_deg is None:
            self._blocked = "divider reference not reliable"
            return False
        residuals = [abs((a-phase.sector_offset_deg+PITCH/2) % PITCH-PITCH/2)
                     for a in phase.wall_angles_deg]
        if len(residuals) < 3 or max(residuals) > MARGIN:
            self._blocked = "divider angles disagree with five-pocket geometry"
            return False
        center = channel.center
        if phase.center_x is None or phase.center_y is None or math.dist(center, (phase.center_x, phase.center_y)) > 20:
            self._blocked = "optical and calibrated centers disagree"
            return False
        offset = phase.sector_offset_deg
        if self._geometry is not None:
            # The commanded angle unwraps the otherwise 72-degree periodic image.
            expected = self._geometry.phase
            error = (offset-expected+PITCH/2) % PITCH-PITCH/2
            if abs(error) > MARGIN:
                self._blocked = "rotor did not reach expected divider phase"
                return False
            offset = expected + error
        self._geometry = PocketGeometry(center, offset, -1 if channel.reverse else 1)
        if self._index_phase is None:
            self._index_phase = offset
        return True

    def _reconcile(self, state, now):
        # Re-identify within the reserved physical pocket, never across pockets.
        observed = {}
        for po in state.pieces:
            if po.sv_bt_track_id is None:
                return False
            pocket = self._geometry.box_pocket(po.bbox)
            if pocket is None or pocket in observed:
                return False
            observed[pocket] = po
        for pocket, po in observed.items():
            existing = self._pieces.get(po.sv_bt_track_id) or self._aliases.get(po.sv_bt_track_id)
            reserved = self._reservations.get(pocket)
            if existing is not None and existing is not reserved:
                return False
            if reserved is not None:
                self._aliases[po.sv_bt_track_id] = reserved
        self._observe(state, now)
        for pocket, po in observed.items():
            tp = self._pieces.get(po.sv_bt_track_id) or self._aliases.get(po.sv_bt_track_id)
            self._reservations[pocket] = tp
        missing = [tp for p, tp in self._reservations.items() if p not in observed]
        return not any(tp is not self._eject_target for tp in missing)

    def _landingPocket(self, service):
        channel = service.channels().get(4)
        if channel is None or not channel.drop_sections:
            return None
        angles = [channel.radius1_angle_image+s for s in channel.drop_sections]
        pockets = {self._geometry.pocket(a) for a in angles}
        if len(pockets) != 1:
            return None
        if any(min((a-self._geometry.phase) % PITCH, PITCH-(a-self._geometry.phase) % PITCH) < MARGIN for a in angles):
            return None
        return pockets.pop()

    def _startMove(self, move, now, eject=False):
        if move < 1.0:
            return
        self._gate(False, now)
        if now-self._gate_closed_at < INFLIGHT_SETTLE:
            return
        c3 = getattr(self.irl, "c_channel_3_rotor_stepper", None)
        if c3 is None or not c3.stopped:
            self._gate_closed_at = now
            return
        if self.startOutputMove(C4_TRAVEL_SIGN*move, self.ctx.config.precise_converge_speed_usteps_per_s):
            self._move = move
            self._move_started = now
            self._frame_after = time.time()
            if eject and self._eject_target.gap_to_exit is not None:
                self._eject_budget -= move
        else:
            self._blocked = "motor command failed; reference requires restart"
            self._move = -1  # latch; do not infer an unacknowledged motor position

    def step(self):
        now = time.monotonic()
        service = getattr(self.gc, "perception_service", None)
        stepper = getattr(self.irl, "carousel_stepper", None)
        if service is None or stepper is None:
            self._blocked = "missing perception or stepper"
            self._gate(False, now)
            return
        state = service.read_state(4)
        if not (0 <= time.time()-state.ts <= MAX_FRAME_AGE):
            self._blocked = "stale camera"
            self._gate(False, now)
            return
        # Observe the output even during motion. A commanded angle cannot prove
        # that the part travelled with the rotor; require seeing this identity
        # reach the exit before its disappearance can count as delivery.
        if self._eject_target is not None:
            for po in state.pieces:
                tp = self._pieces.get(po.sv_bt_track_id) or self._aliases.get(po.sv_bt_track_id)
                if tp is self._eject_target and po.com_forward_to_exit_deg <= 0:
                    self._exit_armed = True
        if not stepper.stopped:
            self._gate(False, now)
            return
        if self._move is not None:
            self._gate(False, now)
            if self._move < 0:
                return
            # Require a newly captured frame *after* observing the motor stopped.
            if self._move > 0:
                self._geometry = PocketGeometry(self._geometry.center, self._geometry.phase+self._geometry.direction*self._move, self._geometry.direction)
                self._move = 0.0
                self._settled_at = now
                self._frame_after = time.time()
                return
            if state.ts <= self._frame_after or not self._reference(service, state, now):
                return
            self._move = None
        if self._geometry is None:
            self._gate(False, now)
            if state.n_pieces:
                self._empty_since = None
                self._blocked = "start requires an empty platter"
                return
            if self._empty_since is None:
                self._empty_since = now
            if now-self._empty_since < 1.0 or not self._reference(service, state, now):
                return
        if state.ts == self._last_frame:
            return
        self._last_frame = state.ts
        self._blocked = ""
        if state.n_pieces != len(state.pieces) or not self._reconcile(state, now):
            self._blocked = "ambiguous or missing pocket occupancy"
            self._gate(False, now)
            return
        self._applyResults(now)
        self._captureDropPieces(service, now)
        self._captureRetryHead(service, now)
        self._aimChuteForHead(now)
        target = self._eject_target
        if target is not None and target.last_seen == now and target.gap_to_exit <= 0:
            self._exit_armed = True
        if target is not None and target.last_seen < now:
            self._gate(False, now)
            if not self._exit_armed or _exitArcOccupied(state):
                self._exit_empty_since = None
                return
            if self._exit_empty_since is None:
                self._exit_empty_since = now
            if now-self._exit_empty_since >= 0.5 and self._headReady(target):
                self.transport.advanceTransport()
                target.ejected = True
                self._reservations = {p: tp for p, tp in self._reservations.items() if tp is not target}
                self._pieces = {i: tp for i, tp in self._pieces.items() if tp is not target}
                self._aliases = {i: tp for i, tp in self._aliases.items() if tp is not target}
                self._eject_target = None
                self._exit_armed = False
                self._exit_empty_since = None
                self.noteProgress()
            return
        self._exit_empty_since = None
        if self._exit_armed and now-self._settled_at < 0.5:
            self._gate(False, now)
            return
        landing = self._landingPocket(service)
        ready = landing is not None and landing not in self._reservations and not state.in_drop
        # No hard two-piece limit: capacity follows the occupied arc and output
        # clearance. The fifth pocket remains unavailable at the open outlet.
        ready &= len(self._reservations) < 4
        incomplete = any(not tp.capture_done for tp in self._reservations.values())
        if incomplete:
            self._gate(ready, now)
            return
        head = self._headPiece()
        if head is None:
            self._gate(ready, now)
            if not ready:
                self._blocked = "align empty platter: landing arc crosses a divider"
            return
        # Fill an available pocket while classification/aiming runs. Drain a
        # sparse feed after the existing short grace, without requiring a successor.
        if ready and not (self._headReady(head) and now-head.placed_at >= 3.0):
            self._gate(True, now)
            return
        release = self._headReady(head)
        if release and self._eject_target is None:
            self._eject_target = head
            self._eject_budget = max(0.0, head.gap_to_exit or 0.0) + PITCH
        ids = [po.sv_bt_track_id for po in state.pieces
               if (self._pieces.get(po.sv_bt_track_id) or self._aliases.get(po.sv_bt_track_id)) is head]
        progress = (self._geometry.direction*(self._geometry.phase-self._index_phase)) % PITCH
        requested = PITCH-progress if 1.0 < progress < PITCH-1.0 else PITCH
        if release:
            requested = min(requested, self._eject_budget)
            if self._exit_armed:
                requested = min(requested, 5.0)
        move = bounded_move(requested, self._geometry, state.pieces, ids[0] if release and ids else None)
        if move < 1:
            self._blocked = "waiting for head result and distribution target"
            self._gate(False, now)
            return
        self._startMove(move, now, eject=release)
