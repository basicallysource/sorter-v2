from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from rt.classification.brickognize import BrickognizeClient
from rt.contracts.classification import ClassifierResult
from rt.contracts.feed import FeedFrame
from rt.contracts.registry import CLASSIFIERS
from rt.contracts.tracking import Track
from rt.perception.classifiers.brickognize import BrickognizeClassifier


class _FakeClient(BrickognizeClient):
    """Drop-in fake — skips the real HTTP path."""

    def __init__(
        self,
        *,
        response: dict[str, Any] | None = None,
        delay_s: float = 0.0,
        raise_exc: Exception | None = None,
    ) -> None:
        # Intentionally skip super().__init__ — the real one creates a session.
        self._response = response or {
            "items": [
                {"id": "3001", "name": "brick", "category": "part", "score": 0.88},
            ],
            "colors": [
                {"id": "red", "name": "Red", "score": 0.92},
            ],
        }
        self._delay_s = float(delay_s)
        self._raise = raise_exc
        self.call_count = 0
        self.inflight = 0
        self.peak_inflight = 0
        self._inflight_lock = threading.Lock()

    def predict(self, image_bytes: bytes) -> Any:
        with self._inflight_lock:
            self.inflight += 1
            self.peak_inflight = max(self.peak_inflight, self.inflight)
            self.call_count += 1
        try:
            if self._delay_s:
                time.sleep(self._delay_s)
            if self._raise is not None:
                raise self._raise
            return self._response
        finally:
            with self._inflight_lock:
                self.inflight -= 1

    def close(self) -> None:  # pragma: no cover
        return None


def _track(track_id: int = 1, global_id: int | None = 1) -> Track:
    return Track(
        track_id=track_id,
        global_id=global_id,
        piece_uuid=None,
        bbox_xyxy=(0, 0, 10, 10),
        score=0.9,
        confirmed_real=True,
        angle_rad=0.0,
        radius_px=50.0,
        hit_count=5,
        first_seen_ts=0.0,
        last_seen_ts=0.0,
    )


def _frame(frame_seq: int = 1) -> FeedFrame:
    return FeedFrame(
        feed_id="c4_feed",
        camera_id="c4",
        raw=None,
        gray=None,
        timestamp=0.0,
        monotonic_ts=0.0,
        frame_seq=frame_seq,
    )


def _crop_bytes() -> bytes:
    # Fake already-encoded JPEG — encode_jpeg pass-through accepts bytes.
    return b"\xff\xd8\xff\xe0fake_jpeg_body"


def test_brickognize_classifier_registered() -> None:
    assert "brickognize" in CLASSIFIERS.keys()


def test_classify_returns_result() -> None:
    fake = _FakeClient()
    clf = BrickognizeClassifier(max_concurrent=2, timeout_s=1.0, client=fake)
    try:
        result = clf.classify(_track(), _frame(), _crop_bytes())
    finally:
        clf.stop()
    assert isinstance(result, ClassifierResult)
    assert result.part_id == "3001"
    assert result.color_id == "red"
    assert result.confidence == pytest.approx(0.88)
    assert result.algorithm == "brickognize"
    assert fake.call_count == 1


def test_classify_async_returns_future() -> None:
    fake = _FakeClient()
    clf = BrickognizeClassifier(max_concurrent=2, timeout_s=1.0, client=fake)
    try:
        fut = clf.classify_async(_track(), _frame(), _crop_bytes())
        result = fut.result(timeout=1.0)
    finally:
        clf.stop()
    assert result.part_id == "3001"


def test_classify_timeout_returns_timeout_result() -> None:
    fake = _FakeClient(delay_s=0.5)
    clf = BrickognizeClassifier(max_concurrent=2, timeout_s=0.05, client=fake)
    try:
        result = clf.classify(_track(), _frame(), _crop_bytes())
    finally:
        clf.stop()
    assert result.part_id is None
    assert result.meta.get("timeout") is True
    assert result.confidence == 0.0


def test_classify_http_error_returns_error_result() -> None:
    fake = _FakeClient(raise_exc=RuntimeError("boom"))
    clf = BrickognizeClassifier(max_concurrent=2, timeout_s=1.0, client=fake)
    try:
        result = clf.classify(_track(), _frame(), _crop_bytes())
    finally:
        clf.stop()
    assert result.part_id is None
    assert "boom" in (result.meta.get("error") or "")


def test_classify_bounds_concurrency() -> None:
    fake = _FakeClient(delay_s=0.1)
    clf = BrickognizeClassifier(max_concurrent=2, timeout_s=5.0, client=fake)
    try:
        futures = [
            clf.classify_async(_track(track_id=i), _frame(i), _crop_bytes())
            for i in range(5)
        ]
        for f in futures:
            f.result(timeout=5.0)
    finally:
        clf.stop()
    # Max 2 HTTP calls concurrently despite 5 submitted.
    assert fake.peak_inflight <= 2
    assert fake.call_count == 5


def test_stop_rejects_new_submissions() -> None:
    fake = _FakeClient()
    clf = BrickognizeClassifier(max_concurrent=1, timeout_s=1.0, client=fake)
    clf.stop()
    fut = clf.classify_async(_track(), _frame(), _crop_bytes())
    result = fut.result(timeout=1.0)
    assert result.part_id is None
    assert "stopped" in (result.meta.get("error") or "").lower()


def test_classify_no_items_returns_null_part() -> None:
    fake = _FakeClient(response={"items": [], "colors": []})
    clf = BrickognizeClassifier(max_concurrent=1, timeout_s=1.0, client=fake)
    try:
        result = clf.classify(_track(), _frame(), _crop_bytes())
    finally:
        clf.stop()
    assert result.part_id is None
    assert result.meta.get("no_items") is True


def test_classifier_validates_constructor() -> None:
    with pytest.raises(ValueError):
        BrickognizeClassifier(max_concurrent=0)
    with pytest.raises(ValueError):
        BrickognizeClassifier(timeout_s=0.0)


def test_reset_is_noop() -> None:
    fake = _FakeClient()
    clf = BrickognizeClassifier(client=fake)
    try:
        clf.reset()  # just must not raise
    finally:
        clf.stop()
