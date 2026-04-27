from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from rt.contracts.detection import Detection, DetectionBatch
from rt.contracts.events import Event
from rt.contracts.feed import FeedFrame, PolygonZone, RectZone
from rt.contracts.tracking import Track, TrackBatch
from rt.events.bus import InProcessEventBus
from rt.events.topics import RUNTIME_MOVE_COMPLETED
from rt.perception.pipeline import PerceptionFrameState
from rt.perception.teacher_samples import (
    AuxiliaryTeacherSampleCollector,
    TeacherAnnotation,
    TeacherDetection,
    TeacherSampleCollectionConfig,
    _gemini_prompt,
)
from utils.polygon_crop import apply_polygon_crop


def test_gemini_prompt_emphasizes_individual_parts_and_transparent_pieces() -> None:
    prompt = _gemini_prompt(640, 480, "classification_channel")

    assert "Prefer splitting over grouping" in prompt
    assert "Strive for exhaustive recall" in prompt
    assert "do not omit any real loose part" in prompt
    assert "one tight box per part" in prompt
    assert "Do not draw one large box around a pile" in prompt
    assert "transparent, translucent, clear, smoky, or tinted LEGO pieces" in prompt
    assert "avoid labeling pure glare" in prompt


@dataclass
class _Feed:
    feed_id: str


@dataclass
class _Detector:
    key: str = "hive:test-detector"

    def _apply_zone(
        self,
        raw: np.ndarray,
        zone: Any,
    ) -> tuple[np.ndarray | None, tuple[int, int]]:
        if isinstance(zone, RectZone):
            x1 = max(0, int(zone.x))
            y1 = max(0, int(zone.y))
            x2 = min(int(raw.shape[1]), int(zone.x + zone.w))
            y2 = min(int(raw.shape[0]), int(zone.y + zone.h))
            if x2 <= x1 or y2 <= y1:
                return None, (0, 0)
            return np.ascontiguousarray(raw[y1:y2, x1:x2]), (x1, y1)
        raise NotImplementedError


@dataclass
class _PolygonDetector:
    key: str = "hive:test-detector"

    def _apply_zone(
        self,
        raw: np.ndarray,
        zone: Any,
    ) -> tuple[np.ndarray | None, tuple[int, int]]:
        if not isinstance(zone, PolygonZone):
            raise NotImplementedError
        return apply_polygon_crop(raw, zone.vertices)


@dataclass
class _ApronDetector:
    key: str = "hive:test-detector"

    def _apply_zone(
        self,
        raw: np.ndarray,
        zone: Any,  # noqa: ARG002
    ) -> tuple[np.ndarray | None, tuple[int, int]]:
        return np.ascontiguousarray(raw), (0, 0)


class _Pipeline:
    def __init__(
        self,
        feed_id: str,
        zone: Any | None = None,
        detector: Any | None = None,
    ) -> None:
        self.feed = _Feed(feed_id)
        self.zone = zone or RectZone(x=0, y=0, w=120, h=120)
        self.detector = detector or _Detector()


class _Runner:
    def __init__(
        self,
        feed_id: str,
        state: Any | None,
        *,
        zone: Any | None = None,
        detector: Any | None = None,
    ) -> None:
        self._pipeline = _Pipeline(feed_id, zone=zone, detector=detector)
        self._state = state

    def latest_state(self) -> Any | None:
        return self._state


class _TrainingManager:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    def saveAuxiliaryDetectionCapture(self, **kwargs: Any) -> dict[str, Any]:
        self.saved.append(kwargs)
        return {"ok": True, "sample_id": f"sample-{len(self.saved)}"}


