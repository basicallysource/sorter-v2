"""Web-driven polygon editor (replaces scripts/polygon_editor.py).

Draws the feeder channel regions (second / third / carousel) and the single classification
region over live camera frames. The canvas UI lives in the SvelteKit app; this session owns
the camera capture threads and persists polygons via blob_manager.

Channel -> camera mapping for this machine (no single feeder camera, one classification cam):
    second  -> c_channel_2
    third   -> c_channel_3
    carousel-> carousel (dedicated) else c_channel_3
    classification -> classification
"""

from __future__ import annotations

import threading
from typing import Any, Optional

import cv2

from blob_manager import (
    get_channel_polygons,
    set_channel_polygons,
    get_classification_polygons,
    set_classification_polygons,
)
from hardware.camera_resolver import resolve_camera_setup
from irl.config import make_camera_config
from vision.camera import CaptureThread

FEEDER_CHANNELS = ["second", "third", "carousel"]
CLASSIFICATION_CHANNEL = "classification"
ALL_CHANNELS = FEEDER_CHANNELS + [CLASSIFICATION_CHANNEL]


class PolygonSession:
    def __init__(self, gc):
        self.gc = gc
        self._lock = threading.Lock()
        self._captures: dict[str, CaptureThread] = {}

        setup = resolve_camera_setup(gc.logger)  # role -> live cv2 index

        # Map each drawable channel onto whichever assigned camera shows it.
        self.channel_camera_map: dict[str, str] = {}
        if "c_channel_2" in setup:
            self.channel_camera_map["second"] = "c_channel_2"
        if "c_channel_3" in setup:
            self.channel_camera_map["third"] = "c_channel_3"
            self.channel_camera_map["carousel"] = "c_channel_3"
        if "carousel" in setup:
            self.channel_camera_map["carousel"] = "carousel"
        if "classification" in setup:
            self.channel_camera_map["classification"] = "classification"

        # Start a capture thread per distinct camera the channels reference.
        for camera in set(self.channel_camera_map.values()):
            index = setup.get(camera)
            if index is None:
                continue
            cap = CaptureThread(camera, make_camera_config(index))
            cap.start()
            self._captures[camera] = cap

    # ----- frames --------------------------------------------------------

    def cameras(self) -> list[str]:
        return sorted(self._captures.keys())

    def frame_jpeg(self, camera: str) -> Optional[bytes]:
        cap = self._captures.get(camera)
        if cap is None or cap.latest_frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", cap.latest_frame.raw, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else None

    def _resolution(self, camera: str) -> list[int]:
        cap = self._captures.get(camera)
        if cap and cap.latest_frame is not None:
            h, w = cap.latest_frame.raw.shape[:2]
            return [w, h]
        return [1920, 1080]

    # ----- load / save ---------------------------------------------------

    def init_data(self) -> dict:
        """Channel->camera map + previously saved points, for the editor to restore."""
        result: dict[str, Any] = {
            "channel_camera_map": self.channel_camera_map,
            "channels": FEEDER_CHANNELS,
            "classification_channel": CLASSIFICATION_CHANNEL,
            "cameras": self.cameras(),
        }
        saved = get_channel_polygons()
        if saved:
            result["user_pts"] = saved.get("user_pts", {})
            result["section_zero_pts"] = saved.get("section_zero_pts", {})
        class_saved = get_classification_polygons()
        if class_saved:
            result["class_user_pts"] = class_saved.get("user_pts", {})
        return result

    def save(self, body: dict) -> None:
        """Persist channel + classification polygons (with per-camera resolutions)."""
        cam = self.channel_camera_map
        set_channel_polygons(
            {
                "polygons": body["polygons"],
                "user_pts": body["user_pts"],
                "channel_angles": body.get("channel_angles", {}),
                "section_zero_pts": body.get("section_zero_pts", {}),
                "resolution": self._resolution(cam.get("second", "")),
                "third_resolution": self._resolution(cam.get("third", "")),
                "carousel_resolution": self._resolution(cam.get("carousel", "")),
            }
        )
        set_classification_polygons(
            {
                "polygons": body["class_polygons"],
                "user_pts": body["class_user_pts"],
                "resolution": self._resolution(cam.get("classification", "")),
            }
        )

    # ----- lifecycle -----------------------------------------------------

    def close(self) -> None:
        with self._lock:
            for cap in self._captures.values():
                try:
                    cap.stop()
                except Exception:
                    pass
            self._captures.clear()
