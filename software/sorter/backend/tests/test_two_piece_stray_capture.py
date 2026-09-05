"""A head that appeared forward of the drop zone is photographed at rest
instead of being sent to misc unclassified."""
import logging
import threading
from types import SimpleNamespace

from defs.known_object import ClassificationStatus
from subsystems.classification_channel.two_piece import (
    _STRAY_CAPTURE_S,
    _STRAY_MISC_S,
    TwoPieceClassificationChannel,
    _TrackedPiece,
)


class _Worker:
    def __init__(self):
        self.ctx = SimpleNamespace(
            known_object=None, captured_crops=[], capturing_started_at=0.0,
            classify_started_at=0.0, classification_result=None, classification_error=None,
            classify_lock=threading.Lock(), config=SimpleNamespace(classify_timeout_s=10.0),
        )
        self.applied = []
        self.emitted = 0

    def emitKnownObject(self):
        self.emitted += 1

    def updateKnownObjectWithResult(self, result, error):
        self.applied.append((result, error))


def _handler(tp):
    h = object.__new__(TwoPieceClassificationChannel)
    h.logger = logging.getLogger("test")
    h.ctx = SimpleNamespace(config=SimpleNamespace(low_confidence_retry=True))
    h._pieces = {tp.track_id: tp}
    h._orphans = []
    h._headPiece = lambda: tp
    h.noteProgress = lambda: None
    h.shared = SimpleNamespace(distribution_ready=False)
    h.transport = SimpleNamespace(placePieceForDistribution=lambda obj: None)
    return h


def _stray(now=100.0):
    tp = _TrackedPiece(7, _Worker(), now)
    tp.zone = 0  # appeared in the holding band, never in the drop zone
    return tp


def test_stray_head_gets_an_at_rest_burst_after_the_grace_period() -> None:
    tp = _stray(now=100.0)
    h = _handler(tp)
    h._aimChuteForHead(100.0 + _STRAY_CAPTURE_S - 1)
    assert not tp.retry_started and not tp.placed
    h._aimChuteForHead(100.0 + _STRAY_CAPTURE_S + 1)
    assert tp.stray and tp.retry_started and not tp.retry_done and not tp.capture_done
    assert tp.known_object is not None
    assert not tp.placed  # aim waits for the burst


def test_stray_result_is_applied_whatever_its_score() -> None:
    tp = _stray()
    h = _handler(tp)
    h._startStrayCapture(tp)
    tp.capture_done = True
    tp.worker.ctx.classify_started_at = 105.0
    tp.worker.ctx.classification_result = {"items": [{"score": 0.31}]}
    h._applyResults(106.0)
    assert tp.retry_done and tp.result_applied
    assert tp.worker.applied == [({"items": [{"score": 0.31}]}, None)]


def test_stray_error_is_applied_too() -> None:
    tp = _stray()
    h = _handler(tp)
    h._startStrayCapture(tp)
    tp.capture_done = True
    tp.worker.ctx.classify_started_at = 105.0
    tp.worker.ctx.classification_error = "no_captures"
    h._applyResults(106.0)
    assert tp.worker.applied == [(None, "no_captures")]


def test_stray_without_an_at_rest_frame_drains_to_misc() -> None:
    tp = _stray(now=100.0)
    h = _handler(tp)
    h._startStrayCapture(tp)
    h._aimChuteForHead(100.0 + _STRAY_MISC_S - 1)
    assert not tp.placed
    h._aimChuteForHead(100.0 + _STRAY_MISC_S + 1)
    assert tp.retry_done and tp.result_applied and tp.placed
    assert tp.known_object.classification_status == ClassificationStatus.unknown
