import json
import os
import queue
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import cv2
import numpy as np

DATA_FILE = Path(__file__).parent / "data.json"
_DATA_LOCK = threading.Lock()
BLOB_DIR = Path(__file__).parent / "blob"


def _writeJsonAtomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def loadData() -> dict[str, Any]:
    if not DATA_FILE.exists():
        return {}
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def saveData(data: dict[str, Any]) -> None:
    _writeJsonAtomic(DATA_FILE, data)


def getMachineId() -> str:
    with _DATA_LOCK:
        data = loadData()
        if "machine_id" in data:
            return data["machine_id"]

        machine_id = str(uuid.uuid4())
        data["machine_id"] = machine_id
        saveData(data)
        return machine_id


def getMachineNickname() -> str | None:
    data = loadData()
    nickname = data.get("machine_nickname")
    if not isinstance(nickname, str):
        return None
    nickname = nickname.strip()
    return nickname or None


def setMachineNickname(nickname: str | None) -> None:
    with _DATA_LOCK:
        data = loadData()
        normalized = nickname.strip() if isinstance(nickname, str) else ""
        if normalized:
            data["machine_nickname"] = normalized
        else:
            data.pop("machine_nickname", None)
        saveData(data)


def getStepperPosition(name: str) -> int:
    data = loadData()
    return data.get("stepper_positions", {}).get(name, 0)


def setStepperPosition(name: str, position_steps: int) -> None:
    with _DATA_LOCK:
        data = loadData()
        if "stepper_positions" not in data:
            data["stepper_positions"] = {}
        data["stepper_positions"][name] = position_steps
        saveData(data)


def getServoPosition(name: str) -> int:
    data = loadData()
    return data.get("servo_positions", {}).get(name, 0)


def setServoPosition(name: str, angle: int) -> None:
    with _DATA_LOCK:
        data = loadData()
        if "servo_positions" not in data:
            data["servo_positions"] = {}
        data["servo_positions"][name] = angle
        saveData(data)


def getBinCategories() -> list[list[list[list[str]]]] | None:
    data = loadData()
    return data.get("bin_categories")


def setBinCategories(categories: list[list[list[list[str]]]]) -> None:
    with _DATA_LOCK:
        data = loadData()
        data["bin_categories"] = categories
        saveData(data)


def getMcuPath() -> str | None:
    data = loadData()
    return data.get("mcu_path")


def setMcuPath(path: str) -> None:
    with _DATA_LOCK:
        data = loadData()
        data["mcu_path"] = path
        saveData(data)


def getCameraSetup() -> dict | None:
    data = loadData()
    return data.get("camera_setup")


def setCameraSetup(setup: dict) -> None:
    with _DATA_LOCK:
        data = loadData()
        data["camera_setup"] = setup
        saveData(data)


def getChannelPolygons() -> dict | None:
    data = loadData()
    return data.get("channel_polygons")


def setChannelPolygons(polygons: dict) -> None:
    with _DATA_LOCK:
        data = loadData()
        data["channel_polygons"] = polygons
        saveData(data)


def getChuteCalibration() -> dict[str, float] | None:
    data = loadData()
    return data.get("chute_calibration")


def setChuteCalibration(calibration: dict[str, float]) -> None:
    with _DATA_LOCK:
        data = loadData()
        data["chute_calibration"] = calibration
        saveData(data)


def getClassificationPolygons() -> dict | None:
    data = loadData()
    return data.get("classification_polygons")


def setClassificationPolygons(polygons: dict) -> None:
    with _DATA_LOCK:
        data = loadData()
        data["classification_polygons"] = polygons
        saveData(data)


def getClassificationDetectionConfig() -> dict | None:
    data = loadData()
    return data.get("classification_detection")


def setClassificationDetectionConfig(config: dict) -> None:
    with _DATA_LOCK:
        data = loadData()
        data["classification_detection"] = config
        saveData(data)


def getFeederDetectionConfig() -> dict | None:
    data = loadData()
    return data.get("feeder_detection")


def setFeederDetectionConfig(config: dict) -> None:
    with _DATA_LOCK:
        data = loadData()
        data["feeder_detection"] = config
        saveData(data)


def getCarouselDetectionConfig() -> dict | None:
    data = loadData()
    return data.get("carousel_detection")


def setCarouselDetectionConfig(config: dict) -> None:
    with _DATA_LOCK:
        data = loadData()
        data["carousel_detection"] = config
        saveData(data)


def getClassificationTrainingConfig() -> dict | None:
    data = loadData()
    return data.get("classification_training")


def setClassificationTrainingConfig(config: dict) -> None:
    with _DATA_LOCK:
        data = loadData()
        data["classification_training"] = config
        saveData(data)


def getApiKeys() -> dict:
    data = loadData()
    return data.get("api_keys", {})


def setApiKeys(keys: dict) -> None:
    with _DATA_LOCK:
        data = loadData()
        data["api_keys"] = keys
        saveData(data)


CAMERA_NAMES = ["feeder", "classification_bottom", "classification_top"]


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
