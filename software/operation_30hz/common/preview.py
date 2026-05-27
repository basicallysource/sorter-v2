"""Minimal MJPEG preview server. Faithful to the live setup in two ways:

1. Three endpoints — one per camera — served by FastAPI/uvicorn over the
   same anyio worker pool (default cap 40).
2. The overlay-rendering callback is invoked on the request-handler thread.
   That's where the live code currently leaks YOLO inference: the overlay
   lambda calls _getFeederObjectDetection() as a side effect of rendering.
   In rev01 we mimic this faithfully (handler thread runs RKNN). In rev02
   the handler just reads a slot.

Callers pass `overlay_fn(role, frame_bgr) -> annotated_bgr` and we JPEG-encode
the result with cv2.imencode (which releases the GIL during the encode call).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, Optional

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import uvicorn


log = logging.getLogger("preview")

OverlayFn = Callable[[str, np.ndarray], np.ndarray]


def make_server(
    role_to_latest_frame: Dict[str, Callable[[], Optional[np.ndarray]]],
    overlay_fn: OverlayFn,
    port: int,
    metrics,
) -> uvicorn.Server:
    app = FastAPI()

    def gen_mjpeg(role: str):
        get_frame = role_to_latest_frame[role]
        boundary = b"--frame\r\n"
        while True:
            t0 = time.perf_counter()
            frame = get_frame()
            if frame is None:
                time.sleep(0.01)
                continue
            t1 = time.perf_counter()
            annotated = overlay_fn(role, frame)
            t2 = time.perf_counter()
            ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ok:
                continue
            t3 = time.perf_counter()
            metrics.observe(f"preview.{role}.get_frame_ms", (t1 - t0) * 1000.0)
            metrics.observe(f"preview.{role}.overlay_ms", (t2 - t1) * 1000.0)
            metrics.observe(f"preview.{role}.encode_ms", (t3 - t2) * 1000.0)
            metrics.hit_by_thread(f"preview.{role}.serve.by_thread")
            yield boundary + b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"

    @app.get("/preview/{role}")
    def preview(role: str):
        if role not in role_to_latest_frame:
            return {"error": f"unknown role {role}"}
        return StreamingResponse(
            gen_mjpeg(role), media_type="multipart/x-mixed-replace; boundary=frame"
        )

    cfg = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning", access_log=False)
    return uvicorn.Server(cfg)


def run_server_in_thread(server: uvicorn.Server) -> threading.Thread:
    t = threading.Thread(target=server.run, daemon=True, name="preview-uvicorn")
    t.start()
    return t
