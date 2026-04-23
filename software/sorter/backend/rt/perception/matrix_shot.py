"""Persist reverse-buffered free-fall frames for a piece.

Matrix-shot is deliberately a perception sidecar: it observes the piece
lifecycle, snapshots recent camera buffers, and persists debug/classification
evidence. It does not steer the runtime hot path.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from blob_manager import write_piece_crop
from local_state import remember_piece_dossier

from rt.contracts.events import Event, EventBus
from rt.events.topics import PIECE_REGISTERED


_LOG = logging.getLogger(__name__)
_SEGMENT_SEQUENCE = 0
_CROP_KIND = "matrix"
_DEFAULT_ROLES = ("c_channel_3", "carousel")
_QUEUE_MAX = 64


@dataclass(frozen=True, slots=True)
class MatrixShotConfig:
    roles: tuple[str, ...] = _DEFAULT_ROLES
    pre_window_s: float = 1.8
    post_window_s: float = 0.15
    ring_read_frames: int = 120
    max_frames_per_role: int = 12
    max_width_px: int = 960
    jpeg_quality: int = 82


@dataclass(frozen=True, slots=True)
class _CandidateFrame:
    role: str
    captured_ts: float
    raw: np.ndarray


class MatrixShotRecorder:
    """Capture a small, disk-backed frame burst around C3 -> C4 handoff.

    The trigger is C4's first confirmed registration of a piece. At that
    instant the camera capture threads already hold a short history, so the
    recorder can walk backward through the C3 and C4 ring buffers and archive
    frames from the fall without adding latency to the perception loop.
    """

    def __init__(
        self,
        camera_service: Any,
        *,
        config: MatrixShotConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._camera_service = camera_service
        self._config = config or MatrixShotConfig()
        self._logger = logger or _LOG
        self._jobs: queue.Queue[tuple[str, float] | None] = queue.Queue(maxsize=_QUEUE_MAX)
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="MatrixShotRecorder",
            daemon=True,
        )
        self._thread.start()

    def enqueue(self, *, piece_uuid: str, trigger_wall_ts: float | None = None) -> None:
        if not isinstance(piece_uuid, str) or not piece_uuid.strip():
            return
        trigger = float(trigger_wall_ts if trigger_wall_ts is not None else time.time())
        try:
            self._jobs.put_nowait((piece_uuid, trigger))
        except queue.Full:
            self._logger.warning("matrix_shot: queue full, dropping job for %s", piece_uuid)

    def capture_now(
        self,
        *,
        piece_uuid: str,
        trigger_wall_ts: float | None = None,
    ) -> dict[str, Any] | None:
        """Synchronously capture and persist one matrix-shot manifest."""
        if not isinstance(piece_uuid, str) or not piece_uuid.strip():
            return None
        trigger = float(trigger_wall_ts if trigger_wall_ts is not None else time.time())
        candidates = self._collect_candidates(trigger)
        frames = self._persist_frames(piece_uuid=piece_uuid, candidates=candidates, trigger=trigger)
        manifest: dict[str, Any] = {
            "name": "Matrix-Shot",
            "status": "captured" if frames else "empty",
            "triggered_at": trigger,
            "pre_window_s": float(self._config.pre_window_s),
            "post_window_s": float(self._config.post_window_s),
            "roles": list(self._config.roles),
            "frame_count": len(frames),
            "frames": frames,
        }
        try:
            remember_piece_dossier(
                piece_uuid,
                {
                    "matrix_shot": manifest,
                    "updated_at": time.time(),
                },
            )
        except Exception:
            self._logger.exception("matrix_shot: failed to persist dossier manifest for %s", piece_uuid)
        return manifest

    def _worker_loop(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            piece_uuid, trigger = job
            try:
                self.capture_now(piece_uuid=piece_uuid, trigger_wall_ts=trigger)
            except Exception:
                self._logger.exception("matrix_shot: capture failed for %s", piece_uuid)

    def _collect_candidates(self, trigger: float) -> list[_CandidateFrame]:
        start = trigger - max(0.0, float(self._config.pre_window_s))
        end = trigger + max(0.0, float(self._config.post_window_s))
        out: list[_CandidateFrame] = []
        for role in self._config.roles:
            frames = self._ring_frames_for_role(role)
            selected = [
                frame
                for frame in frames
                if start <= float(getattr(frame, "timestamp", 0.0) or 0.0) <= end
            ]
            if not selected:
                # Timestamp clocks can be slightly skewed during startup. Keep
                # the best backward-looking fallback rather than losing the shot.
                selected = [
                    frame
                    for frame in frames
                    if float(getattr(frame, "timestamp", 0.0) or 0.0) <= trigger
                ][-self._config.max_frames_per_role :]
            selected = self._even_sample(selected, self._config.max_frames_per_role)
            for frame in selected:
                raw = getattr(frame, "raw", None)
                ts = float(getattr(frame, "timestamp", 0.0) or 0.0)
                if not isinstance(raw, np.ndarray) or raw.size == 0 or ts <= 0.0:
                    continue
                out.append(_CandidateFrame(role=role, captured_ts=ts, raw=raw))
        out.sort(key=lambda frame: (frame.captured_ts, frame.role))
        return out

    def _ring_frames_for_role(self, role: str) -> list[Any]:
        service = self._camera_service
        getter = getattr(service, "get_capture_thread_for_role", None)
        capture = None
        if callable(getter):
            try:
                capture = getter(role)
            except Exception:
                self._logger.debug("matrix_shot: capture lookup raised for role=%s", role, exc_info=True)
                capture = None
        if capture is None:
            feed_getter = getattr(service, "get_feed", None)
            feed = feed_getter(role) if callable(feed_getter) else None
            device = getattr(feed, "device", None) if feed is not None else None
            capture = getattr(device, "capture_thread", None) if device is not None else None
        drain = getattr(capture, "drain_ring_buffer", None)
        if not callable(drain):
            return []
        try:
            frames = drain(int(self._config.ring_read_frames))
        except Exception:
            self._logger.debug("matrix_shot: ring drain raised for role=%s", role, exc_info=True)
            return []
        return list(frames) if isinstance(frames, (list, tuple)) else []

    @staticmethod
    def _even_sample(frames: list[Any], limit: int) -> list[Any]:
        if limit <= 0 or len(frames) <= limit:
            return frames
        if limit == 1:
            return [frames[-1]]
        max_index = len(frames) - 1
        indices = sorted({
            min(max_index, max(0, int(round(i * max_index / (limit - 1)))))
            for i in range(limit)
        })
        return [frames[i] for i in indices]

    def _persist_frames(
        self,
        *,
        piece_uuid: str,
        candidates: list[_CandidateFrame],
        trigger: float,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for idx, candidate in enumerate(candidates):
            encoded, width, height = self._encode(candidate.raw)
            if encoded is None:
                continue
            rel_path = write_piece_crop(
                piece_uuid=piece_uuid,
                sequence=_SEGMENT_SEQUENCE,
                kind=_CROP_KIND,
                idx=idx,
                jpeg_bytes=encoded,
            )
            if rel_path is None:
                continue
            out.append(
                {
                    "role": candidate.role,
                    "captured_ts": candidate.captured_ts,
                    "relative_ms": int(round((candidate.captured_ts - trigger) * 1000.0)),
                    "jpeg_path": str(Path(rel_path)),
                    "width": width,
                    "height": height,
                }
            )
        return out

    def _encode(self, raw: np.ndarray) -> tuple[bytes | None, int, int]:
        frame = np.ascontiguousarray(raw)
        height, width = int(frame.shape[0]), int(frame.shape[1])
        max_width = int(self._config.max_width_px)
        if max_width > 0 and width > max_width:
            scale = max_width / float(width)
            width = max_width
            height = max(1, int(math.floor(height * scale)))
            frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, int(self._config.jpeg_quality)],
        )
        if not ok:
            return None, width, height
        return encoded.tobytes(), width, height


def install(
    bus: EventBus,
    camera_service: Any,
    *,
    logger: logging.Logger | None = None,
    config: MatrixShotConfig | None = None,
) -> MatrixShotRecorder:
    recorder = MatrixShotRecorder(camera_service, config=config, logger=logger)

    def _on_piece_registered(event: Event) -> None:
        payload = event.payload or {}
        piece_uuid = payload.get("piece_uuid") or payload.get("uuid")
        if not isinstance(piece_uuid, str) or not piece_uuid.strip():
            return
        recorder.enqueue(piece_uuid=piece_uuid, trigger_wall_ts=time.time())

    bus.subscribe(PIECE_REGISTERED, _on_piece_registered)
    return recorder


__all__ = ["MatrixShotConfig", "MatrixShotRecorder", "install"]
