"""Feed recording taps: the camera's own JPEG bytes, per-inference detection
events, and the static zone overlay, so an external recorder can store full
resolution video and stills without the Pi encoding anything.

Design: the capture thread already receives every frame the camera produces,
so tapping it adds nothing on the USB bus. ``/raw/{role}`` re-serves those
compressed bytes untouched (no decode, no re-encode). ``/events/{role}``
streams what the live feed overlay is drawn from, keyed by the timestamp of
the frame each inference ran on, and ``/zones/{role}`` serves the static zone
arrays once, so the recorder can composite the same overlay offline.
"""

from __future__ import annotations

import asyncio
import base64
import json
import queue
import time
from typing import Any, Dict, Iterator, Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from server import shared_state

router = APIRouter()

RAW_BOUNDARY = b"frame"
RAW_QUEUE_FRAMES = 12
RAW_KEEPALIVE_S = 1.0
EVENTS_POLL_S = 0.02
EVENTS_KEEPALIVE_S = 2.0


def _camera_service():
    service = shared_state.camera_service
    if service is None:
        raise HTTPException(status_code=503, detail="Camera service not running.")
    return service


def _capture_thread(role: str):
    thread = _camera_service().get_capture_thread_for_role(role)
    if thread is None:
        raise HTTPException(status_code=404, detail=f"No camera bound to role '{role}'.")
    return thread


def _perception():
    gc = shared_state.gc_ref
    return getattr(gc, "perception_service", None) if gc is not None else None


def _channel_for_role(role: str):
    ps = _perception()
    if ps is None:
        raise HTTPException(status_code=503, detail="Perception service not running.")
    channel_id = ps.channel_id_for_role(role)
    if channel_id is None:
        raise HTTPException(status_code=404, detail=f"Perception has no channel for role '{role}'.")
    channel = ps.channel_def(channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail=f"Perception channel {channel_id} is not built.")
    return ps, channel_id, channel


def _bbox(b: Any) -> list[float]:
    return [float(b[0]), float(b[1]), float(b[2]), float(b[3])]


