import logging
import math
from queue import Queue
from types import SimpleNamespace

import pytest

from defs.known_object import ClassificationStatus, PieceStage
from irl.config import ClassificationChannelConfig
from perception.state import ChannelState, PieceObservation
from piece_transport import ClassificationChannelTransport
from subsystems.classification_channel.indexed_buffer import (
    IndexedBufferClassificationChannel, PocketGeometry, bounded_move,
)
from subsystems.classification_channel.simple_state_machine_rev01.context import SimpleStateMachineRev01Context
from subsystems.shared_variables import SharedVariables


def observation(tid, angle, gap, zone=3):
    x = 500+300*math.cos(math.radians(angle))
    y = 500+300*math.sin(math.radians(angle))
    return PieceObservation(gap, int(angle) % 360, zone,
                            (round(x-5), round(y-5), round(x+5), round(y+5)), tid)


@pytest.mark.parametrize("direction", [1, -1])
def test_whole_pocket_is_protected_not_just_piece_center(direction):
    geometry = PocketGeometry((500, 500), 0, direction)
    head = observation(1, 36, 60)
    follower = observation(2, 108, 132)
    assert bounded_move(72, geometry, [head, follower]) == pytest.approx(19, abs=0.2)
    assert bounded_move(72, geometry, [head, follower], released_id=1) == 72
    assert bounded_move(500, geometry, [head, follower], released_id=1) == 72


def test_releasing_head_still_protects_next_pocket():
    geometry = PocketGeometry((500, 500), 0, 1)
    head = observation(1, 36, -5)
    follower = observation(2, 108, 67)
    assert bounded_move(72, geometry, [head, follower], released_id=1) == pytest.approx(26, abs=0.2)
    assert bounded_move(72, geometry, [head, follower]) == 0


def test_divider_straddling_wide_or_invalid_box_has_no_single_pocket():
    geometry = PocketGeometry((500, 500), 0, 1)
    assert geometry.box_pocket(observation(1, 36, 100).bbox) == 0
    assert geometry.box_pocket((750, 490, 810, 510)) is None
    assert geometry.box_pocket((400, 400, 600, 600)) is None
    assert geometry.box_pocket((0, 0, 0, 0)) is None


class Rig:
    """Real controller/identity/transport, simulated camera, motor and capture.

    Motor completion and camera frames are separate events; classification and
    chute positioning are controlled independently of the scheduler.
    """
    def __init__(self, monkeypatch):
        self.now = 100.0
        monkeypatch.setattr("time.time", lambda: self.now)
        monkeypatch.setattr("time.monotonic", lambda: self.now)
        self.pieces = []
        self.state = ChannelState(self.now, False, False, 0)
        self.channel = SimpleNamespace(center=(500, 500), reverse=False, has_zones=True,
                                       radius1_angle_image=0, drop_sections=frozenset(range(32, 41)))
        self.service = SimpleNamespace(read_state=lambda _: self.state, channels=lambda: {4: self.channel})
        self.motor = SimpleNamespace(stopped=True)
        self.c3 = SimpleNamespace(stopped=True)
        self.shared = SharedVariables()
        self.transport = ClassificationChannelTransport()
        self.h = IndexedBufferClassificationChannel(
            SimpleNamespace(carousel_stepper=self.motor, c_channel_3_rotor_stepper=self.c3),
            SimpleNamespace(classification_channel_config=ClassificationChannelConfig()),
            SimpleNamespace(logger=logging.getLogger("indexed-test"), perception_service=self.service),
            self.shared, self.transport, None, Queue(), SimpleStateMachineRev01Context())
        self.h._geometry = PocketGeometry((500, 500), 0, 1)
        self.h._index_phase = 0
        self.h.ctx.config.low_confidence_retry = False
        self.moves = []
        def move(angle, speed):
            self.moves.append(abs(angle))
            self.motor.stopped = False
            return True
        self.h.startOutputMove = move
        self.h._reference = lambda *args: True
        def capture(*args):
            for tp in self.h._pieces.values():
                if tp.zone == 1:
                    tp.capture_done = True
        self.h._captureDropPieces = capture

    def tick(self, elapsed=0.1):
        self.now += elapsed
        self.state = ChannelState(self.now, any(p.zone_code == 1 for p in self.pieces),
                                  any(p.zone_code == 2 for p in self.pieces), len(self.pieces),
                                  pieces=tuple(self.pieces))
        self.h.step()

    def arrive(self, tid):
        self.pieces.append(observation(tid, 36, 216, 1))
        self.tick()

    def finish(self):
        move = self.moves[-1]
        self.pieces = [observation(p.sv_bt_track_id, p.com_section+move,
                                   p.com_forward_to_exit_deg-move,
                                   2 if p.com_forward_to_exit_deg-move <= 10 else 3)
                       for p in self.pieces]
        self.motor.stopped = True
        self.tick()  # observes stopped; old frames still forbidden
        self.tick()  # new optical reference and updated observations

    def classify_and_aim(self, tid):
        tp = self.h._pieces[tid]
        self.h._ensureKnownObject(tp)
        tp.known_object.classification_status = ClassificationStatus.classified
        tp.result_applied = True
        self.tick()
        tp.known_object.stage = PieceStage.distributing
        self.shared.distribution_ready = True
        return tp