class _Teacher:
    def __init__(
        self,
        detections: tuple[TeacherDetection, ...] | None = None,
        *,
        model: str = "google/gemini-3.1-flash-lite-preview",
    ) -> None:
        self._detections = (
            detections
            if detections is not None
            else (
                TeacherDetection(
                    bbox_xyxy=(20, 20, 50, 50),
                    confidence=0.91,
                    kind="lego",
                    description="red plate",
                ),
            )
        )
        self._model = model
        self.calls: list[dict[str, Any]] = []

    def annotate(
        self,
        image: np.ndarray,
        *,
        source_role: str,
        feed_id: str,
        model: str | None,
    ) -> TeacherAnnotation:
        self.calls.append(
            {
                "shape": tuple(image.shape),
                "source_role": source_role,
                "feed_id": feed_id,
                "model": model,
            }
        )
        return TeacherAnnotation(
            model=model or self._model,
            detections=self._detections,
            raw_payload={"detections": []},
        )


class _ExplodingTeacher:
    def annotate(
        self,
        image: np.ndarray,  # noqa: ARG002
        *,
        source_role: str,  # noqa: ARG002
        feed_id: str,  # noqa: ARG002
        model: str | None,  # noqa: ARG002
    ) -> TeacherAnnotation:
        raise RuntimeError("teacher exploded")


class _MinimalLogger:
    def __init__(self) -> None:
        self.messages: list[tuple[Any, ...]] = []

    def error(self, *args: Any) -> None:
        self.messages.append(args)


def _state(
    *,
    feed_id: str = "c2_feed",
    frame_seq: int = 1,
    bbox: tuple[int, int, int, int] = (40, 40, 70, 70),
    confirmed_real: bool = True,
    ghost: bool = False,
    raw_value: int = 255,
) -> PerceptionFrameState:
    raw = np.full((120, 120, 3), raw_value, dtype=np.uint8)
    frame = FeedFrame(
        feed_id=feed_id,
        camera_id=feed_id,
        raw=raw,
        gray=None,
        timestamp=100.0,
        monotonic_ts=10.0,
        frame_seq=frame_seq,
    )
    detections = DetectionBatch(
        feed_id=feed_id,
        frame_seq=frame_seq,
        timestamp=100.0,
        detections=(Detection(bbox_xyxy=bbox, score=0.87),),
        algorithm="hive:test-detector",
        latency_ms=1.0,
    )
    track = Track(
        track_id=1,
        global_id=10,
        piece_uuid="piece-1",
        bbox_xyxy=bbox,
        score=0.87,
        confirmed_real=confirmed_real,
        angle_rad=None,
        radius_px=None,
        hit_count=12,
        first_seen_ts=90.0,
        last_seen_ts=100.0,
        ghost=ghost,
    )
    filtered_tracks = () if ghost else (track,)
    tracks = TrackBatch(
        feed_id=feed_id,
        frame_seq=frame_seq,
        timestamp=100.0,
        tracks=filtered_tracks,
        lost_track_ids=(),
    )
    return PerceptionFrameState(
        frame=frame,
        detections=detections,
        raw_tracks=tracks,
        filtered_tracks=tracks,
    )


def _collector(
    runners: list[Any],
    manager: _TrainingManager,
    *,
    enabled_by_role: dict[str, bool] | None = None,
    teacher: _Teacher | None = None,
    wall_teacher: _Teacher | None = None,
    wall_detector_mode_enabled: bool = False,
    openrouter_model_by_role: dict[str, str] | None = None,
    event_bus: Any | None = None,
    move_trigger_settle_s: float = 0.0,
    worker_count: int = 1,
    gemini_worker_count: int = 1,
    angle_sample_degrees: float = 15.0,
    min_capture_interval_s: float = 2.0,
    logger: Any | None = None,
) -> AuxiliaryTeacherSampleCollector:
    config = TeacherSampleCollectionConfig(
        enabled_by_role=enabled_by_role or {"c_channel_2": True},
        interval_s=30.0,
        worker_count=worker_count,
        gemini_worker_count=gemini_worker_count,
        angle_sample_degrees=angle_sample_degrees,
        min_capture_interval_s=min_capture_interval_s,
        openrouter_model_by_role=openrouter_model_by_role
        or {"c_channel_2": "google/gemini-3.1-flash-lite-preview"},
        wall_detector_mode_enabled=wall_detector_mode_enabled,
    )
    teacher = teacher or _Teacher()
    wall_teacher_value = wall_teacher
    return AuxiliaryTeacherSampleCollector(
        runner_provider=lambda: runners,
        config_provider=lambda: config,
        training_manager_provider=lambda: manager,
        teacher_annotator_provider=lambda: teacher,
        wall_teacher_annotator_provider=(
            (lambda: wall_teacher_value) if wall_teacher_value is not None else None
        ),
        event_bus=event_bus,
        move_trigger_settle_s=move_trigger_settle_s,
        logger=logger,
    )


