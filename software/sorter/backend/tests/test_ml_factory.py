"""Tests for the ML-runtime factory and Hive-variant artifact resolution."""

from __future__ import annotations

import json
import sys
import types

import pytest

from vision.ml import create_processor, resolve_variant_artifact
from vision.ml.factory import imgsz_from_run_metadata


def _seed_variant(tmp_path, runtime: str):
    exports = tmp_path / "exports"
    exports.mkdir(parents=True)
    if runtime == "onnx":
        path = exports / "best.onnx"
        path.write_bytes(b"x")
    elif runtime == "ncnn":
        ncnn_dir = exports / "best_ncnn_model"
        ncnn_dir.mkdir()
        path = ncnn_dir / "model.ncnn.param"
        path.write_text("7767517\n1 1\nInput in0 0 1 in0\n")
        (ncnn_dir / "model.ncnn.bin").write_bytes(b"")
    elif runtime == "hailo":
        path = exports / "chamber.hef"
        path.write_bytes(b"x")
    else:
        raise AssertionError(runtime)
    return path


def test_resolve_onnx(tmp_path):
    seeded = _seed_variant(tmp_path, "onnx")
    assert resolve_variant_artifact(tmp_path, "onnx") == seeded


def test_resolve_ncnn_param(tmp_path):
    seeded = _seed_variant(tmp_path, "ncnn")
    assert resolve_variant_artifact(tmp_path, "ncnn") == seeded


def test_resolve_hailo_hef(tmp_path):
    seeded = _seed_variant(tmp_path, "hailo")
    assert resolve_variant_artifact(tmp_path, "hailo") == seeded


def test_resolve_missing(tmp_path):
    (tmp_path / "exports").mkdir()
    assert resolve_variant_artifact(tmp_path, "onnx") is None
    assert resolve_variant_artifact(tmp_path, "ncnn") is None
    assert resolve_variant_artifact(tmp_path, "hailo") is None


def test_factory_unsupported_runtime(tmp_path):
    with pytest.raises(ValueError, match="Unsupported"):
        create_processor(
            model_path=tmp_path / "model.bin",
            model_family="yolo",
            runtime="tflite",
            imgsz=320,
        )


def test_factory_unsupported_family(tmp_path):
    with pytest.raises(ValueError, match="Unsupported"):
        create_processor(
            model_path=tmp_path / "model.onnx",
            model_family="detr",
            runtime="onnx",
            imgsz=320,
        )


def test_factory_builds_onnx_without_loading(tmp_path):
    seeded = _seed_variant(tmp_path, "onnx")
    proc = create_processor(
        model_path=seeded,
        model_family="yolo",
        runtime="onnx",
        imgsz=320,
    )
    assert proc.runtime == "onnx"
    assert proc.family == "yolo"
    assert proc.imgsz == 320


def test_factory_builds_ncnn_without_loading(tmp_path):
    seeded = _seed_variant(tmp_path, "ncnn")
    proc = create_processor(
        model_path=seeded,
        model_family="nanodet",
        runtime="ncnn",
        imgsz=416,
    )
    assert proc.runtime == "ncnn"
    assert proc.family == "nanodet"
    assert proc.imgsz == 416


def test_factory_builds_hailo_without_loading(tmp_path):
    seeded = _seed_variant(tmp_path, "hailo")
    proc = create_processor(
        model_path=seeded,
        model_family="yolo",
        runtime="hailo",
        imgsz=320,
    )
    assert proc.runtime == "hailo"
    assert proc.family == "yolo"


def test_imgsz_from_metadata_explicit():
    assert imgsz_from_run_metadata({"imgsz": 416}) == 416


def test_imgsz_from_metadata_nested():
    assert imgsz_from_run_metadata({"dataset": {"imgsz": 320}}) == 320


def test_imgsz_from_metadata_run_name():
    assert imgsz_from_run_metadata({"run_name": "chamber-yolo11s-320"}) == 320


def test_imgsz_from_metadata_fallback():
    assert imgsz_from_run_metadata({}) == 320


# ---------------------------------------------------------------------------
# Preference-wiring tests for ncnn-vulkan vs ncnn-cpu.
# ---------------------------------------------------------------------------


def _write_prefs(tmp_path, payload) -> None:
    """Point the shared runtime_preferences reader at a tmp JSON file."""
    import runtime_preferences as prefs_mod

    prefs_path = tmp_path / "runtime_preferences.json"
    if payload is not None:
        prefs_path.write_text(json.dumps(payload))
    prefs_mod.PREFS_PATH = prefs_path  # monkeypatch module-level default


