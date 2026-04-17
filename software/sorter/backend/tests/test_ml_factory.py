"""Tests for the ML-runtime factory and Hive-variant artifact resolution."""

from __future__ import annotations

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
