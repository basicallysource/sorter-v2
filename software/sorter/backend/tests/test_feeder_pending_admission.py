"""Cover the post-C3-pulse admission grace window.

Without this guard the race between the C3 stepper cooldown ending and
the new piece being registered into C4's zone manager can leave the next
feeder tick reading "C4 empty" and firing a second pulse, double-dropping
both pieces into the same C4 sector. The grace window keeps admission
blocked for CLASSIFICATION_CHANNEL_PENDING_ADMISSION_MS after every
successful ch3 pulse — long enough for the structural check to catch
the new piece on its own.
"""

from __future__ import annotations

import time
import unittest
from types import SimpleNamespace

from subsystems.feeder.feeding import (
    CLASSIFICATION_CHANNEL_PENDING_ADMISSION_MS,
    CLASSIFICATION_INTAKE_REQUEST_LEASE_S,
    Feeding,
)
from subsystems.bus import PieceRequest, StationId, TickBus
from subsystems.shared_variables import SharedVariables


class _Stepper:
    def __init__(self, name: str) -> None:
        self._name = name
        self.moves: list[float] = []
        self._busy = False

    def degrees_for_microsteps(self, steps: int) -> float:
        # 1 microstep == 0.045° for the test — purely cosmetic.
        return float(steps) * 0.045

    def estimateMoveDegreesMs(self, degrees: float, *, max_speed: int) -> float:
        return 50.0  # fixed short exec time

    def move_degrees(self, degrees: float) -> bool:
        self.moves.append(float(degrees))
        return True

    def set_acceleration(self, *_args, **_kwargs) -> None:
        pass

    def set_speed_limits(self, *_args, **_kwargs) -> None:
        pass


class _Vision:
    def __init__(self) -> None:
        self.captures: list[dict] = []

    def scheduleFeederTeacherCaptureAfterMove(self, role: str, **kwargs) -> None:
        self.captures.append({"role": role, **kwargs})


class _Profiler:
    def __init__(self) -> None:
        self.values: list[tuple[str, float]] = []
        self.hits: list[str] = []

    def hit(self, key: str) -> None:
        self.hits.append(key)

    def timer(self, _key: str):
        from contextlib import contextmanager

        @contextmanager
        def _noop():
            yield

        return _noop()

    def observeValue(self, key: str, value: float) -> None:
        self.values.append((key, value))


class _RuntimeStats:
    def __init__(self) -> None:
        self.pulses: list[tuple[str, str]] = []

    def observePulse(self, label: str, status: str, *_args) -> None:
        self.pulses.append((label, status))


def _make_feeding_stub() -> Feeding:
    """Bypass __init__ — the timer logic only touches the few fields we
    set manually below."""
    feeding = Feeding.__new__(Feeding)
    feeding.gc = SimpleNamespace(profiler=_Profiler(), runtime_stats=_RuntimeStats())
    feeding.vision = _Vision()
    feeding.shared = SimpleNamespace(sample_collection_mode=False)
    feeding._busy_until = {}
    feeding._motion_until = {}
    feeding._classification_channel_pending_admission_until = 0.0
    feeding._sample_speed_limit_cache = {}
    return feeding


def test_send_pulse_sets_pending_admission_timer_for_ch3() -> None:
    feeding = _make_feeding_stub()
    stepper = _Stepper("c_channel_3_rotor")
    cfg = SimpleNamespace(
        steps_per_pulse=300, microsteps_per_second=1600, delay_between_pulse_ms=1000
    )

    before = time.monotonic()
    sent = feeding._sendPulse("ch3_precise", stepper, cfg)
    after = time.monotonic()

    assert sent is True
    pin = feeding._classification_channel_pending_admission_until
    expected_lower = before + (CLASSIFICATION_CHANNEL_PENDING_ADMISSION_MS / 1000.0)
    expected_upper = after + (CLASSIFICATION_CHANNEL_PENDING_ADMISSION_MS / 1000.0)
    assert expected_lower <= pin <= expected_upper


def test_send_pulse_does_not_set_pending_admission_for_ch1_or_ch2() -> None:
    feeding = _make_feeding_stub()
    cfg = SimpleNamespace(
        steps_per_pulse=300, microsteps_per_second=1600, delay_between_pulse_ms=250
    )

    feeding._sendPulse("ch1_normal", _Stepper("c_channel_1_rotor"), cfg)
    feeding._sendPulse("ch2_normal", _Stepper("c_channel_2_rotor"), cfg)

    assert feeding._classification_channel_pending_admission_until == 0.0


def test_pending_admission_helper_true_while_window_open() -> None:
    feeding = _make_feeding_stub()
    feeding._classification_channel_pending_admission_until = time.monotonic() + 0.5

    assert feeding._classificationChannelHasPendingAdmission() is True


def test_pending_admission_helper_false_after_window_expires() -> None:
    feeding = _make_feeding_stub()
    feeding._classification_channel_pending_admission_until = time.monotonic() - 0.5

    assert feeding._classificationChannelHasPendingAdmission() is False


def test_pending_admission_helper_false_when_never_set() -> None:
    feeding = _make_feeding_stub()
    assert feeding._classificationChannelHasPendingAdmission() is False


def test_failed_ch3_pulse_does_not_arm_pending_admission() -> None:
    """A move_degrees() failure must not arm the in-flight timer — the
    piece never left C3, so blocking the next admission attempt for 1.5 s
    would just stall C3 needlessly on retry."""
    feeding = _make_feeding_stub()
    stepper = _Stepper("c_channel_3_rotor")
    stepper.move_degrees = lambda _deg: False  # always reject
    cfg = SimpleNamespace(
        steps_per_pulse=300, microsteps_per_second=1600, delay_between_pulse_ms=1000
    )

    sent = feeding._sendPulse("ch3_precise", stepper, cfg)
    assert sent is False
    assert feeding._classification_channel_pending_admission_until == 0.0


def test_classification_intake_request_allows_ch3_after_gate_closes() -> None:
    feeding = _make_feeding_stub()
    bus = TickBus()
    feeding.shared = SharedVariables(
        gc=SimpleNamespace(use_channel_bus=True),
        bus=bus,
    )
    feeding.shared.set_classification_gate(False, reason="awaiting_piece")
    bus.publish(
        PieceRequest(
            source=StationId.CLASSIFICATION,
            target=StationId.C3,
            sent_at_mono=20.0,
        )
    )

    assert feeding._classificationIntakeRequestPending(20.5) is True
    assert (
        feeding._classificationIntakeRequestPending(
            20.0 + CLASSIFICATION_INTAKE_REQUEST_LEASE_S + 0.1
        )
        is False
    )


def test_successful_ch3_precise_pulse_consumes_classification_request() -> None:
    feeding = _make_feeding_stub()
    bus = TickBus()
    feeding.shared = SharedVariables(
        gc=SimpleNamespace(use_channel_bus=True),
        bus=bus,
    )
    now = time.monotonic()
    feeding.shared.publish_piece_request(
        source=StationId.CLASSIFICATION,
        target=StationId.C3,
        sent_at_mono=now,
    )
    cfg = SimpleNamespace(
        steps_per_pulse=300, microsteps_per_second=1600, delay_between_pulse_ms=1000
    )

    assert feeding._classificationIntakeRequestPending(now + 0.1) is True
    sent = feeding._sendPulse("ch3_precise", _Stepper("c_channel_3_rotor"), cfg)

    assert sent is True
    assert bus.piece_delivered(StationId.C3, StationId.CLASSIFICATION) is not None
    assert feeding._classificationIntakeRequestPending(time.monotonic()) is False


if __name__ == "__main__":
    unittest.main()
