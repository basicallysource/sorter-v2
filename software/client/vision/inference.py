import threading
import time
from typing import Optional, List, Tuple
from ultralytics import YOLO

from .camera import CaptureThread
from .types import VisionResult, CameraFrame


class CameraModelBinding:
    camera: CaptureThread
    model: Optional[YOLO]
    latest_result: Optional[VisionResult]
    latest_annotated_frame: Optional[CameraFrame]
    last_processed_timestamp: float

    def __init__(self, camera: CaptureThread, model_path: Optional[str]):
        self.camera = camera
        self.model = YOLO(model_path) if model_path else None
        self.latest_result = None
        self.latest_annotated_frame = None
        self.last_processed_timestamp = 0.0


class InferenceThread:
    _thread: Optional[threading.Thread]
    _stop_event: threading.Event
    _bindings: List[CameraModelBinding]

    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._bindings = []

    def addBinding(
        self, camera: CaptureThread, model_path: Optional[str]
    ) -> CameraModelBinding:
        binding = CameraModelBinding(camera, model_path)
        self._bindings.append(binding)
        return binding

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._inferenceLoop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def _inferenceLoop(self) -> None:
        while not self._stop_event.is_set():
            processed_any = False

            for binding in self._bindings:
                if binding.model is None:
                    continue

                frame = binding.camera.latest_frame
                if frame is None:
                    continue

                if frame.timestamp <= binding.last_processed_timestamp:
                    continue

                processed_any = True
                binding.last_processed_timestamp = frame.timestamp

                results = binding.model(frame.raw, verbose=False)

                result = None
                annotated = frame.raw.copy()

                if len(results) > 0 and len(results[0].boxes) > 0:
                    box = results[0].boxes[0]
                    class_id = int(box.cls[0])
                    confidence = float(box.conf[0])
                    xyxy = list(map(int, box.xyxy[0].tolist()))
                    bbox: Tuple[int, int, int, int] = (
                        xyxy[0],
                        xyxy[1],
                        xyxy[2],
                        xyxy[3],
                    )
                    class_name = binding.model.names.get(class_id, str(class_id))

                    result = VisionResult(
                        class_id=class_id,
                        class_name=class_name,
                        confidence=confidence,
                        bbox=bbox,
                        timestamp=frame.timestamp,
                    )

                    annotated = results[0].plot()

                binding.latest_result = result
                binding.latest_annotated_frame = CameraFrame(
                    raw=frame.raw,
                    annotated=annotated,
                    result=result,
                    timestamp=frame.timestamp,
                )

            if not processed_any:
                time.sleep(0.01)
