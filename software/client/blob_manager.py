import json
import os
import tempfile
import threading
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
    _fps: int

    def __init__(self, fps: int = 30):
        self._fps = fps
        self._writers = {}

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._run_dir = BLOB_DIR / timestamp
        self._run_dir.mkdir(parents=True, exist_ok=True)

    def _getWriter(self, key: str, frame: np.ndarray) -> cv2.VideoWriter:
        if key not in self._writers:
            h, w = frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            path = self._run_dir / f"{key}.mp4"
            self._writers[key] = cv2.VideoWriter(str(path), fourcc, self._fps, (w, h))
        return self._writers[key]

    def writeFrame(
        self, camera: str, raw: Optional[np.ndarray], annotated: Optional[np.ndarray]
    ) -> None:
        if raw is not None:
            writer = self._getWriter(f"{camera}_raw", raw)
            writer.write(raw)

        if annotated is not None:
            writer = self._getWriter(f"{camera}_annotated", annotated)
            writer.write(annotated)

    def close(self) -> None:
        for writer in self._writers.values():
            writer.release()
        self._writers.clear()
