"""Tests for the C4 transport pulse-settle-pulse motion profile."""

from __future__ import annotations

import logging
import os
import time as time_module
from typing import Any
from unittest.mock import patch

from rt.hardware.channel_callables import (
    C4_TRANSPORT_PROFILE_ENV,
    C4_TRANSPORT_SETTLE_MS_ENV,
    C4_TRANSPORT_SUB_PULSE_DEG_ENV,
    build_c4_callables,
)


class _FakeStepper:
    """Bare-minimum stepper double used by the motion-profile code path."""

    def __init__(self) -> None:
        self.moves: list[float] = []

    # move_degrees_with_profile drives the stepper via these two helpers.
    def set_speed_limits(self, _min_speed: int, _max_speed: int) -> None:
        return None

    def set_acceleration(self, _accel: int) -> None:
        return None

    def move_degrees(self, degrees: float) -> bool:
        self.moves.append(float(degrees))
        return True

    # Alias kept for code paths that still call the blocking variant.
    move_degrees_blocking = move_degrees

    def degrees_for_microsteps(self, microsteps: int) -> float:
        return float(microsteps)

    def microsteps_for_degrees(self, degrees: float) -> int:
        return int(degrees * 10)


class _FakeFeederConfig:
    pass


class _FakeIrl:
    def __init__(self) -> None:
        self.carousel_stepper = _FakeStepper()
        self.feeder_config = _FakeFeederConfig()
        self.irl_config = self


def _build() -> tuple[Any, _FakeStepper]:
    """Return the transport_move closure + the fake stepper it drives."""

    irl = _FakeIrl()
    _carousel, transport, *_rest = build_c4_callables(irl, logging.getLogger("test"))
    return transport, irl.carousel_stepper


def test_default_transport_profile_is_single_shot(monkeypatch) -> None:
    monkeypatch.delenv(C4_TRANSPORT_PROFILE_ENV, raising=False)
    transport, stepper = _build()

    assert transport(6.0) is True
    assert stepper.moves == [6.0]


def test_pulsed_profile_splits_move_and_settles(monkeypatch) -> None:
    monkeypatch.setenv(C4_TRANSPORT_PROFILE_ENV, "pulsed")
    monkeypatch.setenv(C4_TRANSPORT_SUB_PULSE_DEG_ENV, "2.0")
    monkeypatch.setenv(C4_TRANSPORT_SETTLE_MS_ENV, "50")
    transport, stepper = _build()

    sleeps: list[float] = []

    with patch("rt.hardware.channel_callables.time.sleep", side_effect=sleeps.append):
        assert transport(6.0) is True

    # 6° split into 3 × 2° sub-pulses.
    assert stepper.moves == [2.0, 2.0, 2.0]
    # Two settles — between each pair of sub-pulses, not before the first.
    assert sleeps == [0.05, 0.05]


def test_pulsed_profile_preserves_direction(monkeypatch) -> None:
    monkeypatch.setenv(C4_TRANSPORT_PROFILE_ENV, "pulsed")
    monkeypatch.setenv(C4_TRANSPORT_SUB_PULSE_DEG_ENV, "1.5")
    monkeypatch.setenv(C4_TRANSPORT_SETTLE_MS_ENV, "0")
    transport, stepper = _build()

    assert transport(-4.5) is True
    assert stepper.moves == [-1.5, -1.5, -1.5]


def test_pulsed_profile_skips_split_for_small_moves(monkeypatch) -> None:
    """A 1° nudge shouldn't get sprinkled with sleeps when sub-pulse is 2°."""

    monkeypatch.setenv(C4_TRANSPORT_PROFILE_ENV, "pulsed")
    monkeypatch.setenv(C4_TRANSPORT_SUB_PULSE_DEG_ENV, "2.0")
    monkeypatch.setenv(C4_TRANSPORT_SETTLE_MS_ENV, "50")
    transport, stepper = _build()

    sleeps: list[float] = []

    with patch("rt.hardware.channel_callables.time.sleep", side_effect=sleeps.append):
        assert transport(1.0) is True

    assert stepper.moves == [1.0]
    assert sleeps == []


def test_pulsed_profile_tails_remaining_fraction(monkeypatch) -> None:
    """7° with sub_pulse=2° → 2+2+2+1 (final partial)."""

    monkeypatch.setenv(C4_TRANSPORT_PROFILE_ENV, "pulsed")
    monkeypatch.setenv(C4_TRANSPORT_SUB_PULSE_DEG_ENV, "2.0")
    monkeypatch.setenv(C4_TRANSPORT_SETTLE_MS_ENV, "0")
    transport, stepper = _build()

    assert transport(7.0) is True
    assert stepper.moves == [2.0, 2.0, 2.0, 1.0]


def test_pulsed_profile_aborts_if_sub_pulse_fails(monkeypatch) -> None:
    monkeypatch.setenv(C4_TRANSPORT_PROFILE_ENV, "pulsed")
    monkeypatch.setenv(C4_TRANSPORT_SUB_PULSE_DEG_ENV, "2.0")
    monkeypatch.setenv(C4_TRANSPORT_SETTLE_MS_ENV, "0")

    irl = _FakeIrl()
    call_count = 0
    real_move = irl.carousel_stepper.move_degrees

    def _flaky_move(degrees: float) -> bool:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            return False
        return real_move(degrees)

    irl.carousel_stepper.move_degrees = _flaky_move  # type: ignore[assignment]

    _carousel, transport, *_rest = build_c4_callables(irl, logging.getLogger("test"))
    assert transport(6.0) is False
    # First sub-pulse ran, second aborted — third must not have been attempted.
    assert call_count == 2
