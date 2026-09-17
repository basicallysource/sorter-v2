"""A multi-drop clump belongs in the bottom bucket, whole.

Only the clump member that becomes the head is ever handed to distribution, and
distribution opens every door for it. The siblings touch it, so the detector
merges and re-ids them: on a production machine 60 of 101 clump members were
never routed at all, and 22 of them left the platter while a layer door was
closed for some later piece — i.e. into a customer's sorted bin. The forced
channel sweep had the same hole, by design: it dumped the platter "wherever the
chute happens to point", and 11 of 66 sweeps ran with a door closed.

These tests pin the two rules that follow: a sweep opens every door before it
turns, and losing an unrouted clump member keeps the doors open until it has had
its chance to fall.
"""

from __future__ import annotations

import logging
import queue
import time
from types import SimpleNamespace
from unittest.mock import patch

from defs.known_object import ClassificationStatus, KnownObject, PieceStage
from piece_transport import ClassificationChannelTransport
from subsystems.classification_channel import two_piece
from subsystems.classification_channel.simple_state_machine_rev01 import channel_clear
from subsystems.classification_channel.simple_state_machine_rev01.channel_clear import (
    ChannelClearResult,
    clearChannelByAdvancing,
)
from subsystems.classification_channel.two_piece import (
    _Phase,
    _TrackedPiece,
    TwoPieceClassificationChannel,
)
from subsystems.distribution.chute import BinAddress
from subsystems.distribution.positioning import Positioning
from subsystems.distribution.states import DistributionState
from subsystems.shared_variables import SharedVariables

_LOGGER = logging.getLogger("test_c4_multi_drop_doors")
_PRECISE_ZONE = 3


class _Servo:
    available = True

    def __init__(self, log: list[str], index: int, *, shadow_open: bool = False) -> None:
        self._log = log
        self._index = index
        self._shadow_open = shadow_open
        self.open_calls = 0
        self.close_calls = 0

    def isClosed(self) -> bool:
        return not self._shadow_open

    def open(self) -> None:
        self.open_calls += 1
        self._shadow_open = True
        self._log.append(f"open{self._index}")

    def close(self) -> None:
        self.close_calls += 1
        self._shadow_open = False
        self._log.append(f"close{self._index}")

    def apply_open_speed(self) -> None:
        pass

    def apply_close_speed(self) -> None:
        pass

    @property
    def stopped(self) -> bool:
        return True


class _Stepper:
    def __init__(self, log: list[str]) -> None:
        self._log = log
        self.moves = 0

    def set_speed_limits(self, lo: int, hi: int) -> None:
        pass

    def estimateMoveStepsMs(self, steps: int, speed: int) -> int:
        return 10

    def move_steps_blocking(self, steps: int, timeout_ms: int = 0) -> bool:
        self.moves += 1
        self._log.append(f"move{self.moves}")
        return True


class _Perception:
    """Reports the channel occupied until the sweep has taken `clears_after` steps."""

    def __init__(self, stepper: _Stepper, clears_after: int = 1) -> None:
        self._stepper = stepper
        self._clears_after = clears_after

    def read_state(self, channel: int):
        assert channel == 4
        return SimpleNamespace(n_pieces=0 if self._stepper.moves >= self._clears_after else 1)


def _mkSweepWorld(*, disable_servos: bool = False, servo_count: int = 3):
    log: list[str] = []
    stepper = _Stepper(log)
    servos = [_Servo(log, i) for i in range(servo_count)]
    gc = SimpleNamespace(
        logger=_LOGGER,
        disable_servos=disable_servos,
        perception_service=_Perception(stepper),
    )
    irl = SimpleNamespace(carousel_stepper=stepper, servos=servos)
    return gc, irl, servos, log


# ------------------------------------------------------------------ the sweep


def test_sweep_opens_every_door_before_it_turns_the_platter() -> None:
    gc, irl, servos, log = _mkSweepWorld()

    result = clearChannelByAdvancing(gc, irl, SimpleNamespace(), label="[TEST]")

    assert result.cleared
    assert [servo.open_calls for servo in servos] == [1, 1, 1]
    assert log.index("open0") < log.index("move1"), log
    assert log.index("open2") < log.index("move1"), log


def test_sweep_reopens_a_door_the_shadow_state_already_calls_open() -> None:
    # The servo shadow is written even when the firmware rejects the move, so a
    # door believed open can physically be closed. The sweep must not trust it.
    gc, irl, servos, _log = _mkSweepWorld()
    for servo in servos:
        servo._shadow_open = True

    clearChannelByAdvancing(gc, irl, SimpleNamespace(), label="[TEST]")

    assert [servo.open_calls for servo in servos] == [1, 1, 1]


def test_sweep_leaves_the_doors_alone_when_servos_are_disabled() -> None:
    gc, irl, servos, log = _mkSweepWorld(disable_servos=True)

    assert clearChannelByAdvancing(gc, irl, SimpleNamespace(), label="[TEST]").cleared
    assert [servo.open_calls for servo in servos] == [0, 0, 0]
    assert log == ["move1"]


