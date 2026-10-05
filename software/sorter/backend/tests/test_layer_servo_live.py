from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from server.routers import hardware, servos


def _irl(*channels):
    return SimpleNamespace(
        servos=[SimpleNamespace(channel=channel, angle=90) for channel in channels]
    )


def test_layer_added_since_home_has_no_live_servo(monkeypatch) -> None:
    monkeypatch.setattr(hardware.shared_state, "getActiveIRL", lambda: _irl(0, 1, 2, 3))
    layers = [{} for _ in range(5)]

    hardware._attach_live_servo_state(layers)

    assert [layer["servo_live_channel"] for layer in layers] == [0, 1, 2, 3, None]
    assert layers[4]["servo_current_angle"] is None


def test_no_live_hardware_reports_no_live_servos(monkeypatch) -> None:
    monkeypatch.setattr(hardware.shared_state, "getActiveIRL", lambda: None)
    layers = [{}, {}]

    hardware._attach_live_servo_state(layers)

    assert [layer["servo_live_channel"] for layer in layers] == [None, None]


def test_moving_a_layer_added_since_home_says_to_home(monkeypatch) -> None:
    monkeypatch.setattr(servos.shared_state, "getActiveIRL", lambda: _irl(0, 1, 2, 3))

    with pytest.raises(HTTPException) as exc:
        servos._live_servo_for_layer(4)

    assert exc.value.status_code == 409
    assert "home the machine" in str(exc.value.detail)
