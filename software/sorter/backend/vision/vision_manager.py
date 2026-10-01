import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from global_config import GlobalConfig
from irl.config import CameraPictureSettings
from .camera import CaptureThread
from .camera_service import CameraService
from .overlays.telemetry import TelemetryOverlay
from .types import CameraFrame


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

        # A folder of recordings per run under the backend's blob dir, named
        # for the run's start time.
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._run_dir = Path(__file__).parent.parent / "blob" / timestamp
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


class VisionManager:
    def __init__(self, gc: GlobalConfig, camera_service: CameraService):
        self.gc = gc
        self._camera_service = camera_service
        self._video_recorder = VideoRecorder() if gc.should_write_camera_feeds else None

    def start(self) -> None:
        for role, feed in self._camera_service.feeds.items():
            def statsForCamera(camera_role=role):
                capture = self.getCaptureThreadForRole(camera_role)
                return capture.getTelemetrySnapshot() if capture is not None else None

            feed.clear_overlays()
            feed.add_overlay(TelemetryOverlay(statsForCamera))

    def stop(self) -> None:
        if self._video_recorder:
            self._video_recorder.close()

    def reloadPolygons(self) -> None:
        perception = self.gc.perception_service
        if perception is not None:
            perception.request_reconcile()

    def recordFrames(self) -> None:
        if self._video_recorder is None:
            return
        for camera in self._camera_service.active_cameras:
            frame = self.getFrame(camera.value)
            if frame is not None:
                self._video_recorder.writeFrame(camera.value, frame.raw, frame.annotated)

    def getCaptureThreadForRole(self, camera_name: str) -> Optional[CaptureThread]:
        return self._camera_service.get_capture_thread_for_role(camera_name)

    def setCameraSourceForRole(
        self,
        camera_name: str,
        source: int | str | None,
    ) -> bool:
        return self._camera_service.set_camera_source_for_role(camera_name, source)

    def setPictureSettingsForRole(
        self,
        camera_name: str,
        settings: CameraPictureSettings,
    ) -> bool:
        return self._camera_service.set_picture_settings_for_role(camera_name, settings)

    def setDeviceSettingsForRole(
        self,
        camera_name: str,
        settings: dict[str, int | float | bool] | None,
        *,
        persist: bool = False,
    ) -> dict[str, int | float | bool] | None:
        return self._camera_service.set_device_settings_for_role(camera_name, settings, persist=persist)

    def getFrame(self, camera_name: str) -> Optional[CameraFrame]:
        feed = self._camera_service.get_feed(camera_name)
        return feed.get_frame(annotated=True) if feed else None
