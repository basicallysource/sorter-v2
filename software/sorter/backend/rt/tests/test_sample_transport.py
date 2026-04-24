from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import MagicMock

from rt.services.sample_transport import C1234SampleTransportCoordinator


@dataclass
class _FakePort:
    key: str
    degrees_per_step: float = 36.0
    steps: int = 0
    configured_rpm: float | None = None
    direct_max_speed: int | None = None
    direct_acceleration: int | None = None

    def step(self, now_mono: float) -> bool:
        self.steps += 1
        return True

    def configure_sample_transport(
        self,
        *,
        target_rpm: float | None,
        direct_max_speed_usteps_per_s: int | None = None,
        direct_acceleration_usteps_per_s2: int | None = None,
    ) -> None:
        self.configured_rpm = target_rpm
        self.direct_max_speed = direct_max_speed_usteps_per_s
        self.direct_acceleration = direct_acceleration_usteps_per_s2
        if self.key == "c4" and target_rpm is not None:
            self.degrees_per_step = max(6.0, min(45.0, target_rpm * 6.0 * 0.25))

    def nominal_degrees_per_step(self) -> float | None:
        return self.degrees_per_step


class _FakeRuntime:
    def __init__(self, key: str) -> None:
        self.port = _FakePort(key)

    def sample_transport_port(self) -> _FakePort:
        return self.port


def test_sample_transport_steps_channels_by_ratio_and_restores_running() -> None:
    coordinator = C1234SampleTransportCoordinator()
    control = MagicMock()
    control.paused = False
    runtimes = [_FakeRuntime("c1"), _FakeRuntime("c2"), _FakeRuntime("c3")]
    published: list[str] = []

    started = coordinator.start(
        runtimes=runtimes,
        control=control,
        state_publisher=published.append,
        base_interval_s=0.12,
        ratio=2.0,
        duration_s=0.28,
        poll_s=0.01,
    )

    assert started is True
    deadline = time.time() + 2.0
    while coordinator.status()["active"] and time.time() < deadline:
        time.sleep(0.01)

    status = coordinator.status()
    assert status["active"] is False
    assert status["success"] is True
    assert status["reason"] == "duration_elapsed"
    assert published == ["sample_transport", "running"]
    control.pause.assert_called_once_with()
    control.resume.assert_called_once_with()
    assert runtimes[0].port.steps < runtimes[1].port.steps <= runtimes[2].port.steps


def test_sample_transport_cancel_restores_paused_state() -> None:
    coordinator = C1234SampleTransportCoordinator()
    control = MagicMock()
    control.paused = True
    runtime = _FakeRuntime("c1")
    published: list[str] = []

    assert coordinator.start(
        runtimes=[runtime],
        control=control,
        state_publisher=published.append,
        base_interval_s=0.1,
        duration_s=10.0,
        poll_s=0.01,
    )
    deadline = time.time() + 1.0
    while runtime.port.steps == 0 and time.time() < deadline:
        time.sleep(0.01)

    assert coordinator.cancel() is True
    deadline = time.time() + 2.0
    while coordinator.status()["active"] and time.time() < deadline:
        time.sleep(0.01)

    status = coordinator.status()
    assert status["active"] is False
    assert status["success"] is False
    assert status["reason"] == "cancelled"
    assert published == ["sample_transport", "paused"]
    control.pause.assert_called_once_with()
    control.resume.assert_not_called()


def test_sample_transport_rejects_second_start() -> None:
    coordinator = C1234SampleTransportCoordinator()
    control = MagicMock()
    control.paused = False
    runtime = _FakeRuntime("c1")

    assert coordinator.start(
        runtimes=[runtime],
        control=control,
        base_interval_s=0.1,
        duration_s=10.0,
        poll_s=0.01,
    )
    try:
        assert (
            coordinator.start(
                runtimes=[runtime],
                control=control,
                base_interval_s=0.1,
                duration_s=10.0,
                poll_s=0.01,
            )
            is False
        )
    finally:
        coordinator.cancel()