def test_collect_once_archives_cropped_positive_c_channel_sample() -> None:
    manager = _TrainingManager()
    zone = RectZone(x=20, y=20, w=80, h=80)
    runner = _Runner("c2_feed", _state(), zone=zone)
    teacher = _Teacher()
    collector = _collector([runner], manager, teacher=teacher)

    assert collector.collect_once() == 1

    assert len(manager.saved) == 1
    saved = manager.saved[0]
    assert saved["source"] == "live_aux_teacher_capture"
    assert saved["source_role"] == "c_channel_2"
    assert saved["detection_scope"] == "feeder"
    assert saved["capture_reason"] == "rt_manual_collect"
    assert saved["detection_algorithm"] == "gemini_sam"
    assert saved["detection_openrouter_model"] == "google/gemini-3.1-flash-lite-preview"
    assert saved["detection_bbox"] == [20, 20, 50, 50]
    assert saved["detection_candidate_bboxes"] == [[20, 20, 50, 50]]
    assert saved["detection_score"] == 0.91
    assert saved["input_image"].shape == (80, 80, 3)
    assert saved["source_frame"].shape == (120, 120, 3)
    assert teacher.calls == [
        {
            "shape": (80, 80, 3),
            "source_role": "c_channel_2",
            "feed_id": "c2_feed",
            "model": "google/gemini-3.1-flash-lite-preview",
        }
    ]
    assert saved["extra_metadata"]["teacher_capture"] is True
    assert saved["extra_metadata"]["teacher_capture_crop_mode"] == "detector_apply_zone"
    assert saved["extra_metadata"]["teacher_capture_trigger"] == "rt_manual_collect"
    assert (
        saved["extra_metadata"]["teacher_capture_label_source"]
        == "gemini_sam"
    )
    assert (
        saved["extra_metadata"]["teacher_capture_gemini_model"]
        == "google/gemini-3.1-flash-lite-preview"
    )
    assert saved["extra_metadata"]["teacher_capture_crop_bbox_full_frame"] == [
        20,
        20,
        100,
        100,
    ]
    assert saved["extra_metadata"]["teacher_capture_primary_bbox_full_frame"] == [
        40,
        40,
        70,
        70,
    ]


def test_collect_once_uses_median_gemini_confidence_as_sample_score() -> None:
    manager = _TrainingManager()
    runner = _Runner("c2_feed", _state())
    teacher = _Teacher(
        detections=(
            TeacherDetection(
                bbox_xyxy=(20, 20, 50, 50),
                confidence=0.99,
                kind="lego",
                description="red plate",
            ),
            TeacherDetection(
                bbox_xyxy=(55, 20, 80, 50),
                confidence=0.75,
                kind="lego",
                description="blue brick",
            ),
            TeacherDetection(
                bbox_xyxy=(20, 55, 50, 80),
                confidence=0.51,
                kind="lego",
                description="clear tile",
            ),
        )
    )
    collector = _collector([runner], manager, teacher=teacher)

    assert collector.collect_once() == 1

    saved = manager.saved[0]
    assert saved["detection_bbox"] == [20, 20, 50, 50]
    assert saved["detection_score"] == 0.75
    assert (
        saved["extra_metadata"]["teacher_capture_score_kind"]
        == "median_detection_confidence"
    )