def test_sweep_of_an_empty_channel_touches_nothing() -> None:
    gc, irl, servos, log = _mkSweepWorld()
    gc.perception_service = SimpleNamespace(read_state=lambda ch: SimpleNamespace(n_pieces=0))

    result = clearChannelByAdvancing(gc, irl, SimpleNamespace(), label="[TEST]")

    assert result.reason == "already_clear"
    assert log == []


# ------------------------------------------------- the stall auto-clear's head


def _mkChannel(transport, shared) -> TwoPieceClassificationChannel:
    ch = TwoPieceClassificationChannel.__new__(TwoPieceClassificationChannel)
    ch.transport = transport
    ch.shared = shared
    ch.logger = _LOGGER
    ch.gc = SimpleNamespace()
    ch.irl = SimpleNamespace()
    ch.irl_config = SimpleNamespace()
    ch.cv = SimpleNamespace(_vision=None)
    ch.ctx = SimpleNamespace(reset=lambda: None, known_object=None)
    ch._pieces = {}
    ch._phase = _Phase.WAITING
    ch._eject_target = None
    ch._stage_target = None
    ch._phase_started_at = time.monotonic()
    ch.last_progress_at = time.monotonic()
    ch._multi_drop_streak = 0
    ch._multi_drop_last_ts = -1.0
    ch._multi_drop_seq = 0
    ch._bucket_hold_cycles = 0
    return ch


class _FakeWorker:
    def __init__(self, obj: KnownObject | None) -> None:
        self.ctx = SimpleNamespace(known_object=obj, classify_started_at=0.0)

    def emitKnownObject(self) -> None:
        pass

    def abandonInFlightObject(self, reason: str) -> None:
        pass


def _addPiece(
    ch: TwoPieceClassificationChannel,
    track_id: int,
    *,
    obj: KnownObject | None = None,
    placed: bool = False,
    double_feed: bool = False,
    last_seen_ago_s: float = 0.0,
) -> _TrackedPiece:
    now = time.monotonic()
    tp = _TrackedPiece(track_id, _FakeWorker(obj), now)
    tp.zone = _PRECISE_ZONE
    tp.gap_to_exit = 10.0
    tp.last_seen = now - last_seen_ago_s
    tp.placed = placed
    tp.double_feed = double_feed
    if obj is not None:
        tp.capture_done = True
        tp.result_applied = True
    ch._pieces[track_id] = tp
    return tp


def _clearedSweep(*args, **kwargs) -> ChannelClearResult:
    return ChannelClearResult(True, True, 144.0, "cleared")


def test_stall_clear_records_the_aimed_piece_where_it_actually_lands() -> None:
    # The sweep now runs with the doors open, so the piece the chute was aimed
    # for goes to the bucket with everything else. Its record must say so
    # instead of crediting a bin it never reached.
    transport = ClassificationChannelTransport()
    shared = SharedVariables()
    shared.transport = transport
    ch = _mkChannel(transport, shared)
    obj = KnownObject(part_id="3001", color_id="1")
    obj.classification_status = ClassificationStatus.classified
    obj.stage = PieceStage.distributing
    obj.destination_bin = (1, 2, 3)
    transport.placePieceForDistribution(obj)
    _addPiece(ch, 7, obj=obj, placed=True)

    with patch.object(two_piece, "clearChannelByAdvancing", _clearedSweep):
        assert ch.attemptStallAutoClear(max_output_deg=720.0).cleared

    assert obj.destination_bin is None
    assert transport.getPieceForDistributionDrop() is obj


# --------------------------------------------------- the loose clump member


def _mkShared() -> SharedVariables:
    shared = SharedVariables()
    shared.transport = ClassificationChannelTransport()
    return shared


def test_losing_an_unrouted_clump_member_holds_the_doors_open() -> None:
    shared = _mkShared()
    ch = _mkChannel(shared.transport, shared)
    _addPiece(ch, 41, double_feed=True, last_seen_ago_s=two_piece._TRACK_GONE_RETIRE_S + 0.1)

    ch._retireGonePieces(time.monotonic())

    assert shared.bucket_passthrough_hold is True
    assert ch._bucket_hold_cycles == two_piece._BUCKET_HOLD_EJECTS


def test_losing_an_ordinary_piece_does_not_hold_the_doors() -> None:
    # Only a multi-drop leaves a sibling on the platter we never routed. Holding
    # on every lost track would send most of the machine's output to the bucket.
    shared = _mkShared()
    ch = _mkChannel(shared.transport, shared)
    _addPiece(ch, 42, last_seen_ago_s=two_piece._TRACK_GONE_RETIRE_S + 0.1)

    ch._retireGonePieces(time.monotonic())

    assert shared.bucket_passthrough_hold is False


