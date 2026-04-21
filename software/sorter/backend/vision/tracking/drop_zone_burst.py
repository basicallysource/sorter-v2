"""Drop-zone burst capture: ±2s of YOLO-detected frames around first C4 entry.

When a piece is first registered on the classification channel (C4 carousel),
this module captures a burst of ~60 frames — the last ~30 frames already in the
rolling pre-buffer plus ~30 live frames after the trigger. Each frame is run
through the carousel YOLO/hive detector to extract a tight crop.

The burst is attached to the piece's ``TrackHistoryEntry`` via
``PieceHistoryBuffer.attach_burst`` so it appears on the detail page.
"""

from __future__ import annotations

import base64
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

import cv2
import numpy as np

from .history import DropZoneBurstFrame, PieceHistoryBuffer, BURST_JPEG_QUALITY, BURST_MAX_EDGE_PX

BURST_PRE_FRAMES = 30
BURST_POST_FRAMES = 30
BURST_FPS = 15
BURST_PRE_BUFFER_MAXLEN = BURST_PRE_FRAMES + 10


@dataclass
class _BufferedFrame:
    raw: np.ndarray
    timestamp: float


def _encode_frame(frame: np.ndarray) -> str:
    h, w = frame.shape[:2]
    longest = max(h, w)
    if longest > BURST_MAX_EDGE_PX:
        scale = BURST_MAX_EDGE_PX / float(longest)
        frame = cv2.resize(
            frame,
            (int(round(w * scale)), int(round(h * scale))),
            interpolation=cv2.INTER_AREA,
        )
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, BURST_JPEG_QUALITY])
    if not ok:
        return ""
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _encode_crop(frame: np.ndarray, bbox: tuple[int, int, int, int], margin_px: int = 20) -> str:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    x1 = max(0, x1 - margin_px)
    y1 = max(0, y1 - margin_px)
    x2 = min(w, x2 + margin_px)
    y2 = min(h, y2 + margin_px)
    if x2 <= x1 or y2 <= y1:
        return _encode_frame(frame)
    crop = frame[y1:y2, x1:x2]
    return _encode_frame(crop)


class RollingFrameBuffer:
    """Thread-safe rolling buffer of the last N raw frames from a capture thread."""

    def __init__(self, maxlen: int = BURST_PRE_BUFFER_MAXLEN) -> None:
        self._lock = threading.Lock()
        self._buf: deque[_BufferedFrame] = deque(maxlen=maxlen)

    def push(self, frame: np.ndarray, timestamp: float) -> None:
        with self._lock:
            self._buf.append(_BufferedFrame(raw=frame.copy(), timestamp=timestamp))

    def snapshot(self) -> list[_BufferedFrame]:
        with self._lock:
            return list(self._buf)


class DropZoneBurstCollector:
    """Manages per-piece burst collection for C4 first-entry events.

    Usage:
    1. Push frames into ``rolling_buffer`` from the carousel capture thread.
    2. Call ``trigger(global_id, detect_fn)`` when a new piece is registered.
       The collector grabs the pre-buffer snapshot, then collects post-burst
       frames in a background thread, runs ``detect_fn`` on each, and finally
       calls ``history.attach_burst(global_id, frames)``.
    """

    def __init__(self, history: PieceHistoryBuffer) -> None:
        self._history = history
        self.rolling_buffer = RollingFrameBuffer(maxlen=BURST_PRE_BUFFER_MAXLEN)
        self._active: dict[int, threading.Thread] = {}
        self._lock = threading.Lock()

    def trigger(
        self,
        global_id: int,
        detect_fn: Callable[[np.ndarray], tuple[tuple[int, int, int, int] | None, float | None]],
        get_latest_frame: Callable[[], tuple[np.ndarray, float] | None],
    ) -> None:
        """Trigger a burst collection for ``global_id``.

        ``detect_fn(frame_bgr)`` → ``(bbox_xyxy | None, score | None)``
        ``get_latest_frame()`` → ``(frame_bgr, timestamp) | None``
        """
        with self._lock:
            if global_id in self._active:
                return
            pre_frames = self.rolling_buffer.snapshot()
            t = threading.Thread(
                target=self._collect,
                args=(global_id, pre_frames, detect_fn, get_latest_frame),
                daemon=True,
                name=f"drop-burst-{global_id}",
            )
            self._active[global_id] = t
        t.start()

    def _collect(
        self,
        global_id: int,
        pre_frames: list[_BufferedFrame],
        detect_fn: Callable[[np.ndarray], tuple[tuple[int, int, int, int] | None, float | None]],
        get_latest_frame: Callable[[], tuple[np.ndarray, float] | None],
    ) -> None:
        try:
            burst: list[DropZoneBurstFrame] = []
            trigger_ts = time.time()
            interval_s = 1.0 / BURST_FPS

            # Pre-burst: frames already in the rolling buffer (chronological)
            for idx, bf in enumerate(pre_frames):
                bbox, score = _safe_detect(detect_fn, bf.raw)
                jpeg_b64 = _encode_frame(bf.raw)
                crop_b64 = _encode_crop(bf.raw, bbox) if bbox is not None else jpeg_b64
                burst.append(
                    DropZoneBurstFrame(
                        frame_index=idx,
                        timestamp=bf.timestamp,
                        phase="pre",
                        detected=bbox is not None,
                        jpeg_b64=jpeg_b64,
                        crop_jpeg_b64=crop_b64,
                        bbox=bbox,
                        score=score,
                    )
                )

            # Post-burst: collect fresh frames from the live capture
            post_count = 0
            last_frame_ts: float = 0.0
            deadline = time.monotonic() + (BURST_POST_FRAMES / BURST_FPS) + 1.5
            frame_idx = len(burst)

            while post_count < BURST_POST_FRAMES and time.monotonic() < deadline:
                result = get_latest_frame()
                if result is None:
                    time.sleep(interval_s)
                    continue
                raw, ts = result
                if ts == last_frame_ts:
                    time.sleep(interval_s * 0.5)
                    continue
                last_frame_ts = ts
                bbox, score = _safe_detect(detect_fn, raw)
                jpeg_b64 = _encode_frame(raw)
                crop_b64 = _encode_crop(raw, bbox) if bbox is not None else jpeg_b64
                burst.append(
                    DropZoneBurstFrame(
                        frame_index=frame_idx,
                        timestamp=ts,
                        phase="post",
                        detected=bbox is not None,
                        jpeg_b64=jpeg_b64,
                        crop_jpeg_b64=crop_b64,
                        bbox=bbox,
                        score=score,
                    )
                )
                post_count += 1
                frame_idx += 1
                time.sleep(interval_s)

            self._history.attach_burst(global_id, burst)
        except Exception:
            pass
        finally:
            with self._lock:
                self._active.pop(global_id, None)


def _safe_detect(
    detect_fn: Callable[[np.ndarray], tuple[tuple[int, int, int, int] | None, float | None]],
    frame: np.ndarray,
) -> tuple[tuple[int, int, int, int] | None, float | None]:
    try:
        return detect_fn(frame)
    except Exception:
        return None, None
