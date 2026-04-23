"""Tests for the Hive-ONNX / NCNN detector port (rt/perception/detectors/hive_onnx.py)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from rt.contracts.detection import DetectionBatch
from rt.contracts.feed import FeedFrame, PolarZone, PolygonZone, RectZone
from rt.contracts.registry import StrategyRegistry
from rt.perception.detectors import hive_onnx
from rt.perception.detectors.hive_onnx import (
    HiveDetector,
    default_hive_detector_slug,
    discover_and_register_hive_detectors,
)


# --- Fixtures / helpers ------------------------------------------------------


@dataclass(frozen=True)
class _MLDetection:
    """Mimics ``backend.vision.ml.Detection`` (bbox-xyxy + score)."""

    bbox: tuple[int, int, int, int]
    score: float


class FakeHiveProcessor:
    """Stand-in for a BaseProcessor — records calls and returns fixed output."""

    def __init__(self, detections: list[_MLDetection] | None = None) -> None:
        self._detections = detections or []
        self.calls: list[tuple[int, int]] = []  # (h, w) of each crop
        self.last_image: np.ndarray | None = None
        self.reset_calls = 0
        self.closed = False

    def infer(self, image_bgr: np.ndarray) -> list[_MLDetection]:
        self.calls.append((int(image_bgr.shape[0]), int(image_bgr.shape[1])))
        self.last_image = image_bgr.copy()
        return list(self._detections)

    def reset(self) -> None:
        self.reset_calls += 1

    def close(self) -> None:
        self.closed = True


def _frame(raw: np.ndarray, seq: int = 1) -> FeedFrame:
    return FeedFrame(
        feed_id="c2_feed",
        camera_id="cam_c2",
        raw=raw,
        gray=None,
        timestamp=float(seq) * 0.1,
        monotonic_ts=float(seq) * 0.1,
        frame_seq=seq,
    )


# --- HiveDetector unit tests ------------------------------------------------


def test_default_slug_points_at_c_channel_model() -> None:
    assert default_hive_detector_slug() == "hive:c-channel-yolo11n-320"


def test_hive_detector_key_and_requires() -> None:
    proc = FakeHiveProcessor()
    det = HiveDetector(
        model_id="model-uuid",
        slug="c-channel-yolo11n-320",
        processor=proc,
        imgsz=320,
        model_family="yolo",
    )
    assert det.key == "hive:c-channel-yolo11n-320"
    assert det.requires() == frozenset({"raw"})


def test_hive_detector_with_fake_processor_returns_detection_batch() -> None:
    proc = FakeHiveProcessor(
        detections=[_MLDetection(bbox=(10, 20, 60, 80), score=0.85)],
    )
    det = HiveDetector(
        model_id="m", slug="s", processor=proc, imgsz=320, model_family="yolo",
    )
    frame = _frame(np.zeros((200, 300, 3), dtype=np.uint8), seq=7)

    batch = det.detect(frame, RectZone(x=0, y=0, w=300, h=200))

    assert isinstance(batch, DetectionBatch)
    assert batch.feed_id == "c2_feed"
    assert batch.frame_seq == 7
    assert batch.algorithm == "hive:s"
    assert batch.latency_ms >= 0.0
    assert len(batch.detections) == 1
    d0 = batch.detections[0]
    assert d0.bbox_xyxy == (10, 20, 60, 80)
    assert d0.score == pytest.approx(0.85)
    assert d0.meta["slug"] == "s"
    assert d0.meta["model_family"] == "yolo"


def test_hive_detector_score_and_bbox_in_original_coords() -> None:
    """When cropping by RectZone(100, 100, ...), bboxes must be shifted back."""
    proc = FakeHiveProcessor(
        detections=[_MLDetection(bbox=(5, 10, 35, 40), score=0.42)],
    )
    det = HiveDetector(
        model_id="m", slug="s", processor=proc, imgsz=320, model_family="yolo",
    )
    frame = _frame(np.zeros((480, 640, 3), dtype=np.uint8))
    zone = RectZone(x=100, y=100, w=200, h=150)

    batch = det.detect(frame, zone)

    # Processor was called with the cropped region (150 rows x 200 cols).
    assert proc.calls == [(150, 200)]
    assert len(batch.detections) == 1
    # (5, 10, 35, 40) + (100, 100) offset -> (105, 110, 135, 140)
    assert batch.detections[0].bbox_xyxy == (105, 110, 135, 140)


def test_hive_detector_polygon_zone_masks_to_polygon_inside_bounding_rect() -> None:
    proc = FakeHiveProcessor(detections=[_MLDetection(bbox=(0, 0, 10, 10), score=0.9)])
    det = HiveDetector(
        model_id="m", slug="s", processor=proc, imgsz=320, model_family="yolo",
    )
    frame = _frame(np.full((200, 200, 3), 255, dtype=np.uint8))
    zone = PolygonZone(vertices=((50, 50), (150, 60), (120, 160), (40, 140)))

    _ = det.detect(frame, zone)

    # Bounding rect of vertices: x in [40, 150], y in [50, 160] => crop 110x110.
    assert proc.calls == [(110, 110)]
    assert proc.last_image is not None
    # Pixels in the bounding rect but outside the polygon must be masked out.
    assert int(proc.last_image[0, 0, 0]) == 0
    # Pixels well inside the polygon remain intact.
    assert int(proc.last_image[40, 40, 0]) == 255


def test_hive_detector_filters_detections_outside_polygon_center() -> None:
    proc = FakeHiveProcessor(
        detections=[
            _MLDetection(bbox=(0, 0, 10, 10), score=0.9),
            _MLDetection(bbox=(45, 45, 65, 65), score=0.8),
        ]
    )
    det = HiveDetector(
        model_id="m", slug="s", processor=proc, imgsz=320, model_family="yolo",
    )
    frame = _frame(np.full((200, 200, 3), 255, dtype=np.uint8))
    zone = PolygonZone(vertices=((50, 50), (150, 60), (120, 160), (40, 140)))

    batch = det.detect(frame, zone)

    # The bbox centered near the top-left corner of the bounding rect is
    # outside the actual polygon and must be discarded.
    assert [d.bbox_xyxy for d in batch.detections] == [(85, 95, 105, 115)]


def test_hive_detector_polar_zone_not_implemented() -> None:
    proc = FakeHiveProcessor()
    det = HiveDetector(
        model_id="m", slug="s", processor=proc, imgsz=320, model_family="yolo",
    )
    frame = _frame(np.zeros((200, 200, 3), dtype=np.uint8))
    zone = PolarZone(
        center_xy=(100.0, 100.0),
        r_inner=30.0,
        r_outer=60.0,
        theta_start_rad=0.0,
        theta_end_rad=6.28,
    )

    with pytest.raises(NotImplementedError):
        det.detect(frame, zone)


def test_hive_detector_empty_crop_yields_empty_batch() -> None:
    proc = FakeHiveProcessor(detections=[_MLDetection(bbox=(0, 0, 5, 5), score=0.9)])
    det = HiveDetector(
        model_id="m", slug="s", processor=proc, imgsz=320, model_family="yolo",
    )
    # Zone entirely outside the frame -> crop has zero area.
    frame = _frame(np.zeros((100, 100, 3), dtype=np.uint8))
    zone = RectZone(x=200, y=200, w=50, h=50)

    batch = det.detect(frame, zone)

    assert batch.detections == ()
    assert proc.calls == []  # inference skipped when crop is empty


def test_hive_detector_reset_and_stop_dispatch_to_processor() -> None:
    proc = FakeHiveProcessor()
    det = HiveDetector(
        model_id="m", slug="s", processor=proc, imgsz=320, model_family="yolo",
    )
    det.reset()
    det.stop()
    assert proc.reset_calls == 1
    assert proc.closed is True


# --- Discovery / registration tests -----------------------------------------


def _write_run_json(dir_path: Path, payload: dict[str, Any]) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "run.json").write_text(json.dumps(payload))


def _write_onnx_artifact(dir_path: Path) -> Path:
    exports = dir_path / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    path = exports / "best.onnx"
    path.write_bytes(b"\x00\x00")
    return path


def test_discover_and_register_with_mock_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Layout two mock hive dirs — one yolo/onnx (valid), one with space in name.
    a = tmp_path / "hive-aaa"
    _write_run_json(
        a,
        {
            "hive": {"model_id": "aaa", "variant_runtime": "onnx"},
            "model_family": "yolo",
            "name": "c-channel-yolo11n-320",
            "imgsz": 320,
            "runtime": "onnx",
            "scopes": ["c_channel"],
        },
    )
    _write_onnx_artifact(a)

    b = tmp_path / "hive-bbb"
    _write_run_json(
        b,
        {
            "hive": {"model_id": "bbb", "variant_runtime": "onnx"},
            "model_family": "yolo",
            "name": "Carousel YOLO11n 320",
            "imgsz": 320,
            "runtime": "onnx",
            "scopes": ["carousel"],
        },
    )
    _write_onnx_artifact(b)

    # Skip dir: unsupported family.
    c = tmp_path / "hive-ccc"
    _write_run_json(
        c,
        {
            "hive": {"model_id": "ccc", "variant_runtime": "onnx"},
            "model_family": "detectron2",
            "name": "unsupported-model",
            "imgsz": 320,
        },
    )
    _write_onnx_artifact(c)

    # Skip dir: missing exports/.
    d = tmp_path / "hive-ddd"
    _write_run_json(
        d,
        {
            "hive": {"model_id": "ddd", "variant_runtime": "onnx"},
            "model_family": "yolo",
            "name": "artifact-missing",
            "imgsz": 320,
        },
    )

    # Bridge stubs: avoid touching the real legacy factory (no ONNX load).
    sentinel_paths: dict[Path, bool] = {}

    def fake_resolve(run_dir: Path, runtime: str) -> Path | None:
        artifact = run_dir / "exports" / "best.onnx"
        return artifact if artifact.exists() else None

    def fake_build(**kwargs: Any) -> Any:
        sentinel_paths[kwargs["model_path"]] = True
        return FakeHiveProcessor()

    monkeypatch.setattr(hive_onnx, "_resolve_model_artifact", fake_resolve)
    monkeypatch.setattr(hive_onnx, "_build_processor", fake_build)

    registry: StrategyRegistry[Any] = StrategyRegistry("detector")
    registered = discover_and_register_hive_detectors(tmp_path, registry=registry)

    assert sorted(registered) == ["c-channel-yolo11n-320", "carousel-yolo11n-320"]
    keys = registry.keys()
    assert "hive:c-channel-yolo11n-320" in keys
    assert "hive:carousel-yolo11n-320" in keys

    # Lazy: no processor built yet.
    assert sentinel_paths == {}

    # Instantiation builds the processor via the bridge stub.
    det = registry.create("hive:c-channel-yolo11n-320")
    assert isinstance(det, HiveDetector)
    assert det.key == "hive:c-channel-yolo11n-320"
    assert len(sentinel_paths) == 1


def test_discover_returns_empty_for_missing_dir(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    registry: StrategyRegistry[Any] = StrategyRegistry("detector")
    registered = discover_and_register_hive_detectors(missing, registry=registry)
    assert registered == []
    assert registry.keys() == frozenset()


def test_discover_skips_unreadable_run_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = tmp_path / "hive-broken"
    broken.mkdir()
    (broken / "run.json").write_text("{not json")

    registry: StrategyRegistry[Any] = StrategyRegistry("detector")
    registered = discover_and_register_hive_detectors(tmp_path, registry=registry)
    assert registered == []


@pytest.mark.skipif(
    not (
        Path(__file__).resolve().parents[2] / "blob" / "hive_detection_models"
    ).exists(),
    reason="hive models not installed in this env",
)
def test_discover_with_real_models_dir_smoke() -> None:
    """Smoke: when real Hive models are present, c-channel target registers."""
    from rt.contracts.registry import DETECTORS

    # Re-running discovery is a no-op because slugs already exist in the
    # global registry (ValueError -> debug log). We just check the key is
    # present — it was registered by the import of rt.perception.detectors.
    assert default_hive_detector_slug() in DETECTORS.keys()
