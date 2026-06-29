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

from config_paths import CONFIG_DIR

DATA_FILE = CONFIG_DIR / "data.json"
_DATA_LOCK = threading.Lock()
BLOB_DIR = CONFIG_DIR / "blob"


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
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


def load_data() -> dict[str, Any]:
    if not DATA_FILE.exists():
        return {}
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_data(data: dict[str, Any]) -> None:
    _write_json_atomic(DATA_FILE, data)


def get_machine_id() -> str:
    with _DATA_LOCK:
        data = load_data()
        if "machine_id" in data:
            return data["machine_id"]

        machine_id = str(uuid.uuid4())
        data["machine_id"] = machine_id
        save_data(data)
        return machine_id


def get_stepper_position(name: str) -> int:
    data = load_data()
    return data.get("stepper_positions", {}).get(name, 0)


def set_stepper_position(name: str, position_steps: int) -> None:
    with _DATA_LOCK:
        data = load_data()
        if "stepper_positions" not in data:
            data["stepper_positions"] = {}
        data["stepper_positions"][name] = position_steps
        save_data(data)


def get_servo_position(name: str) -> int:
    data = load_data()
    return data.get("servo_positions", {}).get(name, 0)


def set_servo_position(name: str, angle: int) -> None:
    with _DATA_LOCK:
        data = load_data()
        if "servo_positions" not in data:
            data["servo_positions"] = {}
        data["servo_positions"][name] = angle
        save_data(data)


def get_bin_categories() -> list[list[list[str | None]]] | None:
    data = load_data()
    return data.get("bin_categories")


def set_bin_categories(categories: list[list[list[str | None]]]) -> None:
    with _DATA_LOCK:
        data = load_data()
        data["bin_categories"] = categories
        save_data(data)


def get_mcu_path() -> str | None:
    data = load_data()
    return data.get("mcu_path")


def set_mcu_path(path: str) -> None:
    with _DATA_LOCK:
        data = load_data()
        data["mcu_path"] = path
        save_data(data)


def get_camera_setup() -> dict | None:
    data = load_data()
    return data.get("camera_setup")


def set_camera_setup(setup: dict) -> None:
    with _DATA_LOCK:
        data = load_data()
        data["camera_setup"] = setup
        save_data(data)


def get_excluded_camera_indices() -> list[int]:
    data = load_data()
    return data.get("excluded_camera_indices", [])


def set_excluded_camera_indices(indices: list[int]) -> None:
    with _DATA_LOCK:
        data = load_data()
        data["excluded_camera_indices"] = sorted(set(indices))
        save_data(data)


def get_channel_polygons() -> dict | None:
    data = load_data()
    return data.get("channel_polygons")


def set_channel_polygons(polygons: dict) -> None:
    with _DATA_LOCK:
        data = load_data()
        data["channel_polygons"] = polygons
        save_data(data)


def get_chute_calibration() -> dict[str, float] | None:
    data = load_data()
    return data.get("chute_calibration")


def set_chute_calibration(calibration: dict[str, float]) -> None:
    with _DATA_LOCK:
        data = load_data()
        data["chute_calibration"] = calibration
        save_data(data)


def get_chute_wiggle_settings() -> dict:
    """Chute wiggle params used during baseline capture (persisted, with defaults)."""
    data = load_data()
    s = data.get("chute_wiggle") or {}
    return {"hz": float(s.get("hz", 5.0)), "steps": int(s.get("steps", 40))}


def set_chute_wiggle_settings(hz: float, steps: int) -> None:
    with _DATA_LOCK:
        data = load_data()
        data["chute_wiggle"] = {"hz": float(hz), "steps": int(steps)}
        save_data(data)


def get_classification_polygons() -> dict | None:
    data = load_data()
    return data.get("classification_polygons")


def set_classification_polygons(polygons: dict) -> None:
    with _DATA_LOCK:
        data = load_data()
        data["classification_polygons"] = polygons
        save_data(data)


UNMAPPED_PARTS_FILE = CONFIG_DIR / "unmapped_parts.json"
_UNMAPPED_LOCK = threading.Lock()


def get_unmapped_part_ids() -> set[str]:
    if not UNMAPPED_PARTS_FILE.exists():
        return set()
    try:
        with open(UNMAPPED_PARTS_FILE, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()


def add_unmapped_part_id(part_id: str) -> None:
    with _UNMAPPED_LOCK:
        ids = get_unmapped_part_ids()
        if part_id in ids:
            return
        ids.add(part_id)
        sorted_ids = sorted(ids)
        fd, tmp_path = tempfile.mkstemp(dir=UNMAPPED_PARTS_FILE.parent, suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(sorted_ids, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.rename(tmp_path, UNMAPPED_PARTS_FILE)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


CAMERA_NAMES = ["c_channel_2", "c_channel_3", "carousel", "classification"]


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

        self._thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._thread.start()

    def _get_writer(self, key: str, frame: np.ndarray) -> cv2.VideoWriter:
        if key not in self._writers:
            h, w = frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            path = self._run_dir / f"{key}.mp4"
            self._writers[key] = cv2.VideoWriter(str(path), fourcc, self._fps, (w, h))
        return self._writers[key]

    def _writer_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            key, frame, ts = item
            writer = self._get_writer(key, frame)

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

    def write_frame(
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
