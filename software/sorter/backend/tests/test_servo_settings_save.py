"""Saving the servo hardware form must not drop [servo] keys it does not own.

Regression: the form rebuilt the whole table from its own fields, so
move_time_ms and max_torque_percent vanished on every save — and the next
restart put the SC15 back to full torque against a printed flap.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from server.routers import hardware


@pytest.fixture
def machine_params(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "machine.toml"
    path.write_text(
        "\n".join(
            [
                "[servo]",
                'backend = "waveshare"',
                'port = "/dev/serial/by-id/old"',
                "move_time_ms = 600",
                "max_torque_percent = 60",
                "highest_seen_id = 16",
                "",
                "[[servo.channels]]",
                "id = 16",
                "invert = false",
                "",
                "[[servo.channels]]",
                "id = 15",
                "invert = true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MACHINE_SPECIFIC_PARAMS_PATH", str(path))
    return path


def test_save_keeps_move_time_and_torque_cap(machine_params: Path) -> None:
    payload = hardware.ServoHardwareSettingsPayload(
        backend="waveshare",
        port="/dev/serial/by-id/new",
        channels=[
            hardware.ServoChannelConfigPayload(id=16, invert=True),
            hardware.ServoChannelConfigPayload(id=15, invert=True),
        ],
    )
    layers = {"layers": [{"enabled": True}, {"enabled": True}]}
    with (
        patch("server.routers.hardware.getBinLayout", return_value=SimpleNamespace(layers=[None, None])),
        patch("server.routers.hardware._storage_layer_settings_from_layout", return_value=layers),
        patch("server.routers.hardware._pca_available_servo_channels", return_value=[]),
        patch("server.routers.hardware._active_irl", return_value=None),
        patch("server.routers.hardware.shared_state.controller_ref", None),
    ):
        response = hardware.save_servo_hardware_config(payload)

    assert response["ok"]
    saved = machine_params.read_text(encoding="utf-8")
    assert "move_time_ms = 600" in saved
    assert "max_torque_percent = 60" in saved
    assert "highest_seen_id = 16" in saved
    assert 'port = "/dev/serial/by-id/new"' in saved
    assert saved.count("invert = true") == 2
