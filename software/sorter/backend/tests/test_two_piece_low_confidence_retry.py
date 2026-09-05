"""Second burst at rest for a low-confidence head."""
import logging
import threading
from types import SimpleNamespace

from defs.known_object import ClassificationStatus
from defs.known_object import KnownObject
from subsystems.classification_channel.simple_state_machine_rev01.base import Rev01BaseState
from subsystems.classification_channel.two_piece import (
    TwoPieceClassificationChannel,
    _TrackedPiece,
    _topScore,
    retryImproves,
)


def test_retry_improves_only_on_a_higher_score() -> None:
    assert retryImproves(0.7, 0.55)
    assert not retryImproves(0.5, 0.55)
    assert not retryImproves(None, 0.55)
    assert retryImproves(0.3, None)
    assert _topScore({"items": [{"score": 0.71}]}) == 0.71
    assert _topScore({"items": []}) is None
    assert _topScore(None) is None


def _handler():
    h = object.__new__(TwoPieceClassificationChannel)
    h.logger = logging.getLogger("test")
    h.ctx = SimpleNamespace(config=SimpleNamespace(low_confidence_retry=True))
    return h


def _piece(status, confidence):
    tp = object.__new__(_TrackedPiece)
    tp.track_id = 9
    tp.retry_started = False
    tp.retry_done = False
    tp.first_score = None
    tp.retry_base = 0
    tp.stray = False
    tp.capture_done = True
    tp.result_applied = True
    ctx = SimpleNamespace(captured_crops=[1], captured_crop_timestamps=[1], captured_crop_sharpness=[1],
                          captured_crop_quality=[1], capturing_started_at=5.0, classify_started_at=6.0,
                          classification_result={"items": []}, classification_error=None)
    tp.worker = SimpleNamespace(ctx=ctx)
    obj = SimpleNamespace(classification_status=status, confidence=confidence)
    return tp, obj


def test_low_confidence_head_starts_a_second_burst_and_holds_the_aim() -> None:
    h = _handler()
    tp, obj = _piece(ClassificationStatus.low_confidence, 0.55)
    assert h._retryHeadAtRest(tp, obj) is True
    assert tp.retry_started and not tp.capture_done and not tp.result_applied
    assert tp.first_score == 0.55
    assert tp.worker.ctx.captured_crops == [1] and tp.retry_base == 1  # in-flight frames kept
    assert tp.worker.ctx.classify_started_at == 0.0
    # still waiting while the retry runs
    assert h._retryHeadAtRest(tp, obj) is True
    tp.retry_done = True
    assert h._retryHeadAtRest(tp, obj) is False


def test_classified_head_is_not_retried() -> None:
    h = _handler()
    tp, obj = _piece(ClassificationStatus.classified, 0.8)
    assert h._retryHeadAtRest(tp, obj) is False
    assert not tp.retry_started


def test_retry_disabled_by_config() -> None:
    h = _handler()
    h.ctx.config.low_confidence_retry = False
    tp, obj = _piece(ClassificationStatus.low_confidence, 0.55)
    assert h._retryHeadAtRest(tp, obj) is False


def test_not_found_head_is_retried_too() -> None:
    h = _handler()
    tp, obj = _piece(ClassificationStatus.not_found, None)
    assert h._retryHeadAtRest(tp, obj) is True
    assert tp.retry_started and tp.first_score is None
    assert retryImproves(0.42, None)


def test_head_with_retry_in_flight_is_not_a_stray() -> None:
    h = _handler()
    h._orphans = []
    h._pieces = {}
    tp, obj = _piece(ClassificationStatus.low_confidence, 0.5)
    h._retryHeadAtRest(tp, obj)               # retry started: classify_started_at reset
    tp.created_at = -100.0                    # far older than the stray grace
    tp.worker.ctx.classify_started_at = 0.0
    tp.zone = 0
    tp.placed = False
    tp.gap_to_exit = 10.0
    h._headPiece = lambda: tp
    h._ensureKnownObject = lambda t: None
    logged = []
    h.logger = SimpleNamespace(info=lambda m: logged.append(m), warning=lambda m: logged.append("WARN " + m))
    h._aimChuteForHead(now=1000.0)
    assert not any("stray head" in m for m in logged)
    assert tp.result_applied is False and tp.retry_started


def test_retry_timeout_preserves_rejected_result_and_ignores_late_response() -> None:
    h = _handler()
    obj = KnownObject(part_id="3001", confidence=0.55,
                      classification_status=ClassificationStatus.low_confidence)
    worker = object.__new__(Rev01BaseState)
    worker.ctx = SimpleNamespace(
        known_object=obj, captured_crops=[], classification_result=None,
        classification_error=None, classify_started_at=1.0,
        classify_lock=threading.Lock(), config=SimpleNamespace(classify_timeout_s=5),
        color_provider=None, mold_provider=None, classification_attempts=[],
        classification_strategy=None,
    )
    worker.emitKnownObject = lambda: None
    tp = _TrackedPiece(1, worker, 0.0)
    tp.retry_started = True
    h._pieces = {1: tp}
    h.noteProgress = lambda: None
    h._applyResults(10.0)
    assert tp.retry_done and tp.result_applied
    assert obj.classification_status == ClassificationStatus.low_confidence
    assert obj.part_id == "3001" and obj.confidence == 0.55
    worker.ctx.classification_result = {"items": [{"id": "3002", "score": 0.99}]}
    h._applyResults(11.0)
    assert obj.part_id == "3001" and obj.classification_status == ClassificationStatus.low_confidence