def _install_fake_ncnn(gpu_count: int = 1):
    """Install a stub ``ncnn`` module so _ensure_net can be exercised without the
    real library. Returns a ``Net`` factory we can inspect."""
    captured: dict = {"use_vulkan": None}

    class _Opt:
        def __init__(self):
            self.use_vulkan_compute = False
            self.num_threads = 1

    class _Net:
        def __init__(self):
            self.opt = _Opt()

        def load_param(self, *_args, **_kwargs):
            return 0

        def load_model(self, *_args, **_kwargs):
            return 0

        def create_extractor(self):  # pragma: no cover - not called
            raise AssertionError("should not create extractor in these tests")

    def _factory():
        net = _Net()
        # Capture the final value after _ensure_net finishes.
        captured["net"] = net
        return net

    fake = types.ModuleType("ncnn")
    fake.Net = _factory
    fake.get_gpu_count = lambda: gpu_count
    sys.modules["ncnn"] = fake
    return captured


def _seed_ncnn_model(tmp_path):
    """Write a minimally valid .param + .bin pair so _ensure_net can find them."""
    ncnn_dir = tmp_path / "exports" / "best_ncnn_model"
    ncnn_dir.mkdir(parents=True)
    param = ncnn_dir / "model.ncnn.param"
    param.write_text("7767517\n1 1\nInput in0 0 1 in0\n")
    (ncnn_dir / "model.ncnn.bin").write_bytes(b"")
    return param


def test_factory_passes_use_vulkan_when_preference_ncnn_vulkan(tmp_path):
    _write_prefs(tmp_path, {"ncnn": "ncnn-vulkan"})
    param = _seed_ncnn_model(tmp_path)
    captured = _install_fake_ncnn(gpu_count=1)

    proc = create_processor(
        model_path=param,
        model_family="yolo",
        runtime="ncnn",
        imgsz=320,
    )
    assert proc._use_vulkan is True  # type: ignore[attr-defined]
    # Force _ensure_net so use_vulkan_compute gets written onto net.opt.
    proc._ensure_net()  # type: ignore[attr-defined]
    assert captured["net"].opt.use_vulkan_compute is True


def test_factory_defaults_use_vulkan_false_when_preference_ncnn_cpu(tmp_path):
    _write_prefs(tmp_path, {"ncnn": "ncnn-cpu"})
    param = _seed_ncnn_model(tmp_path)
    captured = _install_fake_ncnn(gpu_count=1)

    proc = create_processor(
        model_path=param,
        model_family="yolo",
        runtime="ncnn",
        imgsz=320,
    )
    assert proc._use_vulkan is False  # type: ignore[attr-defined]
    proc._ensure_net()  # type: ignore[attr-defined]
    assert captured["net"].opt.use_vulkan_compute is False


def test_factory_falls_back_when_prefs_file_missing(tmp_path):
    _write_prefs(tmp_path, None)  # no file written
    param = _seed_ncnn_model(tmp_path)
    captured = _install_fake_ncnn(gpu_count=1)

    proc = create_processor(
        model_path=param,
        model_family="nanodet",
        runtime="ncnn",
        imgsz=320,
    )
    assert proc._use_vulkan is False  # type: ignore[attr-defined]
    proc._ensure_net()  # type: ignore[attr-defined]
    assert captured["net"].opt.use_vulkan_compute is False


def test_factory_falls_back_to_cpu_when_vulkan_requested_but_gpu_missing(tmp_path, caplog):
    _write_prefs(tmp_path, {"ncnn": "ncnn-vulkan"})
    param = _seed_ncnn_model(tmp_path)
    captured = _install_fake_ncnn(gpu_count=0)  # no GPU

    proc = create_processor(
        model_path=param,
        model_family="yolo",
        runtime="ncnn",
        imgsz=320,
    )
    # Preference is still recorded on the processor...
    assert proc._use_vulkan is True  # type: ignore[attr-defined]
    # ...but the actual net must run on CPU, with a warning logged.
    with caplog.at_level("WARNING"):
        proc._ensure_net()  # type: ignore[attr-defined]
    assert captured["net"].opt.use_vulkan_compute is False
    assert any("Vulkan requested" in rec.message for rec in caplog.records)