def test_sample_transport_uses_per_channel_rpm_targets() -> None:
    coordinator = C1234SampleTransportCoordinator()
    control = MagicMock()
    control.paused = False
    runtimes = [_FakeRuntime("c1"), _FakeRuntime("c2")]

    assert coordinator.start(
        runtimes=runtimes,
        control=control,
        channel_rpm={"c1": 1.0, "c2": 2.0},
        duration_s=0.12,
        poll_s=0.01,
    )

    deadline = time.time() + 2.0
    while coordinator.status()["active"] and time.time() < deadline:
        time.sleep(0.01)

    status = coordinator.status()
    assert status["config"]["channel_rpm"] == {"c1": 1.0, "c2": 2.0}
    assert status["channels"]["c1"]["interval_s"] == 6.0
    assert status["channels"]["c2"]["interval_s"] == 3.0
    assert status["channels"]["c1"]["target_rpm"] == 1.0
    assert status["channels"]["c2"]["target_rpm"] == 2.0
    assert status["channels"]["c1"]["direct_max_speed_usteps_per_s"] == 2400
    assert status["channels"]["c1"]["direct_acceleration_usteps_per_s2"] == 100000


def test_sample_transport_allows_rpm_targets_up_to_64() -> None:
    coordinator = C1234SampleTransportCoordinator()
    control = MagicMock()
    control.paused = False
    runtime = _FakeRuntime("c2")

    assert coordinator.start(
        runtimes=[runtime],
        control=control,
        channel_rpm={"c2": 80.0},
        duration_s=0.12,
        poll_s=0.01,
    )

    deadline = time.time() + 2.0
    while coordinator.status()["active"] and time.time() < deadline:
        time.sleep(0.01)

    status = coordinator.status()
    assert runtime.port.configured_rpm == 64.0
    assert status["channels"]["c2"]["target_rpm"] == 64.0


def test_sample_transport_recomputes_nominal_degrees_after_port_configure() -> None:
    coordinator = C1234SampleTransportCoordinator()
    control = MagicMock()
    control.paused = False
    runtime = _FakeRuntime("c4")

    assert coordinator.start(
        runtimes=[runtime],
        control=control,
        channel_rpm={"c4": 30.0},
        duration_s=0.12,
        poll_s=0.01,
    )

    deadline = time.time() + 2.0
    while coordinator.status()["active"] and time.time() < deadline:
        time.sleep(0.01)

    status = coordinator.status()
    assert runtime.port.configured_rpm == 30.0
    assert status["channels"]["c4"]["nominal_degrees_per_step"] == 45.0
    assert status["channels"]["c4"]["interval_s"] == 0.25


def test_sample_transport_updates_running_rpm_targets() -> None:
    coordinator = C1234SampleTransportCoordinator()
    control = MagicMock()
    control.paused = False
    runtimes = [_FakeRuntime("c1"), _FakeRuntime("c2")]

    assert coordinator.start(
        runtimes=runtimes,
        control=control,
        channel_rpm={"c1": 1.0, "c2": 1.0},
        duration_s=10.0,
        poll_s=0.01,
    )
    try:
        assert coordinator.update_config(channel_rpm={"c1": 1.0, "c2": 4.0})
        deadline = time.time() + 2.0
        while time.time() < deadline:
            status = coordinator.status()
            if status["channels"]["c2"]["target_rpm"] == 4.0:
                break
            time.sleep(0.01)

        status = coordinator.status()
        assert status["active"] is True
        assert status["config"]["channel_rpm"] == {"c1": 1.0, "c2": 4.0}
        assert status["channels"]["c1"]["interval_s"] == 6.0
        assert status["channels"]["c2"]["interval_s"] == 1.5
        assert status["channels"]["c2"]["target_rpm"] == 4.0
        assert status["channels"]["c2"]["direct_max_speed_usteps_per_s"] == 2400
    finally:
        coordinator.cancel()
