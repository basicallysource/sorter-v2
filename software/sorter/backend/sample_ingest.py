from __future__ import annotations

import os
import threading
from typing import Any

import cv2
import numpy as np

from global_config import GlobalConfig

# Builds one training sample from a camera's latest frame for sample_store:
# the frame as the camera sent it, with everything needed to make sense of it
# later — the camera's settings and live readout, the lamp lighting it, the
# channel outline the frame is cut by, and (when annotation is on) what a
# detector saw in it.

_FEEDER_ROLES = {"c_channel_2", "c_channel_3"}

# Hive only runs its teacher pass on samples whose source_role maps to a teacher
# zone (mirror of hive teacher_detector.SOURCE_ROLE_TO_ZONE). A frame from a
# camera with no teacher zone (e.g. the wide "feeder" overview cam) can never be
# promoted past "raw", so it is not sampled.
TEACHER_ZONE_ROLES = {
    "classification_chamber",
    "carousel",
    "classification_channel",
    "c_channel",
    "c_channel_1",
    "c_channel_2",
    "c_channel_3",
    "c_channel_full",
}

# scope -> Gemini prompt zone (see vision/gemini_sam_detector.ZONE_PROMPTS).
# Unknown zones fall back to classification_chamber inside the detector.
_ZONE_FOR_SCOPE = {
    "classification": "classification_channel",
    "carousel": "carousel",
    "feeder": "classification_chamber",
}

# Quality for the frames that must be re-encoded (a camera with rotation or
# flips set, or no JPEG of its own): high, so the copy is close to the original.
_REENCODE_QUALITY = 95

# One detector per scope, reused across frames (detect(force=True) is stateless
# per call, so sharing is safe and avoids re-init churn).
_detectors: dict[str, Any] = {}

_software_lock = threading.Lock()
_software: dict[str, Any] | None = None


def scopeForRole(role: str) -> str:
    if role in _FEEDER_ROLES:
        return "feeder"
    if role == "carousel":
        return "carousel"
    return "classification"


def _openRouterModelForScope(scope: str) -> str:
    from toml_config import getDetectionConfig
    from vision.gemini_sam_detector import DEFAULT_OPENROUTER_MODEL, normalize_openrouter_model

    try:
        cfg = getDetectionConfig(scope)
        model = cfg.get("openrouter_model") if isinstance(cfg, dict) else None
        return normalize_openrouter_model(model)
    except Exception:
        return DEFAULT_OPENROUTER_MODEL


def _annotate(gc: GlobalConfig, scope: str, frame_bgr: np.ndarray) -> tuple[Any | None, str | None]:
    # Best-effort: a missing key or any failure returns (None, model) so the
    # frame is still kept as a raw sample.
    if not os.getenv("OPENROUTER_API_KEY"):
        return None, None
    model = _openRouterModelForScope(scope)
    try:
        from vision.gemini_sam_detector import GeminiSamDetector

        detector = _detectors.get(scope)
        if detector is None:
            detector = GeminiSamDetector(model, zone=_ZONE_FOR_SCOPE.get(scope, "classification_chamber"))
            _detectors[scope] = detector
        else:
            detector.setOpenRouterModel(model)
        return detector.detect(frame_bgr, force=True), model
    except Exception as exc:
        gc.logger.warning("sample annotation failed (%s): %s" % (scope, exc))
        return None, model


def _detection(gc: GlobalConfig, scope: str, frame_bgr: np.ndarray, annotate: bool) -> dict[str, Any]:
    detection, model = _annotate(gc, scope, frame_bgr) if annotate else (None, None)
    if detection is None:
        return {"algorithm": "raw_capture", "found": False, "bbox": None, "candidate_bboxes": [], "count": 0, "score": None}
    found = getattr(detection, "bbox", None) is not None
    score = getattr(detection, "score", None)
    return {
        "algorithm": "gemini_sam",
        "openrouter_model": model,
        "found": bool(found),
        "bbox": [int(v) for v in detection.bbox] if found else None,
        "candidate_bboxes": [[int(v) for v in b] for b in detection.bboxes],
        "count": len(detection.bboxes),
        "score": float(score) if score is not None else None,
    }


def _pictureSettings(capture: Any) -> dict[str, Any]:
    try:
        ps = capture.getPictureSettings()
        return {
            "rotation": int(ps.rotation),
            "flip_horizontal": bool(ps.flip_horizontal),
            "flip_vertical": bool(ps.flip_vertical),
        }
    except Exception:
        return {"rotation": 0, "flip_horizontal": False, "flip_vertical": False}


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _deviceIdentity(capture: Any) -> dict[str, Any]:
    """Which physical camera this is: its device index and the model name the
    kernel reports for it. Both are None for a network camera, whose address can
    carry a login and is never recorded."""
    identity: dict[str, Any] = {"device_index": None, "model": None}
    try:
        source = capture.getCameraSource()
        if isinstance(source, int) and not isinstance(source, bool) and source >= 0:
            from machine_specs import v4l2CameraModel

            identity["device_index"] = source
            identity["model"] = v4l2CameraModel(source)
    except Exception:
        pass
    return identity


