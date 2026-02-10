import uuid
import time
import threading
import json
import cv2
import numpy as np
import requests
from typing import Optional, Dict

from global_config import GlobalConfig


class Telemetry:
    def __init__(self, gc: GlobalConfig):
        self.gc = gc

    def saveCapture(
        self,
        camera_name: str,
        raw_img,
        annotated_img,
        source: str,
        segmentation_map: Optional[np.ndarray] = None,
    ) -> None:
        if not self.gc.telemetry_enabled:
            return

        seg_copy = segmentation_map.copy() if segmentation_map is not None else None
        thread = threading.Thread(
            target=self._uploadCapture,
            args=(camera_name, raw_img.copy(), annotated_img.copy(), source, seg_copy),
            daemon=True,
        )
        thread.start()

    def _uploadCapture(
        self,
        camera_name: str,
        raw_img,
        annotated_img,
        source: str,
        segmentation_map: Optional[np.ndarray],
    ) -> None:
        capture_id = str(uuid.uuid4())
        timestamp = str(int(time.time() * 1000))
        base_name = f"{self.gc.machine_id}_{self.gc.run_id}_{camera_name}_{timestamp}"
        raw_name = f"{base_name}_raw.jpg"
        annotated_name = f"{base_name}_annotated.jpg"

        _, raw_buf = cv2.imencode(".jpg", raw_img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        _, ann_buf = cv2.imencode(".jpg", annotated_img, [cv2.IMWRITE_JPEG_QUALITY, 80])

        files: Dict[str, tuple[str, bytes, str]] = {
            "raw_img": (raw_name, raw_buf.tobytes(), "image/jpeg"),
            "annotated_img": (annotated_name, ann_buf.tobytes(), "image/jpeg"),
        }

        if segmentation_map is not None:
            seg_name = f"{base_name}_segmentation.json"
            seg_bytes = json.dumps(segmentation_map.tolist()).encode("utf-8")
            files["segmentation_data"] = (seg_name, seg_bytes, "application/json")

        data = {
            "id": capture_id,
            "machine_id": self.gc.machine_id,
            "run_id": self.gc.run_id,
            "camera_name": camera_name,
            "source": source,
        }

        try:
            url = f"{self.gc.telemetry_url.rstrip('/')}/captures"
            requests.post(url, data=data, files=files, timeout=30)
        except Exception as e:
            self.gc.logger.error(f"telemetry upload failed: {e}")
