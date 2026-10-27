"""A cleared layer calibration stays cleared, and a board with no DIAG pin for a
channel runs that stepper without StallGuard instead of failing the init."""

from types import SimpleNamespace

import pytest

import bin_layout_store
from hardware.bus import MCUBusError
from irl.bin_layout import calibratedAnglesForLayer
from irl.config import _armUnlessNoDiagPin


def _layout():
    layer = SimpleNamespace(servo_channel_id=None, servo_open_angle=12, servo_closed_angle=88)
    return SimpleNamespace(layers=[layer])


def test_a_cleared_channel_does_not_fall_back_to_the_legacy_layer_angles(monkeypatch):
    monkeypatch.setattr(bin_layout_store, "get_servo_channel_calibration", lambda: {"0": {"open": None, "closed": None}})
    assert calibratedAnglesForLayer(_layout(), 0) == (None, None)


def test_a_channel_with_no_entry_still_reads_the_legacy_layer_angles(monkeypatch):
    monkeypatch.setattr(bin_layout_store, "get_servo_channel_calibration", lambda: {})
    assert calibratedAnglesForLayer(_layout(), 0) == (12, 88)


class _Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, message, *a, **k):
        self.warnings.append(message)


def test_no_diag_pin_turns_stallguard_off_for_that_stepper():
    gc = SimpleNamespace(logger=_Logger())
    stepper = SimpleNamespace(stallguard_enabled=True)

    def arm():
        raise MCUBusError("Error response received, command: 0x9a, payload: b'No DIAG pin for channel 3'")

    assert _armUnlessNoDiagPin(gc, stepper, "chute", arm)() is None
    assert stepper.stallguard_enabled is False
    assert len(gc.logger.warnings) == 1


def test_other_arming_errors_still_raise():
    gc = SimpleNamespace(logger=_Logger())
    stepper = SimpleNamespace(stallguard_enabled=True)

    def arm():
        raise MCUBusError("Timeout waiting for response terminator (0x00)")

    with pytest.raises(MCUBusError):
        _armUnlessNoDiagPin(gc, stepper, "chute", arm)()
    assert stepper.stallguard_enabled is True
