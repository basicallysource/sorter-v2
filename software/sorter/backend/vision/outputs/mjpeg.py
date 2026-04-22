"""MJPEG output — JPEG encoding for multipart streaming."""

from __future__ import annotations

import cv2
import numpy as np


class MjpegOutput:
    def encode(self, frame: np.ndarray, quality: int = 80) -> bytes:
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes()

    def encode_chunk(self, frame: np.ndarray, quality: int = 80) -> bytes:
        data = self.encode(frame, quality)
        return (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(data)).encode() + b"\r\n\r\n"
            + data + b"\r\n"
        )