def test_three_parts_buffer_while_first_classification_is_pending(monkeypatch):
    rig = Rig(monkeypatch)
    rig.arrive(1)
    rig.tick(1.1)
    assert rig.moves == [72]
    rig.finish()
    assert rig.shared.classification_ready
    rig.arrive(2)
    rig.tick(1.1)
    assert rig.moves == [72, 72]
    rig.finish()
    assert rig.shared.classification_ready
    rig.arrive(3)
    assert len(rig.h._reservations) == 3
    assert not rig.h._pieces[1].result_applied
    rig.tick(1.1)
    assert 30 < rig.moves[-1] < 32  # stop before first pocket touches outlet
    rig.finish()
    count = len(rig.moves)
    rig.tick(2)
    assert len(rig.moves) == count
    assert rig.transport.getPieceForDistributionDrop() is None


def test_missing_piece_reserves_pocket_across_timeout_and_new_id_recovers(monkeypatch):
    rig = Rig(monkeypatch)
    rig.arrive(1)
    original = rig.h._pieces[1]
    rig.pieces = []
    rig.tick(20)
    assert list(rig.h._reservations.values()) == [original]
    assert not rig.shared.classification_ready and not rig.moves
    rig.pieces = [observation(77, 36, 216, 1)]
    rig.tick()
    assert rig.h._aliases[77] is original
    assert len(rig.h._pieces) == 1


def test_known_id_cannot_jump_into_another_reserved_pocket(monkeypatch):
    rig = Rig(monkeypatch)
    rig.arrive(1)
    rig.pieces = [observation(1, 108, 144)]
    rig.tick(2)
    assert "ambiguous" in rig.h.phaseName()
    assert not rig.moves and not rig.shared.classification_ready


def test_double_arrival_holds_without_assigning_two_results(monkeypatch):
    rig = Rig(monkeypatch)
    rig.pieces = [observation(1, 30, 222, 1), observation(2, 42, 210, 1)]
    rig.tick()
    assert not rig.moves and not rig.shared.classification_ready
    assert not rig.h._reservations


def test_stale_camera_and_inflight_c3_block_motion(monkeypatch):
    rig = Rig(monkeypatch)
    rig.arrive(1)
    rig.c3.stopped = False
    rig.tick(2)
    assert not rig.moves
    rig.c3.stopped = True
    rig.tick(0.1)
    assert not rig.moves
    rig.now += 2
    rig.h.step()  # no new camera frame
    assert not rig.moves and not rig.shared.classification_ready
    rig.tick()
    assert rig.moves == [72]


def test_busy_or_wrong_distribution_slot_cannot_release_head(monkeypatch):
    rig = Rig(monkeypatch)
    rig.arrive(1)
    head = rig.classify_and_aim(1)
    assert rig.h._headReady(head)
    rig.shared.distribution_ready = False
    assert not rig.h._headReady(head)
    rig.shared.distribution_ready = True
    rig.transport.placePieceForDistribution(SimpleNamespace())
    assert not rig.h._headReady(head)


def test_recovery_never_bulk_sweeps_reserved_parts(monkeypatch):
    rig = Rig(monkeypatch)
    rig.arrive(1)
    result = rig.h.attemptStallAutoClear(max_output_deg=720)
    assert not result.cleared and result.output_deg_moved == 0
    assert not rig.moves and rig.h.hasReservations()


def test_restart_requires_empty_camera_before_optical_reference(monkeypatch):
    rig = Rig(monkeypatch)
    rig.h._geometry = None
    rig.arrive(1)
    assert not rig.moves and not rig.shared.classification_ready
    assert "empty platter" in rig.h.phaseName()