def test_the_hold_ends_after_the_loose_piece_has_had_its_ejects() -> None:
    shared = _mkShared()
    ch = _mkChannel(shared.transport, shared)
    ch._holdBucket("test")

    for _ in range(two_piece._BUCKET_HOLD_EJECTS):
        assert shared.bucket_passthrough_hold is True
        target = _addPiece(ch, 50, last_seen_ago_s=1.0)
        ch._eject_target = target
        ch._ejecting(SimpleNamespace(exit_com_forward_to_center_deg=None), True, time.monotonic())
        del ch._pieces[50]

    assert shared.bucket_passthrough_hold is False


def test_an_empty_channel_ends_the_hold_early() -> None:
    shared = _mkShared()
    ch = _mkChannel(shared.transport, shared)
    ch.gc = SimpleNamespace(
        logger=_LOGGER,
        perception_service=SimpleNamespace(
            read_state=lambda ch_id: SimpleNamespace(n_pieces=0, in_drop=False, pieces=())
        ),
    )
    ch.irl = SimpleNamespace(carousel_stepper=SimpleNamespace(stopped=True))
    ch.ctx = SimpleNamespace(config=SimpleNamespace(multi_feed_confirm_reads=3))
    ch.setClassificationReady = lambda ready, reason: None
    ch._captureDropPieces = lambda perception_service, now: None
    ch._holdBucket("test")

    ch.step()

    assert shared.bucket_passthrough_hold is False


def test_teardown_ends_the_hold_so_it_cannot_strand_distribution() -> None:
    shared = _mkShared()
    ch = _mkChannel(shared.transport, shared)
    ch._holdBucket("test")

    ch.cleanup()

    assert shared.bucket_passthrough_hold is False


# ------------------------------------------------- distribution honours the hold


class _Logger:
    def info(self, *args, **kwargs) -> None:
        pass

    def warning(self, *args, **kwargs) -> None:
        pass

    def warn(self, *args, **kwargs) -> None:
        pass

    def debug(self, *args, **kwargs) -> None:
        pass


def _mkPositioning(shared, servos, log):
    gc = SimpleNamespace(
        logger=_Logger(),
        runtime_stats=SimpleNamespace(observeStateTransition=lambda *a, **k: None),
        disable_servos=False,
    )
    layout = SimpleNamespace(
        layers=[SimpleNamespace(enabled=True, max_dimension_mm=None) for _ in servos]
    )
    chute = SimpleNamespace(
        moveToBin=lambda address: log.append("chute_move") or 100,
        isBinReachable=lambda address: True,
        stepper=SimpleNamespace(stopped=True),
    )
    sorting_profile = SimpleNamespace(
        getCategoryIdForPart=lambda part_id, color_id: "cat_a",
        highValueCategoryId=lambda price: None,
    )
    positioning = Positioning(
        SimpleNamespace(servos=servos),  # type: ignore[arg-type]
        gc,  # type: ignore[arg-type]
        shared,
        chute,  # type: ignore[arg-type]
        layout,  # type: ignore[arg-type]
        sorting_profile,  # type: ignore[arg-type]
        queue.Queue(),
    )
    positioning._findOrAssignBinForCategory = lambda category_id, not_in_inventory=False: (
        BinAddress(1, 0, 0),
        False,
    )
    return positioning


def _mkClassifiedPiece(shared) -> KnownObject:
    piece = KnownObject(part_id="3001", color_id="1")
    piece.classification_status = ClassificationStatus.classified
    shared.transport.placePieceForDistribution(piece)
    return piece


def test_positioning_claims_a_bin_when_nothing_is_loose() -> None:
    shared = _mkShared()
    log: list[str] = []
    servos = [_Servo(log, i) for i in range(3)]
    piece = _mkClassifiedPiece(shared)

    assert _mkPositioning(shared, servos, log).step() is None  # waiting for the chute
    assert piece.destination_bin == (1, 0, 0)
    assert servos[1].close_calls == 1


def test_positioning_sends_everything_to_the_bucket_while_a_piece_is_loose() -> None:
    shared = _mkShared()
    shared.bucket_passthrough_hold = True
    log: list[str] = []
    servos = [_Servo(log, i) for i in range(3)]
    piece = _mkClassifiedPiece(shared)

    assert _mkPositioning(shared, servos, log).step() == DistributionState.READY
    assert piece.destination_bin is None
    assert piece.category_id == "cat_a"
    assert piece.stage == PieceStage.distributing
    assert [servo.close_calls for servo in servos] == [0, 0, 0]
    assert [servo.open_calls for servo in servos] == [1, 1, 1]
    assert "chute_move" not in log


def test_passthrough_reopens_a_door_the_shadow_state_calls_open() -> None:
    shared = _mkShared()
    shared.bucket_passthrough_hold = True
    log: list[str] = []
    servos = [_Servo(log, i, shadow_open=True) for i in range(3)]
    _mkClassifiedPiece(shared)

    _mkPositioning(shared, servos, log).step()

    assert [servo.open_calls for servo in servos] == [1, 1, 1]
