"""Base64 output — JPEG encoding for WebSocket broadcast."""

from __future__ import annotations

import base64

import cv2
import numpy as np


class Base64Output:
    def encode(self, frame: np.ndarray, quality: int = 80) -> str:
        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return base64.b64encode(buffer).decode("utf-8")
