import queue
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import cv2
import numpy as np

from role_aliases import auxiliary_detection_scope

BLOB_DIR = Path(__file__).parent / "blob"


def loadData() -> dict[str, Any]:
    data: dict[str, Any] = {}

    from local_state import get_machine_id

    machine_id = get_machine_id()
    if machine_id:
        data["machine_id"] = machine_id

    stepper_positions = getAllStepperPositions()
    if stepper_positions:
        data["stepper_positions"] = stepper_positions

    servo_positions = getAllServoPositions()
    if servo_positions:
        data["servo_positions"] = servo_positions

    camera_setup = getCameraSetup()
    if camera_setup is not None:
        data["camera_setup"] = camera_setup

    channel_polygons = getChannelPolygons()
    if channel_polygons is not None:
        data["channel_polygons"] = channel_polygons

    classification_polygons = getClassificationPolygons()
    if classification_polygons is not None:
        data["classification_polygons"] = classification_polygons

    machine_nickname = getMachineNickname()
    if machine_nickname is not None:
        data["machine_nickname"] = machine_nickname

    bin_categories = getBinCategories()
    if bin_categories is not None:
        data["bin_categories"] = bin_categories

    classification_detection = getClassificationDetectionConfig()
    if classification_detection is not None:
        data["classification_detection"] = classification_detection

    feeder_detection = getFeederDetectionConfig()
    if feeder_detection is not None:
        data["feeder_detection"] = feeder_detection

    carousel_detection = getCarouselDetectionConfig()
    if carousel_detection is not None:
        data["carousel_detection"] = carousel_detection

    classification_training = getClassificationTrainingConfig()
    if classification_training is not None:
        data["classification_training"] = classification_training

    sorting_profile_sync = getSortingProfileSyncState()
    if sorting_profile_sync is not None:
        data["sorting_profile_sync"] = sorting_profile_sync

    api_keys = getApiKeys()
    if api_keys:
        data["api_keys"] = api_keys

    hive = getHiveConfig()
    if hive is not None:
        data["hive"] = hive

    return data


