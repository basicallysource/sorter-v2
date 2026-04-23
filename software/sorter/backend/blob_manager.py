"""Disk IO for piece-crop JPEGs plus the runtime video recorder.

Everything else that used to live here — pure forwarders to
``local_state`` / ``toml_config`` and the dead ``loadData`` / ``saveData``
migration helpers — is gone. Callers now import the state accessors
directly from their real home, and detection-config adapters live in
``server/detection_config/common.py``.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

BLOB_DIR = Path(__file__).parent / "blob"
PIECE_CROPS_DIR_NAME = "piece_crops"
PIECE_CROP_KINDS: frozenset[str] = frozenset({"wedge", "piece", "snapshot", "matrix"})

_logger = logging.getLogger(__name__)


def piece_crops_dir(piece_uuid: str) -> Path:
    """Return (and lazily create) the on-disk directory for a piece's crops.

    Layout: ``BLOB_DIR/piece_crops/<piece_uuid>/``. Parent directories are
    created on demand — the sorter may persist to a fresh machine where
    ``BLOB_DIR`` hasn't been touched yet.
    """
    target = BLOB_DIR / PIECE_CROPS_DIR_NAME / str(piece_uuid)
    target.mkdir(parents=True, exist_ok=True)
    return target


def write_piece_crop(
    piece_uuid: str,
    sequence: int,
    kind: str,
    idx: int,
    jpeg_bytes: bytes,
) -> Optional[Path]:
    """Persist a single piece-crop JPEG to disk, best-effort.

    Layout: ``BLOB_DIR/piece_crops/<piece_uuid>/seg<sequence>/<kind>_<idx>.jpg``
    where ``kind`` is one of ``wedge`` / ``piece`` / ``snapshot`` / ``matrix``.

    Returns the **relative** path (relative to :data:`BLOB_DIR`) on success
    so callers can store it in SQLite without baking in an absolute
    filesystem location. On any :class:`OSError` (disk full, permission
    denied, …) the error is logged and ``None`` is returned — segment
    archival must never take the tracker thread with it.
    """
    if not isinstance(piece_uuid, str) or not piece_uuid.strip():
        return None
    if not isinstance(kind, str) or kind not in PIECE_CROP_KINDS:
        _logger.warning("write_piece_crop: refusing unknown kind=%r", kind)
        return None
    try:
        sequence_int = int(sequence)
        idx_int = int(idx)
    except (TypeError, ValueError):
        _logger.warning(
            "write_piece_crop: invalid sequence/idx sequence=%r idx=%r",
            sequence,
            idx,
        )
        return None
    if not isinstance(jpeg_bytes, (bytes, bytearray)) or not jpeg_bytes:
        return None
    try:
        segment_dir = piece_crops_dir(piece_uuid) / f"seg{sequence_int}"
        segment_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{kind}_{idx_int:03d}.jpg"
        abs_path = segment_dir / filename
        tmp_path = abs_path.with_suffix(".jpg.tmp")
        tmp_path.write_bytes(bytes(jpeg_bytes))
        tmp_path.replace(abs_path)
    except OSError as exc:
        _logger.warning(
            "write_piece_crop: failed for uuid=%s seg=%s kind=%s idx=%s: %s",
            piece_uuid,
            sequence,
            kind,
            idx,
            exc,
        )
        return None
    try:
        return abs_path.relative_to(BLOB_DIR)
    except ValueError:
        return abs_path


class VideoRecorder:
    _run_dir: Path
    _writers: dict[str, cv2.VideoWriter]
    _fps: int
    _queue: queue.Queue[tuple[str, np.ndarray, float] | None]
    _thread: threading.Thread
    _start_times: dict[str, float]
    _frame_counts: dict[str, int]

    def __init__(self, fps: int = 10):
        self._fps = fps
        self._writers = {}
        self._queue = queue.Queue(maxsize=120)
        self._start_times = {}
        self._frame_counts = {}
        self._last_frames: dict[str, np.ndarray] = {}

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._run_dir = BLOB_DIR / timestamp
        self._run_dir.mkdir(parents=True, exist_ok=True)

        self._thread = threading.Thread(target=self._writerLoop, daemon=True)
        self._thread.start()

    def _getWriter(self, key: str, frame: np.ndarray) -> cv2.VideoWriter:
        if key not in self._writers:
            h, w = frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            path = self._run_dir / f"{key}.mp4"
            self._writers[key] = cv2.VideoWriter(str(path), fourcc, self._fps, (w, h))
        return self._writers[key]

    def _writerLoop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            key, frame, ts = item
            writer = self._getWriter(key, frame)

            if key not in self._start_times:
                self._start_times[key] = ts
                self._frame_counts[key] = 0

            elapsed = ts - self._start_times[key]
            target_frame = int(elapsed * self._fps)
            current_count = self._frame_counts[key]

            gap = target_frame - current_count
            if gap > 1:
                fill = self._last_frames.get(key)
                if fill is not None:
                    for _ in range(min(gap - 1, self._fps * 2)):
                        writer.write(fill)
                        self._frame_counts[key] += 1

            writer.write(frame)
            self._frame_counts[key] += 1
            self._last_frames[key] = frame

    def writeFrame(
        self, camera: str, raw: Optional[np.ndarray], annotated: Optional[np.ndarray]
    ) -> None:
        ts = time.time()
        if raw is not None:
            try:
                self._queue.put_nowait((f"{camera}_raw", raw.copy(), ts))
            except queue.Full:
                pass
        if annotated is not None:
            try:
                self._queue.put_nowait((f"{camera}_annotated", annotated.copy(), ts))
            except queue.Full:
                pass

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=10.0)
        for writer in self._writers.values():
            writer.release()
        self._writers.clear()
