"""`BrickognizeClassifier` — bounded-concurrency Classifier implementation.

Wraps ``BrickognizeClient`` with a private ``ThreadPoolExecutor`` so the
number of in-flight HTTP calls is capped (default 4). Replaces the legacy
``threading.Thread(daemon=True)`` per-piece pattern from
``backend.classification.brickognize`` — the scout report flagged that as
a leak source when the feeder pushed pieces faster than Brickognize could
respond.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from rt.classification.brickognize import (
    ANY_COLOR_ID,
    BrickognizeClient,
    encode_jpeg,
    pick_best_color,
    pick_best_item,
)
from rt.contracts.classification import ClassifierResult
from rt.contracts.feed import FeedFrame
from rt.contracts.registry import register_classifier
from rt.contracts.tracking import Track


@register_classifier("brickognize")
class BrickognizeClassifier:
    """Synchronous + async Classifier backed by the Brickognize /predict API."""

    key = "brickognize"

    def __init__(
        self,
        *,
        max_concurrent: int = 4,
        timeout_s: float = 12.0,
        api_url: str | None = None,
        client: BrickognizeClient | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError(f"max_concurrent must be >= 1, got {max_concurrent}")
        if timeout_s <= 0.0:
            raise ValueError(f"timeout_s must be > 0, got {timeout_s}")
        self._max_concurrent = int(max_concurrent)
        self._timeout_s = float(timeout_s)
        self._logger = logger or logging.getLogger("rt.perception.classifiers.brickognize")
        self._client = client or BrickognizeClient(api_url=api_url)
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_concurrent,
            thread_name_prefix="brickognize",
        )
        self._stopped = False

    # ------------------------------------------------------------------
    # Classifier protocol

    def classify(
        self,
        track: Track,
        frame: FeedFrame,
        crop: Any,
    ) -> ClassifierResult:
        """Synchronous classify. Submits to executor, waits with timeout."""
        future = self.classify_async(track, frame, crop)
        try:
            return future.result(timeout=self._timeout_s)
        except TimeoutError:
            # concurrent.futures uses its own TimeoutError in Python 3.11+;
            # handled below as well.
            future.cancel()
            return self._timeout_result()
        except Exception as exc:
            import concurrent.futures as _cf

            if isinstance(exc, _cf.TimeoutError):
                future.cancel()
                return self._timeout_result()
            self._logger.exception("BrickognizeClassifier: classify raised")
            return self._error_result(exc)

    def classify_async(
        self,
        track: Track,
        frame: FeedFrame,
        crop: Any,
    ) -> "Future[ClassifierResult]":
        """Non-blocking submit — returns Future. Caller owns await semantics."""
        if self._stopped:
            fut: Future[ClassifierResult] = Future()
            fut.set_result(self._error_result(RuntimeError("classifier stopped")))
            return fut
        return self._executor.submit(self._run_one, track, frame, crop)

    def reset(self) -> None:
        # Brickognize has no internal state; no-op.
        return None

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            # cancel_futures only added in 3.9; keep compat.
            self._executor.shutdown(wait=False)
        try:
            self._client.close()
        except Exception:
            self._logger.debug("BrickognizeClassifier: client close raised", exc_info=True)

    # ------------------------------------------------------------------
    # Helpers

    def _run_one(
        self,
        track: Track,
        frame: FeedFrame,
        crop: Any,
    ) -> ClassifierResult:
        start = time.monotonic()
        try:
            jpeg = encode_jpeg(crop)
            response = self._client.predict(jpeg)
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000.0
            self._logger.warning(
                "BrickognizeClassifier: HTTP call failed for track=%s: %s",
                track.track_id,
                exc,
            )
            return ClassifierResult(
                part_id=None,
                color_id=None,
                category=None,
                confidence=0.0,
                algorithm=self.key,
                latency_ms=latency_ms,
                meta={"error": str(exc), "frame_seq": frame.frame_seq},
            )
        latency_ms = (time.monotonic() - start) * 1000.0

        best_item = pick_best_item(response)
        best_color = pick_best_color(response)
        color_id = best_color["id"] if best_color else ANY_COLOR_ID
        if best_item is None:
            return ClassifierResult(
                part_id=None,
                color_id=color_id,
                category=None,
                confidence=0.0,
                algorithm=self.key,
                latency_ms=latency_ms,
                meta={"frame_seq": frame.frame_seq, "no_items": True},
            )
        return ClassifierResult(
            part_id=str(best_item.get("id") or ""),
            color_id=color_id,
            category=str(best_item.get("category") or "") or None,
            confidence=float(best_item.get("score", 0.0) or 0.0),
            algorithm=self.key,
            latency_ms=latency_ms,
            meta={
                "frame_seq": frame.frame_seq,
                "name": best_item.get("name"),
                "preview_url": best_item.get("img_url"),
                "color_name": (best_color or {}).get("name") if best_color else None,
            },
        )

    def _timeout_result(self) -> ClassifierResult:
        return ClassifierResult(
            part_id=None,
            color_id=None,
            category=None,
            confidence=0.0,
            algorithm=self.key,
            latency_ms=self._timeout_s * 1000.0,
            meta={"timeout": True},
        )

    def _error_result(self, exc: BaseException) -> ClassifierResult:
        return ClassifierResult(
            part_id=None,
            color_id=None,
            category=None,
            confidence=0.0,
            algorithm=self.key,
            latency_ms=0.0,
            meta={"error": str(exc)},
        )


__all__ = ["BrickognizeClassifier"]
