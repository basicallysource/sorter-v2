from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "probe_rk3588_npu_stack.py"
SPEC = importlib.util.spec_from_file_location("probe_rk3588_npu_stack", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


class FakeRKNNLite:
    NPU_CORE_0_1_2 = 7

    def __init__(self) -> None:
        self.released = False

    def load_rknn(self, _path: str) -> int:
        return 0

    def init_runtime(self, *, core_mask: int | None = None) -> int:
        return 0

    def inference(self, *, inputs: list[object]) -> list[object]:
        import numpy as np

        assert inputs
        return [np.zeros((1, 1, 6), dtype=np.float32)]

    def release(self) -> None:
        self.released = True


def _args(*extra: str):
    return probe.parse_args(list(extra))


def test_npu_probe_passes_when_device_runtime_model_and_inference_are_available() -> None:
    args = _args("--require-inference", "--model", "/models/npu-smoke.rknn")

    report = probe.build_report(
        args,
        path_exists=lambda path: path in {
            "/dev/dri/by-path/platform-fdab0000.npu-render",
            "/models/npu-smoke.rknn",
        },
        runtime_loader=lambda: (FakeRKNNLite, None),
    )

    assert report["ok"] is True
    assert report["checks"]["rknpu_device_node"] is True
    assert report["checks"]["rknnlite_importable"] is True
    assert report["checks"]["model_present"] is True
    assert report["checks"]["inference_ok"] is True
    assert report["details"]["inference"]["output_shapes"] == [[1, 1, 6]]


def test_default_npu_smoke_model_is_packaged() -> None:
    assert probe.DEFAULT_MODEL_PATH.name == "c_channel_full_yolo26s_320_rk3588.rknn"
    assert probe.DEFAULT_MODEL_PATH.exists()


def test_npu_probe_rejects_missing_rknpu_device_node_in_strict_mode() -> None:
    args = _args("--require-device", "--require-runtime")

    report = probe.build_report(
        args,
        path_exists=lambda _path: False,
        runtime_loader=lambda: (FakeRKNNLite, None),
    )

    assert report["ok"] is False
    assert any("/dev/dri/by-path/platform-fdab0000.npu-render" in blocker for blocker in report["blockers"])
    assert any("No RKNN runtime marker" in blocker for blocker in report["blockers"])


def test_npu_probe_rejects_missing_rknnlite_runtime() -> None:
    args = _args("--require-runtime")

    report = probe.build_report(
        args,
        path_exists=lambda path: path == "/dev/dri/by-path/platform-fdab0000.npu-render",
        runtime_loader=lambda: (None, "No module named rknnlite"),
    )

    assert report["ok"] is False
    assert report["checks"]["rknnlite_importable"] is False
    assert any("rknnlite.api is not importable" in blocker for blocker in report["blockers"])


def test_load_rknnlite_uses_real_module_name(monkeypatch) -> None:
    parent = types.ModuleType("rknnlite")
    api = types.ModuleType("rknnlite.api")
    api.RKNNLite = FakeRKNNLite
    monkeypatch.setitem(sys.modules, "rknnlite", parent)
    monkeypatch.setitem(sys.modules, "rknnlite.api", api)

    runtime_cls, error = probe._load_rknnlite()

    assert runtime_cls is FakeRKNNLite
    assert error is None
