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


def getBinCategories() -> list[list[list[str | None]]] | None:
    data = loadData()
    return data.get("bin_categories")


def setBinCategories(categories: list[list[list[str | None]]]) -> None:
    with _DATA_LOCK:
        data = loadData()
        data["bin_categories"] = categories
        saveData(data)


def getChannelPolygons() -> dict | None:
    data = loadData()
    return data.get("channel_polygons")


def setChannelPolygons(polygons: dict) -> None:
    with _DATA_LOCK:
        data = loadData()
        data["channel_polygons"] = polygons
        saveData(data)


def getClassificationPolygons() -> dict | None:
    data = loadData()
    return data.get("classification_polygons")


def setClassificationPolygons(polygons: dict) -> None:
    with _DATA_LOCK:
        data = loadData()
        data["classification_polygons"] = polygons
        saveData(data)


def getCarouselPolygon() -> list | None:
    saved = getChannelPolygons()
    if saved is None:
        return None
    return saved.get("polygons", {}).get("carousel")


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


RECORDS_FILE = BLOB_DIR / "records.json"
_RECORDS_LOCK = threading.Lock()


def loadRecords() -> dict[str, Any]:
    if not RECORDS_FILE.exists():
        return {"runs": {}}
    try:
        with open(RECORDS_FILE, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"runs": {}}
        if "runs" not in data or not isinstance(data["runs"], dict):
            data["runs"] = {}
        return data
    except Exception:
        return {"runs": {}}


def saveRecords(data: dict[str, Any]) -> None:
    _writeJsonAtomic(RECORDS_FILE, data)


def appendKnownObjectRecord(
    machine_id: str, run_id: str, known_object: dict[str, Any]
) -> None:
    with _RECORDS_LOCK:
        data = loadRecords()
        data["machine_id"] = machine_id

        runs = data.setdefault("runs", {})
        run_record = runs.setdefault(
            run_id,
            {
                "run_id": run_id,
                "known_objects": {},
            },
        )

        known_objects = run_record.setdefault("known_objects", {})
        obj_id = known_object["uuid"]
        obj_record = known_objects.setdefault(
            obj_id,
            {
                "id": obj_id,
                "created_at": known_object.get("created_at"),
                "classification_successful": None,
                "events": [],
            },
        )

        obj_record["id"] = obj_id
        obj_record["created_at"] = known_object.get(
            "created_at", obj_record.get("created_at")
        )
        obj_record["updated_at"] = known_object.get("updated_at")
        obj_record["stage"] = known_object.get("stage")
        obj_record["classification_status"] = known_object.get("classification_status")
        obj_record["category_id"] = known_object.get("category_id")
        obj_record["destination_bin"] = known_object.get("destination_bin")

        if (
            known_object.get("category_id") is not None
            and obj_record.get("category_assigned_at") is None
        ):
            obj_record["category_assigned_at"] = known_object.get("updated_at")

        classification_status = known_object.get("classification_status")
        if classification_status in ("classified", "unknown", "not_found"):
            if obj_record.get("classification_completed_at") is None:
                obj_record["classification_completed_at"] = known_object.get("updated_at")
            success = classification_status == "classified"
            obj_record["classification_successful"] = success
            obj_record["classification"] = {
                "status": classification_status,
                "part_id": known_object.get("part_id"),
                "confidence": known_object.get("confidence"),
            }
            if success:
                obj_record["classified_at"] = known_object.get("updated_at")

        if known_object.get("stage") == "distributed":
            obj_record["distributed_at"] = known_object.get("updated_at")

        obj_record["events"].append(
            {
                "timestamp": known_object.get("updated_at"),
                "stage": known_object.get("stage"),
                "classification_status": classification_status,
                "part_id": known_object.get("part_id"),
                "confidence": known_object.get("confidence"),
                "category_id": known_object.get("category_id"),
                "destination_bin": known_object.get("destination_bin"),
            }
        )

        run_record["updated_at"] = known_object.get("updated_at")
        if run_record.get("started_at") is None:
            run_record["started_at"] = known_object.get("created_at") or known_object.get(
                "updated_at"
            )

        saveRecords(data)


CAMERA_NAMES = ["feeder", "classification_bottom", "classification_top"]


class VideoRecorder:
    _run_dir: Path
    _writers: dict[str, cv2.VideoWriter]
    _last_write: dict[str, float]
    _last_frame: dict[str, np.ndarray]
    _fps: int
    _queue: queue.Queue
    _thread: threading.Thread
    _stopped: bool

    def __init__(self, run_id: str, fps: int = 30):
        self._fps = fps
        self._writers = {}
        self._last_write = {}
        self._last_frame = {}
        self._queue = queue.Queue()
        self._stopped = False

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._run_dir = BLOB_DIR / f"{timestamp}-{run_id}"
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

    def _processFrame(self, key: str, frame: np.ndarray, t: float) -> None:
        writer = self._getWriter(key, frame)
        frame_duration = 1.0 / self._fps

        if key in self._last_write:
            elapsed = t - self._last_write[key]
            gap_frames = int(elapsed / frame_duration) - 1
            if gap_frames > 0 and key in self._last_frame:
                for _ in range(gap_frames):
                    writer.write(self._last_frame[key])

        writer.write(frame)
        self._last_write[key] = t
        self._last_frame[key] = frame

    def _writerLoop(self) -> None:
        while not self._stopped:
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            key, frame, t = item
            self._processFrame(key, frame, t)

    def writeFrame(
        self, camera: str, raw: Optional[np.ndarray], annotated: Optional[np.ndarray]
    ) -> None:
        t = time.monotonic()
        if raw is not None:
            self._queue.put((f"{camera}_raw", raw, t))
        if annotated is not None:
            self._queue.put((f"{camera}_annotated", annotated, t))

    def close(self) -> None:
        self._stopped = True
        self._thread.join(timeout=5.0)
        while not self._queue.empty():
            try:
                key, frame, t = self._queue.get_nowait()
                self._processFrame(key, frame, t)
            except queue.Empty:
                break
        for writer in self._writers.values():
            writer.release()
        self._writers.clear()
        self._last_write.clear()
        self._last_frame.clear()