def _cameraInfo(role: str, capture: Any, picture: dict[str, Any], image_source: str) -> dict[str, Any]:
    """The camera's state when the frame was taken: which channel and physical
    camera it is, the device settings the sorter applied, the values the driver
    reports now (which, with auto exposure or white balance on, may differ), its
    readout (resolution, frame rate), the capture mode it was asked for and the
    picture settings the sorter applies after capture."""
    try:
        from channel_geometry_payload import channelIdForRole

        channel = channelIdForRole(role)
    except Exception:
        channel = None
    info: dict[str, Any] = {"channel": channel, **_deviceIdentity(capture), "picture_settings": picture, "image": image_source}
    for key, read in (
        ("capture_mode", lambda: capture.getCaptureMode()),
        ("applied_settings", lambda: capture.getDeviceSettings()),
        ("readout", lambda: capture.getTelemetrySnapshot()),
        ("reported_settings", lambda: capture.describeDeviceControls()[1]),
    ):
        try:
            info[key] = _jsonable(read())
        except Exception:
            info[key] = None
    return info


def _lampInfo(role: str) -> dict[str, Any] | None:
    """The light this camera's channel is assigned and its brightness. Outputs
    can be shared, so the channels on the same output are listed too."""
    try:
        from local_state import get_led_state

        state = get_led_state()
    except Exception:
        return None
    output = state["assignments"].get(role)
    if output is None:
        return {"output": None}
    return {
        "output": output,
        "brightness_percent": state["brightness"].get(output),
        "channels_on_output": sorted(k for k, v in state["assignments"].items() if v == output),
    }


def _softwareInfo() -> dict[str, Any]:
    # Read once per process: the version only changes with a restart.
    global _software
    with _software_lock:
        if _software is None:
            try:
                from status_ping import _softwareInfo as read

                _software = read()
            except Exception:
                _software = {}
        return dict(_software)


def buildSample(gc: GlobalConfig, role: str, capture: Any, frame: Any, *, annotate: bool) -> tuple[bytes, dict[str, Any]] | None:
    """The JPEG and the metadata for one sample from `frame` (a CameraFrame from
    `capture`), or None when there is nothing to keep."""
    if role not in TEACHER_ZONE_ROLES:
        return None
    frame_bgr = getattr(frame, "raw", None)
    if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
        return None
    picture = _pictureSettings(capture)
    identity = picture["rotation"] % 360 == 0 and not picture["flip_horizontal"] and not picture["flip_vertical"]
    raw_jpeg = getattr(frame, "raw_jpeg", None)
    if identity and raw_jpeg:
        # The camera's own JPEG: no decode/encode loss, and it is the same frame
        # (same orientation and size) the channel outline is drawn on.
        jpeg = bytes(raw_jpeg)
        image_source = "camera_jpeg"
    else:
        # The outline is drawn on the frame after rotation and flips, so a
        # camera with those set sends that frame, re-encoded.
        ok, encoded = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, _REENCODE_QUALITY])
        if not ok:
            return None
        jpeg = encoded.tobytes()
        image_source = "reencoded_after_picture_settings" if not identity else "reencoded"
    height, width = frame_bgr.shape[:2]

    scope = scopeForRole(role)
    geometry = None
    try:
        from channel_geometry_payload import buildChannelGeometryForRole

        geometry = buildChannelGeometryForRole(role)
    except Exception as exc:
        gc.logger.warning("sample: no channel outline for %s: %s" % (role, exc))
    geometry_matches = None
    if isinstance(geometry, dict) and geometry.get("frame_width") and geometry.get("frame_height"):
        geometry_matches = int(geometry["frame_width"]) == int(width) and int(geometry["frame_height"]) == int(height)

    captured_at = getattr(frame, "timestamp", None)
    meta = {
        "source_role": role,
        "capture_reason": "standalone_sample_collection",
        "detection_scope": scope,
        "detection": _detection(gc, scope, frame_bgr, annotate),
        "camera": _cameraInfo(role, capture, picture, image_source),
        "lamp": _lampInfo(role),
        "channel_geometry": geometry,
        # False when the outline was calibrated for a different frame size than
        # this frame: Hive should not trust the outline on this sample.
        "channel_geometry_matches_frame": geometry_matches,
        "software": _softwareInfo(),
    }
    return jpeg, {
        "camera": role,
        "captured_at": float(captured_at) if isinstance(captured_at, (int, float)) else None,
        "width": int(width),
        "height": int(height),
        "meta": meta,
    }