def test_collect_once_archives_detector_masked_polygon_input() -> None:
    manager = _TrainingManager()
    zone = PolygonZone(vertices=((20, 20), (100, 20), (80, 100), (20, 100)))
    runner = _Runner("c2_feed", _state(), zone=zone, detector=_PolygonDetector())
    collector = _collector([runner], manager)

    assert collector.collect_once() == 1

    saved = manager.saved[0]
    assert saved["detection_bbox"] == [20, 20, 50, 50]
    assert saved["input_image"].shape == (80, 80, 3)
    assert int(saved["input_image"][10, 10, 0]) == 255
    assert int(saved["input_image"][79, 79, 0]) == 0
    assert saved["extra_metadata"]["teacher_capture_crop_mode"] == "polygon_masked_zone"
    assert saved["extra_metadata"]["teacher_capture_crop_bbox_full_frame"] == [
        20,
        20,
        100,
        100,
    ]


def test_collect_once_masks_polygon_teacher_sample_even_when_detector_uses_apron() -> None:
    manager = _TrainingManager()
    zone = PolygonZone(vertices=((20, 20), (100, 20), (80, 100), (20, 100)))
    runner = _Runner("c2_feed", _state(), zone=zone, detector=_ApronDetector())
    collector = _collector([runner], manager)

    assert collector.collect_once() == 1

    saved = manager.saved[0]
    assert saved["input_image"].shape == (80, 80, 3)
    assert int(saved["input_image"][79, 79, 0]) == 0
    assert saved["extra_metadata"]["teacher_capture_crop_mode"] == "polygon_masked_zone"


def test_collect_once_skips_when_teacher_input_crop_is_unavailable() -> None:
    manager = _TrainingManager()
    zone = RectZone(x=20, y=20, w=80, h=80)
    runner = _Runner("c2_feed", _state(), zone=zone, detector=object())
    collector = _collector([runner], manager)

    assert collector.collect_once() == 0

    assert manager.saved == []
    assert collector.status_snapshot()["skipped_no_state"] == 1


def test_collect_once_uses_gemini_teacher_even_when_rt_track_is_unconfirmed() -> None:
    manager = _TrainingManager()
    runner = _Runner("c2_feed", _state(confirmed_real=False))
    collector = _collector([runner], manager)

    assert collector.collect_once() == 1

    assert manager.saved[0]["detection_algorithm"] == "gemini_sam"
    assert manager.saved[0]["detection_bbox"] == [20, 20, 50, 50]


def test_collect_once_archives_negative_sample_when_gemini_finds_no_items() -> None:
    manager = _TrainingManager()
    teacher = _Teacher(detections=())
    runner = _Runner("c2_feed", _state())
    collector = _collector([runner], manager, teacher=teacher)

    assert collector.collect_once() == 1

    assert len(manager.saved) == 1
    saved = manager.saved[0]
    assert saved["detection_algorithm"] == "gemini_sam"
    assert saved["detection_found"] is False
    assert saved["detection_bbox"] is None
    assert saved["detection_candidate_bboxes"] == []
    assert saved["detection_bbox_count"] == 0
    assert saved["extra_metadata"]["teacher_capture_negative"] is True
    assert saved["extra_metadata"]["teacher_capture_gemini_detections"] == []
    snapshot = collector.status_snapshot()
    assert snapshot["teacher_call_count"] == 1
    assert snapshot["skipped_teacher_no_detections"] == 0


def test_collect_once_skips_black_startup_frame_before_gemini() -> None:
    manager = _TrainingManager()
    teacher = _Teacher()
    runner = _Runner("c2_feed", _state(raw_value=0))
    collector = _collector([runner], manager, teacher=teacher)

    assert collector.collect_once() == 0

    assert manager.saved == []
    assert teacher.calls == []
    snapshot = collector.status_snapshot()
    assert snapshot["skipped_low_signal"] == 1
    assert snapshot["skipped_low_signal_by_role"] == {"c_channel_2": 1}
    assert snapshot["teacher_call_count"] == 0


def test_collect_once_respects_disabled_role() -> None:
    manager = _TrainingManager()
    runner = _Runner("c2_feed", _state())
    collector = _collector(
        [runner],
        manager,
        enabled_by_role={"c_channel_2": False},
    )

    assert collector.collect_once() == 0

    assert manager.saved == []
    assert collector.status_snapshot()["skipped_disabled"] == 1