def test_divider_reference_rejects_regular_fit_with_large_residuals(monkeypatch):
    rig = Rig(monkeypatch)
    monkeypatch.setattr("vision.c4_wall_phase.calibrated_c4_wall_geometry", lambda shape: {})
    rig.service.read_bboxes_and_frame = lambda _: ([], SimpleNamespace(timestamp=rig.now, bgr=SimpleNamespace(shape=(1000, 1000, 3))))
    monkeypatch.setattr("vision.c4_wall_phase.detect_c4_wall_phase", lambda *a, **kw: SimpleNamespace(
        ok=True, sector_offset_deg=3, wall_angles_deg=[64, 144, 225, 295, 357], center_x=500, center_y=500))
    assert not IndexedBufferClassificationChannel._reference(rig.h, rig.service, rig.state, rig.now)
    assert "disagree" in rig.h.phaseName()


def test_one_piece_drains_without_successor_and_only_commits_after_exit(monkeypatch):
    rig = Rig(monkeypatch)
    rig.arrive(1)
    target = rig.classify_and_aim(1)
    rig.tick(1.1)
    rig.finish()
    rig.tick(3.1)
    rig.tick(1.1)
    rig.finish()
    rig.tick(1.1)
    rig.finish()
    assert target.gap_to_exit <= 0
    assert rig.transport.getPieceForDistributionDrop() is None
    rig.pieces = []
    rig.tick()
    rig.tick(0.3)
    assert not target.ejected
    rig.tick(0.3)
    assert target.ejected
    assert rig.transport.getPieceForDistributionDrop() is target.known_object
    assert not rig.h._reservations


def test_disappearance_upstream_is_not_an_exit_even_after_timeout(monkeypatch):
    rig = Rig(monkeypatch)
    rig.arrive(1)
    target = rig.classify_and_aim(1)
    rig.tick(1.1)
    rig.finish()
    rig.pieces = []
    for _ in range(5):
        rig.tick(10)
    assert not target.ejected
    assert rig.transport.getPieceForDistributionPositioning() is target.known_object
    assert rig.transport.getPieceForDistributionDrop() is None


def test_cleanup_forces_new_reference_and_does_not_resume_old_reservations(monkeypatch):
    rig = Rig(monkeypatch)
    rig.arrive(1)
    rig.h.cleanup()
    assert not rig.h.hasReservations() and rig.h._geometry is None
    rig.tick()
    assert not rig.moves and not rig.shared.classification_ready


def test_eject_head_keeps_successors_and_their_results_in_separate_pockets(monkeypatch):
    rig = Rig(monkeypatch)
    for tid in (1, 2):
        rig.arrive(tid)
        rig.tick(1.1)
        rig.finish()
    rig.arrive(3)
    head = rig.classify_and_aim(1)
    successors = [rig.h._pieces[2], rig.h._pieces[3]]
    rig.tick(1.1)
    rig.finish()
    assert head.gap_to_exit == pytest.approx(0, abs=0.5)
    rig.pieces = [p for p in rig.pieces if p.sv_bt_track_id != 1]
    rig.tick()
    rig.tick(0.6)
    assert head.ejected
    assert set(rig.h._reservations.values()) == set(successors)
    assert rig.transport.getPieceForDistributionDrop() is head.known_object
    assert all(tp.gap_to_exit >= 72 for tp in successors)
    next_head = rig.classify_and_aim(2)
    assert rig.transport.getPieceForDistributionPositioning() is next_head.known_object
    assert rig.transport.getPieceForDistributionDrop() is head.known_object


def test_capture_in_progress_holds_every_pocket(monkeypatch):
    rig = Rig(monkeypatch)
    rig.h._captureDropPieces = lambda *args: None
    rig.arrive(1)
    rig.tick(5)
    assert not rig.moves and not rig.shared.classification_ready


def test_failed_motor_ack_latches_hold_and_keeps_reservation(monkeypatch):
    rig = Rig(monkeypatch)
    rig.h.startOutputMove = lambda *args: False
    rig.arrive(1)
    rig.tick(2)
    assert rig.h._move == -1
    rig.tick(2)
    assert rig.h._move == -1 and rig.h.hasReservations()
    assert not rig.shared.classification_ready


def test_new_phase_must_match_command_before_followup_motion(monkeypatch):
    rig = Rig(monkeypatch)
    monkeypatch.setattr("vision.c4_wall_phase.calibrated_c4_wall_geometry", lambda shape: {})
    rig.service.read_bboxes_and_frame = lambda _: ([], SimpleNamespace(timestamp=rig.now, bgr=SimpleNamespace(shape=(1000, 1000, 3))))
    monkeypatch.setattr("vision.c4_wall_phase.detect_c4_wall_phase", lambda *a, **kw: SimpleNamespace(
        ok=True, sector_offset_deg=20, wall_angles_deg=[20, 92, 164, 236, 308], center_x=500, center_y=500))
    assert not IndexedBufferClassificationChannel._reference(rig.h, rig.service, rig.state, rig.now)
    assert "expected divider phase" in rig.h.phaseName()
