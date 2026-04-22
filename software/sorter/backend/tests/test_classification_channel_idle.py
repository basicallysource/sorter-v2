from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from subsystems.classification_channel.idle import (
    Idle,
    PURGE_MIN_PULSES,
    PURGE_POST_CLEAR_PULSES,
)
from subsystems.classification_channel.states import ClassificationChannelState


class _Logger:
    def info(self, *args, **kwargs) -> None:
        pass

    def warning(self, *args, **kwargs) -> None:
        pass

    def error(self, *args, **kwargs) -> None:
        pass


class _Servo:
    def open(self) -> None:
        pass


class _Stepper:
    def __init__(self) -> None:
        self.stopped = True
        self.move_calls = 0
        self.acceleration = None

    def set_speed_limits(self, *args, **kwargs) -> None:
        return None

    def set_acceleration(self, acceleration: int) -> None:
        self.acceleration = int(acceleration)

    def degrees_for_microsteps(self, microsteps: int) -> float:
        return float(microsteps) / 100.0

    def move_degrees(self, degrees: float) -> bool:
        self.move_calls += 1
        self.stopped = True
        return True


class _Vision:
    def __init__(
        self,
        visible_sequence: list[bool],
        *,
        track_presence_sequence: list[bool] | None = None,
    ) -> None:
        self._visible_sequence = list(visible_sequence)
        self._track_presence_sequence = (
            list(track_presence_sequence)
            if track_presence_sequence is not None
            else []
        )

    def getFeederTrackAngularExtents(
        self,
        role: str,
        *,
        force_detection: bool = False,
    ):
        present = (
            self._track_presence_sequence.pop(0)
            if self._track_presence_sequence
            else False
        )
        return [object()] if present else []

    def getClassificationChannelDetectionCandidates(self, force: bool = False):
        visible = self._visible_sequence.pop(0) if self._visible_sequence else False
        return [object()] if visible else []

    def clearCarouselBaseline(self) -> None:
        pass


class _Transport:
    dynamic_mode = True

    def activePieces(self):
        return []

    def getPieceAtClassification(self):
        return None


def _make_idle(
    *,
    visible_sequence: list[bool],
    track_presence_sequence: list[bool] | None = None,
) -> tuple[Idle, _Stepper]:
    stepper = _Stepper()
    irl = SimpleNamespace(
        carousel_stepper=stepper,
        servos=[_Servo(), _Servo()],
    )
    irl_config = SimpleNamespace(
        feeder_config=SimpleNamespace(
            classification_channel_eject=SimpleNamespace(
                steps_per_pulse=1000,
                microsteps_per_second=5000,
                acceleration_microsteps_per_second_sq=1100,
            )
        ),
        carousel_stepper=SimpleNamespace(default_steps_per_second=1000),
    )
    gc = SimpleNamespace(logger=_Logger(), disable_servos=True)
    idle = Idle(
        irl=irl,
        irl_config=irl_config,
        gc=gc,
        shared=SimpleNamespace(),
        transport=_Transport(),
        vision=_Vision(
            visible_sequence,
            track_presence_sequence=track_presence_sequence,
        ),
    )
    return idle, stepper


def test_idle_purge_fires_tail_pulses_after_first_clear() -> None:
    idle, stepper = _make_idle(visible_sequence=[False, False, False])

    with patch(
        "subsystems.classification_channel.idle.POST_PULSE_SETTLE_MS",
        0,
    ):
        next_state = None
        for _ in range(32):
            next_state = idle.step()
            if next_state is not None:
                break

    assert next_state == ClassificationChannelState.RUNNING
    assert stepper.move_calls == PURGE_MIN_PULSES + PURGE_POST_CLEAR_PULSES


def test_idle_purge_prefers_live_tracker_over_empty_detection() -> None:
    idle, stepper = _make_idle(
        visible_sequence=[False, False, False, False, False, False],
        track_presence_sequence=[True, True, False, False, False, False],
    )

    with patch(
        "subsystems.classification_channel.idle.POST_PULSE_SETTLE_MS",
        0,
    ):
        next_state = None
        for _ in range(40):
            next_state = idle.step()
            if next_state is not None:
                break

    assert next_state == ClassificationChannelState.RUNNING
    assert stepper.move_calls >= PURGE_MIN_PULSES + 2