def test_collect_once_does_not_capture_same_frame_twice() -> None:
    manager = _TrainingManager()
    runner = _Runner("c2_feed", _state(frame_seq=12))
    collector = _collector([runner], manager)

    assert collector.collect_once() == 1
    assert collector.collect_once() == 0

    assert len(manager.saved) == 1
    snapshot = collector.status_snapshot()
    assert snapshot["last_seen_frame_by_role"] == {"c_channel_2": 12}
    assert snapshot["last_captured_frame_by_role"] == {"c_channel_2": 12}
    assert snapshot["skipped_duplicate_frame"] == 1


def test_collect_once_maps_c4_to_classification_channel_scope() -> None:
    manager = _TrainingManager()
    runner = _Runner("c4_feed", _state(feed_id="c4_feed"))
    collector = _collector(
        [runner],
        manager,
        enabled_by_role={"classification_channel": True},
    )

    assert collector.collect_once() == 1

    saved = manager.saved[0]
    assert saved["source_role"] == "classification_channel"
    assert saved["detection_scope"] == "classification_channel"
    assert saved["extra_metadata"]["teacher_capture_feed_id"] == "c4_feed"


def test_collect_once_routes_classification_channel_to_wall_teacher_when_enabled() -> None:
    """In wall-detector mode, C4 samples must hit the wall annotator (not the
    loose-piece one) and the saved capture must carry the wall algorithm id."""
    manager = _TrainingManager()
    runner = _Runner("c4_feed", _state(feed_id="c4_feed"))
    piece_teacher = _Teacher()
    wall_teacher = _Teacher(
        detections=(
            TeacherDetection(
                bbox_xyxy=(10, 20, 30, 200),
                confidence=0.85,
                kind="wall",
                description="wall",
            ),
        ),
    )
    collector = _collector(
        [runner],
        manager,
        enabled_by_role={"classification_channel": True},
        teacher=piece_teacher,
        wall_teacher=wall_teacher,
        wall_detector_mode_enabled=True,
    )

    assert collector.collect_once() == 1
    assert piece_teacher.calls == []
    assert len(wall_teacher.calls) == 1
    assert wall_teacher.calls[0]["source_role"] == "classification_channel"

    saved = manager.saved[0]
    assert saved["detection_algorithm"] == "gemini_wall_detector"
    assert saved["detection_bbox"] == [10, 20, 30, 200]
    assert saved["extra_metadata"]["teacher_capture_source"] == "gemini_wall_teacher"
    detections = saved["extra_metadata"]["teacher_capture_gemini_detections"]
    assert detections[0]["kind"] == "wall"


def test_collect_once_skips_wall_dispatch_for_feeder_roles() -> None:
    """Wall mode only applies to classification_channel; C2/C3 still use the
    loose-piece annotator even when the flag is on."""
    manager = _TrainingManager()
    runner = _Runner("c2_feed", _state(feed_id="c2_feed"))
    piece_teacher = _Teacher()
    wall_teacher = _Teacher()
    collector = _collector(
        [runner],
        manager,
        enabled_by_role={"c_channel_2": True},
        teacher=piece_teacher,
        wall_teacher=wall_teacher,
        wall_detector_mode_enabled=True,
    )

    assert collector.collect_once() == 1
    assert len(piece_teacher.calls) == 1
    assert wall_teacher.calls == []

    saved = manager.saved[0]
    assert saved["detection_algorithm"] == "gemini_sam"


