"""/api/bins/move-to uses the production door semantics: target closed, rest open."""
from types import SimpleNamespace
from unittest.mock import patch

from server.routers import hardware


class _Servo:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def open(self) -> None:
        self.calls.append("open")

    def close(self) -> None:
        self.calls.append("close")


def test_move_to_closes_target_layer_and_opens_the_others() -> None:
    upper, lower = _Servo(), _Servo()
    chute = SimpleNamespace(getAngleForBin=lambda a: 42.0, moveToBin=lambda a: 500)
    irl = SimpleNamespace(chute=chute, servos=[upper, lower])
    controller = SimpleNamespace(irl=irl)
    payload = hardware.MoveToBinPayload(layer_index=1, section_index=2, bin_index=0)
    with patch("server.routers.hardware.shared_state.controller_ref", controller):
        out = hardware.move_to_bin(payload)
    assert out["ok"] and out["target_angle"] == 42.0
    assert lower.calls == ["close"]
    assert upper.calls == ["open"]
