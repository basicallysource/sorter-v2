import threading
import time
from typing import Optional, List, Tuple
import numpy as np
from ultralytics import YOLO
import cv2

from .camera import CaptureThread
from .types import VisionResult, CameraFrame


class CameraModelBinding:
    camera: CaptureThread
    model: Optional[YOLO]
    latest_result: Optional[VisionResult]
    latest_annotated_frame: Optional[CameraFrame]
    latest_raw_results: Optional[List]
    last_processed_timestamp: float
    exclude_classes_from_plot: List[int]

    def __init__(
        self,
        camera: CaptureThread,
        model_path: Optional[str],
        exclude_classes_from_plot: Optional[List[int]] = None,
    ):
        self.camera = camera
        self.model = YOLO(model_path) if model_path else None
        self.latest_result = None
        self.latest_annotated_frame = None
        self.latest_raw_results = None
        self.last_processed_timestamp = 0.0
        self.exclude_classes_from_plot = exclude_classes_from_plot or []


class InferenceThread:
    _thread: Optional[threading.Thread]
    _stop_event: threading.Event
    _bindings: List[CameraModelBinding]

    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._bindings = []

    def addBinding(
        self,
        camera: CaptureThread,
        model_path: Optional[str],
        exclude_classes_from_plot: Optional[List[int]] = None,
    ) -> CameraModelBinding:
        binding = CameraModelBinding(camera, model_path, exclude_classes_from_plot)
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

                results = binding.model.track(frame.raw, verbose=False, persist=False)

                vision_results: List[VisionResult] = []
                annotated = frame.raw.copy()
                segmentation_map = None

                if len(results) > 0 and len(results[0].boxes) > 0:
                    for box in results[0].boxes:
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
                        vision_results.append(
                            VisionResult(
                                class_id=class_id,
                                class_name=class_name,
                                confidence=confidence,
                                bbox=bbox,
                                timestamp=frame.timestamp,
                            )
                        )

                    if binding.exclude_classes_from_plot:
                        annotated = results[0].plot(
                            labels=False, boxes=False, masks=False, probs=False
                        )
                        # manually draw only non-excluded classes
                        for i, box in enumerate(results[0].boxes):
                            class_id = int(box.cls[0])
                            if class_id in binding.exclude_classes_from_plot:
                                continue
                            confidence = float(box.conf[0])
                            xyxy = list(map(int, box.xyxy[0].tolist()))
                            class_name = binding.model.names.get(
                                class_id, str(class_id)
                            )

                            # choose color based on class: carousel (2) = red, object (0) = green
                            color = (0, 0, 255) if class_id == 2 else (0, 255, 0)

                            # draw bounding box
                            cv2.rectangle(
                                annotated,
                                (xyxy[0], xyxy[1]),
                                (xyxy[2], xyxy[3]),
                                color,
                                2,
                            )
                            # draw label
                            label = f"{class_name} {confidence:.2f}"
                            cv2.putText(
                                annotated,
                                label,
                                (xyxy[0], xyxy[1] - 10),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.5,
                                color,
                                2,
                            )
                            # draw mask if available
                            if results[0].masks is not None and i < len(
                                results[0].masks
                            ):
                                mask_data = results[0].masks[i].data[0].cpu().numpy()
                                mh, mw = mask_data.shape
                                h, w = frame.raw.shape[:2]
                                if mh != h or mw != w:
                                    mask_data = cv2.resize(
                                        mask_data,
                                        (w, h),
                                        interpolation=cv2.INTER_NEAREST,
                                    )
                                mask_data = (mask_data > 0).astype(np.uint8)
                                color_mask = np.zeros_like(annotated)
                                color_mask[mask_data == 1] = color
                                annotated = cv2.addWeighted(
                                    annotated, 1.0, color_mask, 0.4, 0
                                )
                    else:
                        annotated = results[0].plot()

                    if results[0].masks is not None:
                        h, w = frame.raw.shape[:2]
                        segmentation_map = np.zeros((h, w), dtype=np.int32)
                        for i, mask in enumerate(results[0].masks):
                            cls = int(results[0].boxes[i].cls[0])
                            mask_data = mask.data[0].cpu().numpy()
                            mh, mw = mask_data.shape
                            if mh != h or mw != w:
                                mask_data = cv2.resize(
                                    mask_data.astype(np.uint8),
                                    (w, h),
                                    interpolation=cv2.INTER_NEAREST,
                                )
                            segmentation_map[mask_data > 0] = cls

                binding.latest_result = vision_results[0] if vision_results else None
                binding.latest_raw_results = results
                binding.latest_annotated_frame = CameraFrame(
                    raw=frame.raw,
                    annotated=annotated,
                    results=vision_results,
                    timestamp=frame.timestamp,
                    segmentation_map=segmentation_map,
                )

            if not processed_any:
                time.sleep(0.01)