def test_rotation_event_collects_only_the_changed_feed_after_move() -> None:
    manager = _TrainingManager()
    bus = InProcessEventBus()
    teacher = _Teacher()
    c2_runner = _Runner("c2_feed", _state(feed_id="c2_feed", frame_seq=1))
    c3_runner = _Runner("c3_feed", _state(feed_id="c3_feed", frame_seq=2))
    collector = _collector(
        [c2_runner, c3_runner],
        manager,
        enabled_by_role={"c_channel_2": True, "c_channel_3": True},
        openrouter_model_by_role={
            "c_channel_2": "google/gemini-3.1-flash-lite-preview",
            "c_channel_3": "google/gemini-3.1-flash-lite-preview",
        },
        teacher=teacher,
        event_bus=bus,
        move_trigger_settle_s=0.0,
    )

    collector.start()
    try:
        now = time.time()
        bus.publish(
            Event(
                topic=RUNTIME_MOVE_COMPLETED,
                payload={
                    "feed_id": "c3_feed",
                    "completed_ts": now - 0.5,
                    "source": "test_move",
                    "ok": True,
                    "duration_ms": 120,
                },
                source="test",
                ts_mono=1.0,
            )
        )
        bus.drain()
        deadline = time.time() + 1.0
        while not manager.saved and time.time() < deadline:
            time.sleep(0.01)
    finally:
        collector.stop()

    assert len(manager.saved) == 1
    saved = manager.saved[0]
    assert saved["source_role"] == "c_channel_3"
    assert saved["capture_reason"] == "rt_move_completed"
    assert saved["extra_metadata"]["teacher_capture_trigger"] == "rt_move_completed"
    assert saved["extra_metadata"]["teacher_capture_trigger_metadata"] == {
        "move_source": "test_move",
        "move_completed_ts": now - 0.5,
        "move_duration_ms": 120,
        "move_degrees": None,
        "angle_sample_degrees": 15.0,
        "angle_trigger_index": 0,
        "angle_trigger_count": 1,
    }
    assert teacher.calls == [
        {
            "shape": (120, 120, 3),
            "source_role": "c_channel_3",
            "feed_id": "c3_feed",
            "model": "google/gemini-3.1-flash-lite-preview",
        }
    ]
    snapshot = collector.status_snapshot()
    assert snapshot["collection_mode"] == "event_driven_rotation"
    assert snapshot["periodic_enabled"] is False
    assert snapshot["move_event_count"] == 1
    assert snapshot["triggered_collection_count"] == 1


def test_degree_moves_trigger_only_after_angle_step() -> None:
    manager = _TrainingManager()
    runner = _Runner("c4_feed", _state(feed_id="c4_feed", frame_seq=1))
    collector = _collector(
        [runner],
        manager,
        enabled_by_role={"classification_channel": True},
        openrouter_model_by_role={
            "classification_channel": "google/gemini-3-flash-preview",
        },
        angle_sample_degrees=15.0,
    )

    now = time.time()
    for degrees in (10.0, 4.0):
        collector._on_move_completed_event(  # noqa: SLF001
            Event(
                topic=RUNTIME_MOVE_COMPLETED,
                payload={
                    "feed_id": "c4_feed",
                    "completed_ts": now - 0.5,
                    "source": "c4_move",
                    "ok": True,
                    "degrees": degrees,
                },
                source="test",
                ts_mono=1.0,
            )
        )

    snapshot = collector.status_snapshot()
    assert snapshot["trigger_queue_depth"] == 0
    assert snapshot["subthreshold_move_count_by_role"] == {
        "classification_channel": 2,
    }
    assert snapshot["angle_remainder_by_role"]["classification_channel"] == 14.0

    collector._on_move_completed_event(  # noqa: SLF001
        Event(
            topic=RUNTIME_MOVE_COMPLETED,
            payload={
                "feed_id": "c4_feed",
                "completed_ts": now - 0.5,
                "source": "c4_move",
                "ok": True,
                "degrees": 1.0,
            },
            source="test",
            ts_mono=1.0,
        )
    )

    snapshot = collector.status_snapshot()
    assert snapshot["trigger_queue_depth"] == 1
    assert snapshot["angle_trigger_count_by_role"] == {
        "classification_channel": 1,
    }
    assert snapshot["angle_remainder_by_role"]["classification_channel"] == 0.0


