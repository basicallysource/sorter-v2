from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import subprocess
import sys
from typing import Optional


@dataclass(frozen=True)
class CameraMode:
    width: int
    height: int
    max_fps: float
    fourcc: str

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "fps": round(self.max_fps, 2),
            "fourcc": self.fourcc,
        }


_ENUM_HELPER = r"""
import json
import AVFoundation
import CoreMedia

result = {}
types = [AVFoundation.AVCaptureDeviceTypeBuiltInWideAngleCamera]
for name in ("AVCaptureDeviceTypeExternal", "AVCaptureDeviceTypeExternalUnknown"):
    t = getattr(AVFoundation, name, None)
    if t is not None and t not in types:
        types.append(t)

session = AVFoundation.AVCaptureDeviceDiscoverySession.discoverySessionWithDeviceTypes_mediaType_position_(
    types,
    AVFoundation.AVMediaTypeVideo,
    AVFoundation.AVCaptureDevicePositionUnspecified,
)

for dev in session.devices():
    modes = []
    for fmt in dev.formats():
        desc = fmt.formatDescription()
        dims = CoreMedia.CMVideoFormatDescriptionGetDimensions(desc)
        st = CoreMedia.CMFormatDescriptionGetMediaSubType(desc)
        fourcc = bytes([(st >> 24) & 0xff, (st >> 16) & 0xff, (st >> 8) & 0xff, st & 0xff]).decode("ascii", "replace")
        max_fps = 0.0
        for r in fmt.videoSupportedFrameRateRanges():
            mx = float(r.maxFrameRate())
            if mx > max_fps:
                max_fps = mx
        modes.append({"width": int(dims.width), "height": int(dims.height), "fps": max_fps, "fourcc": fourcc})
    result[str(dev.uniqueID())] = modes

print(json.dumps(result))
"""


def _parse_location_id(unique_id: str) -> int | None:
    if not isinstance(unique_id, str) or not unique_id.startswith("0x"):
        return None
    hex_digits = unique_id[2:]
    if len(hex_digits) < 16:
        return None
    try:
        return int(hex_digits[:8], 16)
    except ValueError:
        return None


def _enumerate_via_subprocess() -> dict[str, list[dict]]:
    try:
        result = subprocess.run(
            [sys.executable, "-c", _ENUM_HELPER],
            capture_output=True,
            text=True,
            timeout=8,
            check=True,
        )
    except Exception:
        return {}
    try:
        parsed = json.loads(result.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _enumerate_in_process() -> dict[str, list[dict]]:
    try:
        import AVFoundation  # type: ignore
        import CoreMedia  # type: ignore
    except Exception:
        return {}

    types = [AVFoundation.AVCaptureDeviceTypeBuiltInWideAngleCamera]
    for name in ("AVCaptureDeviceTypeExternal", "AVCaptureDeviceTypeExternalUnknown"):
        t = getattr(AVFoundation, name, None)
        if t is not None and t not in types:
            types.append(t)

    try:
        session = AVFoundation.AVCaptureDeviceDiscoverySession.discoverySessionWithDeviceTypes_mediaType_position_(
            types,
            AVFoundation.AVMediaTypeVideo,
            AVFoundation.AVCaptureDevicePositionUnspecified,
        )
    except Exception:
        return {}

    out: dict[str, list[dict]] = {}
    for dev in session.devices():
        modes: list[dict] = []
        try:
            for fmt in dev.formats():
                desc = fmt.formatDescription()
                dims = CoreMedia.CMVideoFormatDescriptionGetDimensions(desc)
                st = CoreMedia.CMFormatDescriptionGetMediaSubType(desc)
                fourcc = bytes([(st >> 24) & 0xff, (st >> 16) & 0xff, (st >> 8) & 0xff, st & 0xff]).decode(
                    "ascii", "replace"
                )
                max_fps = 0.0
                for r in fmt.videoSupportedFrameRateRanges():
                    mx = float(r.maxFrameRate())
                    if mx > max_fps:
                        max_fps = mx
                modes.append(
                    {"width": int(dims.width), "height": int(dims.height), "fps": max_fps, "fourcc": fourcc}
                )
        except Exception:
            continue
        out[str(dev.uniqueID())] = modes
    return out


@lru_cache(maxsize=1)
def _cached_raw_modes() -> dict[str, list[dict]]:
    data = _enumerate_via_subprocess()
    if data:
        return data
    return _enumerate_in_process()


def invalidate_cache() -> None:
    _cached_raw_modes.cache_clear()


def _collapse_modes(entries: list[dict]) -> list[CameraMode]:
    """Pick max FPS per (width, height). Prefer MJPEG/420v (compressed-decoded) over YUY2/yuvs."""

    def score(fourcc: str) -> int:
        # Higher = preferred
        priority = {
            "MJPG": 4,
            "420v": 3,  # AVFoundation's decoded NV12 — usually from MJPEG on USB
            "420f": 3,
            "yuvs": 2,  # YUY2 — bandwidth-limited at high res
            "YUY2": 2,
            "BGRA": 1,
        }
        return priority.get(fourcc, 0)

    best: dict[tuple[int, int], CameraMode] = {}
    for item in entries:
        try:
            width = int(item["width"])
            height = int(item["height"])
            fps = float(item["fps"])
            fourcc = str(item["fourcc"])
        except (KeyError, TypeError, ValueError):
            continue
        if width <= 0 or height <= 0 or fps <= 0:
            continue
        key = (width, height)
        candidate = CameraMode(width=width, height=height, max_fps=fps, fourcc=fourcc)
        incumbent = best.get(key)
        if incumbent is None:
            best[key] = candidate
            continue
        # Prefer higher FPS; break ties with fourcc priority
        if candidate.max_fps > incumbent.max_fps + 0.01:
            best[key] = candidate
        elif abs(candidate.max_fps - incumbent.max_fps) <= 0.01 and score(candidate.fourcc) > score(
            incumbent.fourcc
        ):
            best[key] = candidate

    modes = sorted(best.values(), key=lambda m: (m.width * m.height, m.max_fps))
    return modes


def list_modes_for_unique_id(unique_id: str) -> list[CameraMode]:
    raw = _cached_raw_modes()
    entries = raw.get(unique_id) or []
    return _collapse_modes(entries)


def list_modes_for_location_id(location_id: int) -> list[CameraMode]:
    raw = _cached_raw_modes()
    for unique_id, entries in raw.items():
        parsed = _parse_location_id(unique_id)
        if parsed is not None and parsed == location_id:
            return _collapse_modes(entries)
    return []


def find_unique_id_for_location(location_id: int) -> Optional[str]:
    raw = _cached_raw_modes()
    for unique_id in raw:
        if _parse_location_id(unique_id) == location_id:
            return unique_id
    return None