def saveData(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError("data must be a dict")

    from local_state import set_machine_id, set_servo_positions, set_stepper_positions

    if "machine_id" in data and isinstance(data["machine_id"], str):
        set_machine_id(data["machine_id"])
    if "stepper_positions" in data:
        set_stepper_positions(data["stepper_positions"])
    if "servo_positions" in data:
        set_servo_positions(data["servo_positions"])
    if "bin_categories" in data and isinstance(data["bin_categories"], list):
        setBinCategories(data["bin_categories"])
    if "camera_setup" in data and isinstance(data["camera_setup"], dict):
        setCameraSetup(data["camera_setup"])
    if "channel_polygons" in data and isinstance(data["channel_polygons"], dict):
        setChannelPolygons(data["channel_polygons"])
    if "classification_polygons" in data and isinstance(data["classification_polygons"], dict):
        setClassificationPolygons(data["classification_polygons"])
    if "machine_nickname" in data:
        setMachineNickname(data["machine_nickname"])
    if "classification_detection" in data and isinstance(data["classification_detection"], dict):
        setClassificationDetectionConfig(data["classification_detection"])
    if "feeder_detection" in data and isinstance(data["feeder_detection"], dict):
        setFeederDetectionConfig(data["feeder_detection"])
    if "carousel_detection" in data and isinstance(data["carousel_detection"], dict):
        setCarouselDetectionConfig(data["carousel_detection"])
    if "classification_training" in data and isinstance(data["classification_training"], dict):
        setClassificationTrainingConfig(data["classification_training"])
    if "sorting_profile_sync" in data and isinstance(data["sorting_profile_sync"], dict):
        setSortingProfileSyncState(data["sorting_profile_sync"])
    if "api_keys" in data and isinstance(data["api_keys"], dict):
        setApiKeys(data["api_keys"])
    if "hive" in data and isinstance(data["hive"], dict):
        setHiveConfig(data["hive"])


def getMachineId() -> str:
    from local_state import get_machine_id, set_machine_id

    machine_id = get_machine_id()
    if machine_id is not None:
        return machine_id

    machine_id = str(uuid.uuid4())
    set_machine_id(machine_id)
    return machine_id


def getMachineNickname() -> str | None:
    from toml_config import getMachineNickname as _get
    return _get()


def setMachineNickname(nickname: str | None) -> None:
    from toml_config import setMachineNickname as _set
    _set(nickname)


def getStepperPosition(name: str) -> int:
    from local_state import get_stepper_positions

    return get_stepper_positions().get(name, 0)


def setStepperPosition(name: str, position_steps: int) -> None:
    from local_state import get_stepper_positions, set_stepper_positions

    positions = get_stepper_positions()
    positions[name] = position_steps
    set_stepper_positions(positions)


def getAllStepperPositions() -> dict[str, int]:
    from local_state import get_stepper_positions

    return get_stepper_positions()


def getServoPosition(name: str) -> int:
    from local_state import get_servo_positions

    return get_servo_positions().get(name, 0)


def setServoPosition(name: str, angle: int) -> None:
    from local_state import get_servo_positions, set_servo_positions

    positions = get_servo_positions()
    positions[name] = angle
    set_servo_positions(positions)


def getAllServoPositions() -> dict[str, int]:
    from local_state import get_servo_positions

    return get_servo_positions()


def getBinCategories() -> list[list[list[list[str]]]] | None:
    from local_state import get_bin_categories

    return get_bin_categories()


def setBinCategories(categories: list[list[list[list[str]]]]) -> None:
    from local_state import set_bin_categories

    set_bin_categories(categories)


def getCameraSetup() -> dict | None:
    from toml_config import getCameraSetup as _get
    return _get()


def setCameraSetup(setup: dict) -> None:
    from toml_config import setCameraSetup as _set
    _set(setup)


def getChannelPolygons() -> dict | None:
    from local_state import get_channel_polygons

    return get_channel_polygons()


def setChannelPolygons(polygons: dict) -> None:
    from local_state import set_channel_polygons

    set_channel_polygons(polygons)


def getChuteCalibration() -> dict[str, float] | None:
    from toml_config import getChuteCalibration as _get
    return _get()


def setChuteCalibration(calibration: dict[str, float]) -> None:
    from toml_config import setChuteCalibration as _set
    _set(calibration)


def getClassificationPolygons() -> dict | None:
    from local_state import get_classification_polygons

    return get_classification_polygons()


def setClassificationPolygons(polygons: dict) -> None:
    from local_state import set_classification_polygons

    set_classification_polygons(polygons)


def getClassificationDetectionConfig() -> dict | None:
    from toml_config import getDetectionConfig
    return getDetectionConfig("classification")


def setClassificationDetectionConfig(config: dict) -> None:
    from toml_config import setDetectionConfig
    setDetectionConfig("classification", config)


def getFeederDetectionConfig() -> dict | None:
    from toml_config import getDetectionConfig
    return getDetectionConfig("feeder")


def setFeederDetectionConfig(config: dict) -> None:
    from toml_config import setDetectionConfig
    setDetectionConfig("feeder", config)


def getCarouselDetectionConfig() -> dict | None:
    from toml_config import getDetectionConfig
    return getDetectionConfig(auxiliary_detection_scope(loadTomlConfig()))


def setCarouselDetectionConfig(config: dict) -> None:
    from toml_config import setDetectionConfig
    setDetectionConfig(auxiliary_detection_scope(loadTomlConfig()), config)


def getClassificationChannelDetectionConfig() -> dict | None:
    from toml_config import getDetectionConfig
    return getDetectionConfig("classification_channel")


def setClassificationChannelDetectionConfig(config: dict) -> None:
    from toml_config import setDetectionConfig
    setDetectionConfig("classification_channel", config)


def getClassificationTrainingConfig() -> dict | None:
    from local_state import get_classification_training_state

    return get_classification_training_state()


def setClassificationTrainingConfig(config: dict) -> None:
    from local_state import set_classification_training_state

    set_classification_training_state(config)


def getHiveConfig() -> dict | None:
    from local_state import get_hive_config

    return get_hive_config()


def setHiveConfig(config: dict) -> None:
    from local_state import set_hive_config

    set_hive_config(config)


def getSortingProfileSyncState() -> dict | None:
    from local_state import get_sorting_profile_sync_state

    return get_sorting_profile_sync_state()


def setSortingProfileSyncState(state: dict) -> None:
    from local_state import set_sorting_profile_sync_state

    set_sorting_profile_sync_state(state)


def getRecentKnownObjects() -> list[dict]:
    from local_state import get_recent_known_objects

    return get_recent_known_objects()


def rememberRecentKnownObject(obj: dict) -> None:
    from local_state import remember_recent_known_object

    remember_recent_known_object(obj)


def getApiKeys() -> dict:
    from local_state import get_api_keys

    return get_api_keys()


def setApiKeys(keys: dict) -> None:
    from local_state import set_api_keys

    set_api_keys(keys)


CAMERA_NAMES = ["feeder", "classification_bottom", "classification_top"]


def loadTomlConfig() -> dict[str, Any]:
    from toml_config import _read_toml

    return _read_toml()


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