def serialize_debug(debug: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The subset of a worker's ``latest_debug`` the feed overlay draws from,
    as plain JSON. Returns None when the snapshot has no frame yet."""
    frame = debug.get("frame")
    if frame is None:
        return None
    detections = []
    for d in debug.get("detections") or []:
        detections.append(
            {
                "bbox": _bbox(d.bbox),
                "in_primary": bool(getattr(d, "in_primary", False)),
                "track_id": getattr(d, "sv_bt_track_id", None),
            }
        )
    merged_ids = debug.get("merged_track_ids") or []
    return {
        "type": "infer",
        "frame_ts": float(frame.timestamp),
        "infer_ms": debug.get("infer_ms"),
        "on_bboxes": [_bbox(b) for b in (debug.get("pre_merge_bboxes") or debug.get("on_channel_bboxes") or [])],
        "detections": detections,
        "merged_bboxes": [_bbox(b) for b in (debug.get("merged_bboxes") or [])],
        "merged_track_ids": [None if t is None else int(t) for t in merged_ids],
        "crop_rect": list(debug["crop_rect"]) if debug.get("crop_rect") is not None else None,
    }


def raw_part(jpeg: bytes, timestamp: float, seq: int, dropped: int, repeat: bool = False) -> bytes:
    """One multipart/x-mixed-replace part carrying the camera's JPEG plus the
    capture timestamp and sequence number the recorder keys on. A repeated part
    (``X-Repeat: 1``) re-sends the last frame while the camera is quiet: it keeps
    the connection alive and gives a wall-clock-paced encoder the held frame it
    would show anyway, whereas an empty part of another content type makes
    ffmpeg's mpjpeg demuxer stop."""
    head = (
        b"--" + RAW_BOUNDARY + b"\r\n"
        b"Content-Type: image/jpeg\r\n"
        b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n"
        b"X-Timestamp: " + repr(float(timestamp)).encode() + b"\r\n"
        b"X-Seq: " + str(int(seq)).encode() + b"\r\n"
        b"X-Dropped: " + str(int(dropped)).encode() + b"\r\n"
        b"X-Repeat: " + (b"1" if repeat else b"0") + b"\r\n\r\n"
    )
    return head + jpeg + b"\r\n"


def keepalive_part() -> bytes:
    """Only before the first frame, when there is nothing to repeat yet."""
    return (
        b"--" + RAW_BOUNDARY + b"\r\n"
        b"Content-Type: application/x-keepalive\r\n"
        b"Content-Length: 0\r\n\r\n\r\n"
    )


def _png_b64(arr: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", arr)
    if not ok:
        raise HTTPException(status_code=500, detail="PNG encode failed.")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _mask_u8(mask: Any) -> np.ndarray:
    m = np.asarray(mask)
    if m.dtype != np.uint8:
        m = (m > 0).astype(np.uint8) * 255
    elif m.max(initial=0) <= 1:
        m = m * 255
    return np.ascontiguousarray(m)


def _picture_settings_dict(thread) -> Dict[str, Any]:
    ps = thread.getPictureSettings() if hasattr(thread, "getPictureSettings") else None
    return {
        "rotation": int(getattr(ps, "rotation", 0) or 0),
        "flip_horizontal": bool(getattr(ps, "flip_horizontal", False)),
        "flip_vertical": bool(getattr(ps, "flip_vertical", False)),
    }


@router.get("/api/recording/status")
def recording_status() -> Dict[str, Any]:
    service = _camera_service()
    ps = _perception()
    roles: list[Dict[str, Any]] = []
    names = sorted(set(service.feeds.keys()) | set(service.devices.keys()))
    for role in names:
        thread = service.get_capture_thread_for_role(role)
        if thread is None:
            continue
        latest = getattr(thread, "latest_frame", None)
        roles.append(
            {
                "role": role,
                "raw_bytes_available": bool(getattr(thread, "raw_bytes_available", False)),
                "last_frame_ts": float(latest.timestamp) if latest is not None else None,
                "capture_mode": thread.getCaptureMode() if hasattr(thread, "getCaptureMode") else None,
                "picture_settings": _picture_settings_dict(thread),
                "perception_channel_id": ps.channel_id_for_role(role) if ps is not None else None,
            }
        )
    return {"ok": True, "roles": roles}


@router.get("/api/recording/raw/{role}")
def raw_stream(role: str, fps: float = 0.0):
    """The camera's own JPEGs, untouched. Parts carry ``X-Timestamp`` (capture
    wall clock) and ``X-Seq``. A slow client loses frames (``X-Dropped`` counts
    them) rather than slowing the capture loop. Zero-length keepalive parts keep
    the connection observable while the camera is down.

    ``fps`` sends at most that many frames a second, chosen by capture
    timestamp. A recorder that wants 5 fps should ask for 5 rather than drop 25
    of every 30 itself: the frames it does not want are then never encoded into
    the response, never put on the network, and never decoded at the far end.
    The stream is still whole frames straight from the camera."""
    thread = _capture_thread(role)
    if fps < 0 or fps > 1000:
        raise HTTPException(status_code=400, detail="fps must be between 0 and 1000.")
    min_gap = 1.0 / fps if fps > 0 else 0.0
    if not getattr(thread, "raw_bytes_available", False):
        raise HTTPException(
            status_code=503,
            detail=f"Raw JPEG bytes are not available for role '{role}' (non-MJPEG source, URL source, or no frames yet).",
        )

    def generate() -> Iterator[bytes]:
        sub = thread.subscribe_raw(maxsize=RAW_QUEUE_FRAMES)
        last_sent = 0.0
        last: tuple[bytes, float, int] | None = None
        try:
            while True:
                try:
                    jpeg, ts, seq = sub.queue.get(timeout=RAW_KEEPALIVE_S)
                except queue.Empty:
                    yield raw_part(*last, sub.dropped, repeat=True) if last else keepalive_part()
                    continue
                if jpeg is None:
                    continue
                if min_gap and (ts - last_sent) < min_gap:
                    continue
                last_sent = ts
                last = (jpeg, ts, seq)
                yield raw_part(jpeg, ts, seq, sub.dropped)
        finally:
            thread.unsubscribe_raw(sub)

    return StreamingResponse(
        generate(),
        media_type=f"multipart/x-mixed-replace; boundary={RAW_BOUNDARY.decode()}",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/api/recording/events/{role}")
def events_stream(role: str):
    """Newline-delimited JSON: one ``header`` line, then an ``infer`` line each
    time the channel's worker completes an inference cycle (the same data the
    live feed overlay is drawn from, keyed by the inferred frame's timestamp),
    and a ``keepalive`` line when idle."""
    ps, channel_id, channel = _channel_for_role(role)
    thread = _capture_thread(role)
    header = {
        "type": "header",
        "role": role,
        "channel_id": int(channel_id),
        "frame_size": [int(v) for v in np.asarray(channel.mask).shape[:2]],
        "picture_settings": _picture_settings_dict(thread),
        "started_at": time.time(),
    }

    async def generate():
        yield (json.dumps(header) + "\n").encode()
        last_ts: Optional[float] = None
        last_emit = time.monotonic()
        while True:
            debug = ps.debug_snapshot(channel_id)
            payload = serialize_debug(debug) if debug else None
            if payload is not None and payload["frame_ts"] != last_ts:
                last_ts = payload["frame_ts"]
                payload["sent_at"] = time.time()
                yield (json.dumps(payload) + "\n").encode()
                last_emit = time.monotonic()
            elif time.monotonic() - last_emit > EVENTS_KEEPALIVE_S:
                yield (json.dumps({"type": "keepalive", "sent_at": time.time()}) + "\n").encode()
                last_emit = time.monotonic()
            await asyncio.sleep(EVENTS_POLL_S)

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/api/recording/zones/{role}")
def zones(role: str) -> Dict[str, Any]:
    """The static zone overlay for a role at full frame resolution, as PNGs:
    the colour fill the feed blends at low opacity and the channel mask whose
    contour is the outline. Fetched once per recording; combined with
    ``/events`` it reproduces the live overlay."""
    from perception.overlay import (
        CHANNEL_OUTLINE_COLOR,
        MERGED_COLOR,
        ON_CHANNEL_COLOR,
        channelZoneOverlay,
    )

    _, channel_id, channel = _channel_for_role(role)
    thread = _capture_thread(role)
    base = channelZoneOverlay(channel)
    overlay = base[0] if base is not None else np.zeros((*np.asarray(channel.mask).shape[:2], 3), np.uint8)
    return {
        "ok": True,
        "role": role,
        "channel_id": int(channel_id),
        "frame_size": [int(v) for v in np.asarray(channel.mask).shape[:2]],
        "picture_settings": _picture_settings_dict(thread),
        "capture_mode": thread.getCaptureMode() if hasattr(thread, "getCaptureMode") else None,
        "overlay_png_b64": _png_b64(np.ascontiguousarray(overlay)),
        "mask_png_b64": _png_b64(_mask_u8(channel.mask)),
        "colors": {
            "on_channel": list(ON_CHANNEL_COLOR),
            "merged": list(MERGED_COLOR),
            "channel_outline": list(CHANNEL_OUTLINE_COLOR),
        },
        "zone_fill_alpha": 0.15,
    }
