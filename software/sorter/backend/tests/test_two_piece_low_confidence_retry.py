"""Second burst at rest for a low-confidence head."""
import logging
from types import SimpleNamespace

from defs.known_object import ClassificationStatus
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
    assert tp.worker.ctx.captured_crops == [] and tp.worker.ctx.classify_started_at == 0.0
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