def test_async_capture_queue_throttles_per_role() -> None:
    manager = _TrainingManager()
    runner = _Runner("c2_feed", _state(feed_id="c2_feed", frame_seq=1))
    collector = _collector(
        [runner],
        manager,
        enabled_by_role={"c_channel_2": True},
        min_capture_interval_s=2.0,
    )

    assert (
        collector._enqueue_samples_once(  # noqa: SLF001
            source_roles={"c_channel_2"},
            trigger_reason="rt_move_completed",
            trigger_metadata={},
        )
        == 1
    )
    runner._state = _state(feed_id="c2_feed", frame_seq=2)  # noqa: SLF001
    assert (
        collector._enqueue_samples_once(  # noqa: SLF001
            source_roles={"c_channel_2"},
            trigger_reason="rt_move_completed",
            trigger_metadata={},
        )
        == 0
    )

    snapshot = collector.status_snapshot()
    assert snapshot["sample_queue_depth"] == 1
    assert snapshot["sample_queue_depth_by_role"] == {"c_channel_2": 1}
    assert snapshot["skipped_throttled_by_role"] == {"c_channel_2": 1}


def test_worker_survives_teacher_error_with_minimal_logger() -> None:
    manager = _TrainingManager()
    bus = InProcessEventBus()
    logger = _MinimalLogger()
    runner = _Runner("c2_feed", _state(feed_id="c2_feed", frame_seq=1))
    collector = _collector(
        [runner],
        manager,
        teacher=_ExplodingTeacher(),  # type: ignore[arg-type]
        event_bus=bus,
        move_trigger_settle_s=0.0,
        logger=logger,
    )

    collector.start()
    try:
        bus.publish(
            Event(
                topic=RUNTIME_MOVE_COMPLETED,
                payload={
                    "feed_id": "c2_feed",
                    "completed_ts": time.time() - 0.5,
                    "source": "test_move",
                    "ok": True,
                },
                source="test",
                ts_mono=1.0,
            )
        )
        bus.drain()
        deadline = time.time() + 1.0
        snapshot = collector.status_snapshot()
        while snapshot["error_count"] < 1 and time.time() < deadline:
            time.sleep(0.01)
            snapshot = collector.status_snapshot()
        assert snapshot["error_count"] >= 1
        assert snapshot["thread_alive"] is True
        assert snapshot["alive_worker_count"] == 1
    finally:
        collector.stop()

    assert logger.messages
    assert manager.saved == []


def test_move_triggers_queue_without_starving_other_channels() -> None:
    manager = _TrainingManager()
    teacher = _Teacher()
    c2_runner = _Runner("c2_feed", _state(feed_id="c2_feed", frame_seq=1))
    c4_runner = _Runner("c4_feed", _state(feed_id="c4_feed", frame_seq=2))
    collector = _collector(
        [c2_runner, c4_runner],
        manager,
        enabled_by_role={"c_channel_2": True, "classification_channel": True},
        openrouter_model_by_role={
            "c_channel_2": "google/gemini-3.1-flash-lite-preview",
            "classification_channel": "google/gemini-3-flash-preview",
        },
        teacher=teacher,
        move_trigger_settle_s=0.0,
        min_capture_interval_s=0.01,
    )

    now = time.time()
    for feed_id, source in (
        ("c4_feed", "c4_move_a"),
        ("c4_feed", "c4_move_b"),
        ("c2_feed", "c2_move"),
    ):
        collector._on_move_completed_event(  # noqa: SLF001
            Event(
                topic=RUNTIME_MOVE_COMPLETED,
                payload={
                    "feed_id": feed_id,
                    "completed_ts": now - 0.5,
                    "source": source,
                    "ok": True,
                },
                source="test",
                ts_mono=1.0,
            )
        )

    snapshot = collector.status_snapshot()
    assert snapshot["move_event_count_by_role"] == {
        "classification_channel": 2,
        "c_channel_2": 1,
    }
    assert snapshot["trigger_queue_depth"] == 3
    assert snapshot["trigger_queue_coalesced_by_role"] == {}

    collector.start()
    try:
        deadline = time.time() + 1.0
        while len(manager.saved) < 2 and time.time() < deadline:
            time.sleep(0.01)
    finally:
        collector.stop()

    assert sorted(saved["source_role"] for saved in manager.saved) == [
        "c_channel_2",
        "classification_channel",
    ]
