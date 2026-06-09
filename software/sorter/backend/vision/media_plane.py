"""Media-plane topology and capability probes for camera transport.

The target camera architecture is one capture and one hardware H.264 encoder per
physical camera, with browser-side overlays. This module exposes the parts of
that target that can be verified independently of the eventual WebRTC signaling
implementation: physical-source deduplication, raw-frame ring buffers, and
Rockchip/WebRTC encoder prerequisites.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from .gstreamer_target_capture import (
    TARGET_PIPELINE_NAME as GSTREAMER_TARGET_PIPELINE_NAME,
    build_gstreamer_target_capture_contract,
    patched_videoconvertscale_rga_enabled,
    target_detection_crop_strategy,
)


_CAPABILITY_CACHE_S = 300.0
_FFMPEG_RKMPP_TEST_S = 0.15
_V4L2_H264_FORMATS = frozenset({"H264", "S264", "AVC1", "X264"})
_V4L2_JPEG_FORMATS = frozenset({"JPEG", "MJPG"})
_V4L2_RAW_YUV_FORMATS = frozenset(
    {
        "NV12",
        "NM12",
        "NV21",
        "YM12",
        "YU12",
        "YV12",
        "YUYV",
        "UYVY",
    }
)
CAMERA_METADATA_MESSAGE_TYPE = "camera.feed_metadata"
CAMERA_METADATA_SCHEMA_VERSION = 1
HIGH_RES_PREVIEW_BUDGET_MAX_WIDTH = 1280
HIGH_RES_PREVIEW_BUDGET_MAX_HEIGHT = 720
CAMERA_METADATA_DATA_CHANNEL_LABEL = "camera-metadata"


def camera_metadata_data_channel_spec() -> dict[str, Any]:
    return {
        "label": CAMERA_METADATA_DATA_CHANNEL_LABEL,
        "ordered": False,
        "max_retransmits": 0,
        "message_type": CAMERA_METADATA_MESSAGE_TYPE,
        "schema_version": CAMERA_METADATA_SCHEMA_VERSION,
    }


def _command_output(args: list[str], timeout_s: float = 2.0) -> str:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except Exception:
        return ""
    return "\n".join(part for part in (result.stdout, result.stderr) if part)


def _command_result(args: list[str], timeout_s: float = 2.0) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except Exception:
        return None


def _probe_librga_direct_runtime() -> dict[str, Any]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "probe_librga_scale_crop.py"
    if not script.exists():
        return {
            "ok": False,
            "available": False,
            "runtime_ready": False,
            "reason": "librga scale/crop probe script is not installed.",
        }
    result = _command_result([sys.executable, str(script), "--json"], timeout_s=10.0)
    if result is None:
        return {
            "ok": False,
            "available": False,
            "runtime_ready": False,
            "reason": "librga scale/crop probe did not complete.",
        }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    ok = bool(payload.get("ok")) and result.returncode == 0
    return {
        **payload,
        "ok": ok,
        "runtime_ready": bool(ok and payload.get("runtime_ready", True)),
        "probe_returncode": result.returncode,
        "probe_stderr": result.stderr.strip()[:1000],
    }


def _probe_gstreamer_videoconvertscale_rga(gst_bin: str | None) -> dict[str, Any]:
    if not gst_bin:
        return {
            "tested": False,
            "ok": False,
            "element": None,
            "reason": "gst-inspect-1.0 is not available.",
        }
    if not patched_videoconvertscale_rga_enabled():
        return {
            "tested": False,
            "ok": False,
            "element": None,
            "reason": (
                "Patched videoconvertscale RGA is available only as an explicit opt-in "
                "because the live appsink graph is not stable on this image."
            ),
        }
    if os.environ.get("GST_VIDEO_CONVERT_USE_RGA", "").strip().lower() in {"0", "false", "no", "off"}:
        return {
            "tested": False,
            "ok": False,
            "element": None,
            "reason": "GST_VIDEO_CONVERT_USE_RGA explicitly disables the patched RGA converter.",
        }
    launcher = shutil.which("gst-launch-1.0")
    if not launcher:
        return {
            "tested": False,
            "ok": False,
            "element": None,
            "reason": "gst-launch-1.0 is not available.",
        }
    if not _command_output([gst_bin, "videoconvertscale"], timeout_s=2.0):
        return {
            "tested": False,
            "ok": False,
            "element": None,
            "reason": "videoconvertscale is not available.",
        }
    env = {**os.environ, "GST_VIDEO_CONVERT_USE_RGA": "1"}
    try:
        result = subprocess.run(
            [
                launcher,
                "-q",
                "videotestsrc",
                "num-buffers=1",
                "!",
                "video/x-raw,format=NV12,width=64,height=64,framerate=1/1",
                "!",
                "videoconvertscale",
                "!",
                "video/x-raw,format=NV12,width=32,height=32",
                "!",
                "fakesink",
                "sync=false",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            env=env,
        )
    except Exception as exc:
        return {
            "tested": True,
            "ok": False,
            "element": "videoconvertscale",
            "reason": str(exc),
        }
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    ok = result.returncode == 0 and "rga_api" in output.lower()
    return {
        "tested": True,
        "ok": bool(ok),
        "element": "videoconvertscale" if ok else None,
        "reason": "videoconvertscale initialized librga via GST_VIDEO_CONVERT_USE_RGA=1."
        if ok
        else (output.strip()[:500] or f"gst-launch returned {result.returncode} without RGA evidence."),
    }


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _ffmpeg_rkmpp_source_factory_importable() -> bool:
    try:
        from .ffmpeg_h264_source import create_ffmpeg_rkmpp_h264_source

        return callable(create_ffmpeg_rkmpp_h264_source)
    except Exception:
        return False


def _gstreamer_capture_source_factory_importable() -> bool:
    try:
        from .gstreamer_h264_source import create_gstreamer_capture_h264_source

        return callable(create_gstreamer_capture_h264_source)
    except Exception:
        return False


def _gstreamer_target_runtime_description() -> dict[str, Any]:
    try:
        from .gstreamer_target_runtime import describe_gstreamer_target_runtime

        description = describe_gstreamer_target_runtime()
        return description if isinstance(description, dict) else {"implemented": False}
    except Exception as exc:
        return {
            "implemented": False,
            "runtime_importable": False,
            "implementation": GSTREAMER_TARGET_PIPELINE_NAME,
            "raw_ring_branch": True,
            "h264_webrtc_branch": True,
            "software_h264_fallback_allowed": False,
            "reason": f"Could not import target GStreamer runtime module: {exc}",
        }


def _device_paths(patterns: list[str]) -> list[str]:
    paths: set[str] = set()
    for pattern in patterns:
        for path in Path("/dev").glob(pattern):
            paths.add(str(path))
    return sorted(paths)


def _path_exists_map(paths: list[str]) -> dict[str, bool]:
    return {path: Path(path).exists() for path in paths}


def _process_command(proc_dir: Path) -> str:
    try:
        raw = (proc_dir / "cmdline").read_bytes()
        command = raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()
    except OSError:
        command = ""
    if not command:
        try:
            command = (proc_dir / "comm").read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            command = ""
    return command[:240] if command else "unknown"


def _summarize_video_handle_entries(
    entries: list[dict[str, Any]],
    *,
    available: bool = True,
    permission_denied: int = 0,
    scan_errors: int = 0,
    reason: str | None = None,
) -> dict[str, Any]:
    by_path: dict[str, dict[str, Any]] = {}
    all_processes: set[int] = set()

    for entry in entries:
        path = str(entry.get("path") or "")
        if not path:
            continue
        try:
            pid = int(entry.get("pid"))
        except (TypeError, ValueError):
            continue
        command = str(entry.get("command") or "unknown")[:240]
        fd = str(entry.get("fd") or "")

        item = by_path.setdefault(
            path,
            {
                "path": path,
                "handle_count": 0,
                "process_count": 0,
                "processes": {},
            },
        )
        item["handle_count"] += 1
        all_processes.add(pid)
        process = item["processes"].setdefault(
            pid,
            {
                "pid": pid,
                "command": command,
                "fd_count": 0,
                "fds": [],
            },
        )
        process["fd_count"] += 1
        if fd:
            process["fds"].append(fd)

    paths: dict[str, dict[str, Any]] = {}
    for path, item in sorted(by_path.items()):
        processes = sorted(
            item["processes"].values(),
            key=lambda process: (-int(process["fd_count"]), int(process["pid"])),
        )
        paths[path] = {
            "path": path,
            "handle_count": int(item["handle_count"]),
            "process_count": len(processes),
            "processes": processes[:12],
            "processes_truncated": max(0, len(processes) - 12),
        }

    return {
        "available": bool(available),
        "reason": reason,
        "total_handles": sum(int(item["handle_count"]) for item in paths.values()),
        "total_processes": len(all_processes),
        "permission_denied": int(permission_denied),
        "scan_errors": int(scan_errors),
        "paths": paths,
    }


def _scan_video_open_handles(proc_root: Path = Path("/proc")) -> dict[str, Any]:
    if platform.system() != "Linux" or not proc_root.exists():
        return _summarize_video_handle_entries(
            [],
            available=False,
            reason="OS video handle audit is only available on Linux hosts with /proc.",
        )

    entries: list[dict[str, Any]] = []
    permission_denied = 0
    scan_errors = 0
    video_re = re.compile(r"^/dev/video\d+$")

    try:
        proc_dirs = list(proc_root.iterdir())
    except PermissionError:
        return _summarize_video_handle_entries(
            [],
            available=False,
            permission_denied=1,
            reason=f"Permission denied while scanning {proc_root}.",
        )
    except OSError as exc:
        return _summarize_video_handle_entries(
            [],
            available=False,
            scan_errors=1,
            reason=f"Could not scan {proc_root}: {exc}",
        )

    for proc_dir in proc_dirs:
        if not proc_dir.name.isdigit():
            continue
        try:
            pid = int(proc_dir.name)
        except ValueError:
            continue
        command = _process_command(proc_dir)
        fd_dir = proc_dir / "fd"
        try:
            fd_entries = list(fd_dir.iterdir())
        except PermissionError:
            permission_denied += 1
            continue
        except FileNotFoundError:
            continue
        except OSError:
            scan_errors += 1
            continue

        for fd_path in fd_entries:
            try:
                target = os.readlink(fd_path)
            except PermissionError:
                permission_denied += 1
                continue
            except FileNotFoundError:
                continue
            except OSError:
                scan_errors += 1
                continue
            target = target.removesuffix(" (deleted)")
            if not video_re.fullmatch(target):
                continue
            entries.append(
                {
                    "path": target,
                    "pid": pid,
                    "fd": fd_path.name,
                    "command": command,
                }
            )

    return _summarize_video_handle_entries(
        entries,
        available=True,
        permission_denied=permission_denied,
        scan_errors=scan_errors,
    )


def _with_live_video_handle_audit(capabilities: dict[str, Any]) -> dict[str, Any]:
    devices = dict(capabilities.get("devices", {}))
    devices["video_open_handles"] = _scan_video_open_handles()
    return {**capabilities, "devices": devices}


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(token.lower() in lower for token in tokens)


def _candidate_ffmpeg_bins() -> list[str]:
    candidates: list[str] = []
    env_bin = os.environ.get("SORTER_FFMPEG_BIN")
    if env_bin:
        candidates.append(env_bin)
    which_bin = shutil.which("ffmpeg")
    if which_bin:
        candidates.append(which_bin)
    candidates.extend(
        [
            "/home/orangepi/.local/ffmpeg-rockchip/bin/ffmpeg",
            "/opt/ffmpeg-rockchip/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
            "/usr/bin/ffmpeg",
        ]
    )
    seen: set[str] = set()
    result: list[str] = []
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if Path(candidate).exists():
            result.append(candidate)
    return result


def _probe_ffmpeg_bin(path: str) -> dict[str, Any]:
    output = _command_output([path, "-hide_banner", "-encoders"], timeout_s=3.0)
    decoders = _command_output([path, "-hide_banner", "-decoders"], timeout_s=3.0)
    filters = _command_output([path, "-hide_banner", "-filters"], timeout_s=3.0)
    has_h264 = "h264_rkmpp" in output
    has_hevc = "hevc_rkmpp" in output
    has_mjpeg_rkmpp_decoder = "mjpeg_rkmpp" in decoders
    has_software_mjpeg_decoder = bool(
        re.search(r"^\s*V\S*\s+mjpeg\s", decoders, flags=re.MULTILINE)
    )
    has_rga = _contains_any(filters, ("scale_rkrga", "vpp_rkrga", "overlay_rkrga"))
    has_rga_crop = _contains_any(filters, ("vpp_rkrga",))
    runtime = _probe_ffmpeg_runtime(
        path,
        [
            "-hide_banner",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=5",
            "-t",
            str(_FFMPEG_RKMPP_TEST_S),
            "-vf",
            "format=nv12",
            "-c:v",
            "h264_rkmpp",
            "-b:v",
            "512k",
            "-f",
            "h264",
        ],
        suffix=".h264",
    ) if has_h264 else {
        "tested": False,
        "ok": False,
        "bytes": 0,
        "error": None,
    }
    rga_runtime = _probe_ffmpeg_runtime(
        path,
        [
            "-hide_banner",
            "-y",
            "-init_hw_device",
            "rkmpp=hw",
            "-filter_hw_device",
            "hw",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=5,format=nv12",
            "-t",
            str(_FFMPEG_RKMPP_TEST_S),
            "-vf",
            "hwupload,scale_rkrga=w=160:h=120:format=nv12",
            "-c:v",
            "h264_rkmpp",
            "-b:v",
            "512k",
            "-f",
            "h264",
        ],
        suffix=".h264",
    ) if has_h264 and has_rga else {
        "tested": False,
        "ok": False,
        "bytes": 0,
        "error": None,
    }
    rga_crop_runtime = _probe_ffmpeg_runtime(
        path,
        [
            "-hide_banner",
            "-y",
            "-init_hw_device",
            "rkmpp=hw",
            "-filter_hw_device",
            "hw",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1920x1080:rate=5,format=nv12",
            "-t",
            str(_FFMPEG_RKMPP_TEST_S),
            "-vf",
            "hwupload,vpp_rkrga=cx=320:cy=180:cw=1280:ch=720:w=640:h=360:format=nv12",
            "-c:v",
            "h264_rkmpp",
            "-b:v",
            "512k",
            "-f",
            "h264",
        ],
        suffix=".h264",
    ) if has_h264 and has_rga_crop else {
        "tested": False,
        "ok": False,
        "bytes": 0,
        "error": None,
    }

    return {
        "path": path,
        "available": bool(output),
        "rkmpp_h264_encoder": has_h264,
        "rkmpp_hevc_encoder": has_hevc,
        "rkmpp_mjpeg_decoder": has_mjpeg_rkmpp_decoder,
        "software_mjpeg_decoder": has_software_mjpeg_decoder,
        "rkrga_filters": has_rga,
        "rkrga_crop_filter": has_rga_crop,
        "runtime_h264_rkmpp": runtime,
        "runtime_rkrga_h264_rkmpp": rga_runtime,
        "runtime_rkrga_crop_h264_rkmpp": rga_crop_runtime,
    }


def _probe_ffmpeg_runtime(
    path: str,
    args_before_output: list[str],
    *,
    suffix: str,
) -> dict[str, Any]:
    fd, output_path = tempfile.mkstemp(suffix=suffix, prefix="sorter-rkmpp-")
    os.close(fd)
    try:
        result = _command_result([path, *args_before_output, output_path], timeout_s=5.0)
        size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
        ok = bool(result is not None and result.returncode == 0 and size > 0)
        return {
            "tested": True,
            "ok": ok,
            "bytes": int(size),
            "error": None
            if ok
            else (
                "\n".join(
                    part for part in (
                        getattr(result, "stdout", "") if result is not None else "",
                        getattr(result, "stderr", "") if result is not None else "",
                    )
                    if part
                )[-1200:]
                if result is not None
                else "ffmpeg runtime probe did not complete"
            ),
        }
    finally:
        try:
            Path(output_path).unlink(missing_ok=True)
        except Exception:
            pass


def _v4l2_value(text: str, label: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(label)}\s*:\s*(.+?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def _v4l2_current_format(text: str, header: str) -> dict[str, str] | None:
    marker = f"{header}:"
    start = text.find(marker)
    if start < 0:
        return None
    block = text[start + len(marker):]
    lines: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if lines and stripped.endswith(":") and not line.startswith(("\t", " ")):
            break
        lines.append(line)

    match = re.search(r"Pixel Format\s*:\s*'([^']+)'\s*(?:\((.*)\))?", "\n".join(lines))
    if not match:
        return None
    return {
        "fourcc": match.group(1),
        "description": (match.group(2) or "").strip(),
    }


def _v4l2_enum_formats(text: str) -> list[dict[str, Any]]:
    formats: list[dict[str, Any]] = []
    for match in re.finditer(r"\[\d+\]:\s*'([^']+)'\s*(?:\((.*)\))?", text):
        description = (match.group(2) or "").strip()
        formats.append(
            {
                "fourcc": match.group(1),
                "description": description,
                "compressed": "compressed" in description.lower(),
            }
        )
    return formats


def _v4l2_format_codes(formats: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("fourcc", "")).upper() for item in formats}


def _describe_v4l2_m2m_device(
    path: str,
    all_output: str,
    capture_formats_output: str,
    output_formats_output: str,
    error: str | None = None,
) -> dict[str, Any]:
    card_type = _v4l2_value(all_output, "Card type")
    entity_name = _v4l2_value(all_output, "Name")
    role_text = f"{card_type or ''} {entity_name or ''}".lower()
    role = "encoder" if "enc" in role_text else "decoder" if "dec" in role_text else "unknown"
    capture_formats = _v4l2_enum_formats(capture_formats_output)
    output_formats = _v4l2_enum_formats(output_formats_output)
    capture_codes = _v4l2_format_codes(capture_formats)
    output_codes = _v4l2_format_codes(output_formats)

    supports_h264_encode = role == "encoder" and bool(capture_codes & _V4L2_H264_FORMATS)
    supports_jpeg_encode = role == "encoder" and bool(capture_codes & _V4L2_JPEG_FORMATS)
    supports_raw_yuv_input = role == "encoder" and bool(output_codes & _V4L2_RAW_YUV_FORMATS)
    production_h264_candidate = supports_h264_encode and supports_raw_yuv_input

    if production_h264_candidate:
        reason = "V4L2 M2M exposes a hardware H.264 encoder with raw YUV input."
    elif role == "encoder" and supports_jpeg_encode and not supports_h264_encode:
        reason = "V4L2 M2M encoder is exposed, but the encoded capture side is JPEG-only."
    elif role == "encoder":
        reason = "V4L2 M2M encoder is exposed, but no H.264 encoded format is visible."
    elif role == "decoder":
        reason = "V4L2 M2M device is a decoder, not an encoder."
    elif error:
        reason = error
    else:
        reason = "V4L2 M2M role could not be classified."

    return {
        "path": path,
        "driver": _v4l2_value(all_output, "Driver name"),
        "card_type": card_type,
        "bus_info": _v4l2_value(all_output, "Bus info"),
        "entity": entity_name,
        "role": role,
        "memory_to_memory": "Memory-to-Memory" in all_output,
        "current_capture_format": _v4l2_current_format(all_output, "Format Video Capture Multiplanar"),
        "current_output_format": _v4l2_current_format(all_output, "Format Video Output Multiplanar"),
        "capture_formats": capture_formats,
        "output_formats": output_formats,
        "supports_h264_encode": supports_h264_encode,
        "supports_jpeg_encode": supports_jpeg_encode,
        "supports_raw_yuv_input": supports_raw_yuv_input,
        "production_h264_candidate": production_h264_candidate,
        "reason": reason,
        "error": error,
    }


def _probe_v4l2_m2m_devices() -> dict[str, Any]:
    v4l2_bin = shutil.which("v4l2-ctl")
    if not v4l2_bin:
        return {
            "available": False,
            "devices": [],
            "h264_encoder_ready": False,
            "reason": "v4l2-ctl is not installed.",
        }

    devices: list[dict[str, Any]] = []
    for path in _device_paths(["video*"]):
        all_result = _command_result([v4l2_bin, "-d", path, "--all"], timeout_s=2.5)
        if all_result is None:
            continue
        all_output = "\n".join(part for part in (all_result.stdout, all_result.stderr) if part)
        if "Memory-to-Memory" not in all_output:
            continue

        capture_result = _command_result([v4l2_bin, "-d", path, "--list-formats-ext"], timeout_s=2.5)
        output_result = _command_result([v4l2_bin, "-d", path, "--list-formats-out-ext"], timeout_s=2.5)
        error = None
        if all_result.returncode != 0:
            error = all_output.strip()[-500:] or f"v4l2-ctl --all returned {all_result.returncode}"
        devices.append(
            _describe_v4l2_m2m_device(
                path,
                all_output,
                "\n".join(
                    part for part in (
                        getattr(capture_result, "stdout", "") if capture_result is not None else "",
                        getattr(capture_result, "stderr", "") if capture_result is not None else "",
                    )
                    if part
                ),
                "\n".join(
                    part for part in (
                        getattr(output_result, "stdout", "") if output_result is not None else "",
                        getattr(output_result, "stderr", "") if output_result is not None else "",
                    )
                    if part
                ),
                error,
            )
        )

    h264_ready = any(item["production_h264_candidate"] for item in devices)
    return {
        "available": bool(devices),
        "devices": devices,
        "h264_encoder_ready": h264_ready,
        "reason": (
            "At least one V4L2 M2M device exposes hardware H.264 encode."
            if h264_ready
            else "No V4L2 M2M H.264 encoder is exposed by the current kernel/device tree."
        ),
    }


def _encoder_path(
    *,
    name: str,
    available: bool,
    hardware: bool,
    target_compliant: bool,
    production_ready: bool,
    reason: str,
    command: str | None = None,
    webrtc_source_factory: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "available": bool(available),
        "hardware": bool(hardware),
        "target_compliant": bool(target_compliant),
        "production_ready": bool(production_ready),
        "webrtc_source_factory": webrtc_source_factory,
        "webrtc_source_supported": bool(webrtc_source_factory),
        "command": command,
        "reason": reason,
    }


def _select_production_hardware_path(encoder_paths: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next(
        (
            path for path in encoder_paths
            if path.get("available")
            and path.get("hardware")
            and path.get("target_compliant")
            and path.get("production_ready")
            and path.get("webrtc_source_supported")
        ),
        None,
    )


def _source_pipeline_candidate(
    *,
    name: str,
    role: str,
    available: bool,
    target_compliant: bool,
    reason: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "name": name,
        "role": role,
        "available": bool(available),
        "target_compliant": bool(target_compliant),
        "reason": reason,
        **details,
    }


@lru_cache(maxsize=1)
def _probe_media_capabilities_cached(bucket: int) -> dict[str, Any]:
    del bucket
    gst_output = ""
    gst_all_output = ""
    gst_bin = shutil.which("gst-inspect-1.0")
    if gst_bin:
        gst_output = _command_output([gst_bin, "rockchipmpp"], timeout_s=3.0)
        gst_all_output = _command_output([gst_bin], timeout_s=3.0)

    ffmpeg_bins = [_probe_ffmpeg_bin(path) for path in _candidate_ffmpeg_bins()]
    selected_ffmpeg = next(
        (
            item for item in ffmpeg_bins
            if item["rkmpp_h264_encoder"] and item["runtime_h264_rkmpp"]["ok"]
        ),
        None,
    )
    selected_ffmpeg_rga = next(
        (
            item for item in ffmpeg_bins
            if item["rkrga_filters"] and item["runtime_rkrga_h264_rkmpp"]["ok"]
        ),
        None,
    )
    selected_ffmpeg_rga_crop = next(
        (
            item for item in ffmpeg_bins
            if item.get("rkrga_crop_filter")
            and item.get("runtime_rkrga_crop_h264_rkmpp", {}).get("ok")
        ),
        None,
    )

    mpp_encoder_bin = shutil.which("mpi_enc_test")
    mpp_info_bin = shutil.which("mpp_info_test")
    mpp_info = _command_output([mpp_info_bin], timeout_s=2.0) if mpp_info_bin else ""
    v4l2_m2m = _probe_v4l2_m2m_devices()
    v4l2_h264_ready = bool(v4l2_m2m["h264_encoder_ready"])
    v4l2_hw_encoder_available = any(
        item.get("role") == "encoder" for item in v4l2_m2m.get("devices", [])
    )

    gst_has_encoder = _contains_any(
        f"{gst_output}\n{gst_all_output}",
        ("mpph264enc", "mpph265enc", "mppvideoenc"),
    )
    gst_has_mpp_jpeg_decoder = _contains_any(
        f"{gst_output}\n{gst_all_output}",
        ("mppjpegdec",),
    )
    gst_has_h264_parse = _contains_any(gst_all_output, ("h264parse",))
    gst_has_jpeg_parse = _contains_any(gst_all_output, ("jpegparse",))
    gst_has_v4l2src = _contains_any(gst_all_output, ("v4l2src",))
    gst_has_appsrc = _contains_any(gst_all_output, ("appsrc",))
    gst_has_appsink = _contains_any(gst_all_output, ("appsink",))
    gst_has_explicit_rga_convert = _contains_any(
        gst_all_output,
        ("rgaconvert", "rkrgaconvert", "rkvideoconvert"),
    )
    gst_videoconvertscale_rga = _probe_gstreamer_videoconvertscale_rga(gst_bin)
    gst_rga_convert_element = (
        "rgaconvert"
        if _contains_any(gst_all_output, ("rgaconvert",))
        else "rkrgaconvert"
        if _contains_any(gst_all_output, ("rkrgaconvert",))
        else "rkvideoconvert"
        if _contains_any(gst_all_output, ("rkvideoconvert",))
        else str(gst_videoconvertscale_rga.get("element") or "")
        if gst_videoconvertscale_rga.get("ok")
        else None
    )
    gst_has_rga_convert = bool(gst_has_explicit_rga_convert or gst_videoconvertscale_rga.get("ok"))
    gst_has_software_h264 = _contains_any(gst_all_output, ("openh264enc", "x264enc"))
    ffmpeg_has_encoder = any(item["rkmpp_h264_encoder"] for item in ffmpeg_bins)
    ffmpeg_runtime_ready = selected_ffmpeg is not None
    ffmpeg_has_rkmpp_mjpeg_decoder = any(item.get("rkmpp_mjpeg_decoder") for item in ffmpeg_bins)
    ffmpeg_has_software_mjpeg_decoder = any(item.get("software_mjpeg_decoder") for item in ffmpeg_bins)
    ffmpeg_has_rga_filters = any(item["rkrga_filters"] for item in ffmpeg_bins)
    ffmpeg_rga_runtime_ready = selected_ffmpeg_rga is not None
    ffmpeg_has_rga_crop_filter = any(item.get("rkrga_crop_filter") for item in ffmpeg_bins)
    ffmpeg_rga_crop_runtime_ready = selected_ffmpeg_rga_crop is not None
    ffmpeg_rga_crop_path = "ffmpeg_vpp_rkrga" if ffmpeg_rga_crop_runtime_ready else None
    ffmpeg_single_capture_blockers = [
        reason
        for reason, missing in (
            ("ffmpeg h264_rkmpp runtime probe is not ready.", not ffmpeg_runtime_ready),
            ("ffmpeg RGA scale runtime probe is not ready.", not ffmpeg_rga_runtime_ready),
            ("ffmpeg vpp_rkrga crop runtime probe is not ready.", not ffmpeg_rga_crop_runtime_ready),
            (
                "ffmpeg has no Rockchip MJPEG decoder for the MJPG high-res camera inputs.",
                not ffmpeg_has_rkmpp_mjpeg_decoder,
            ),
        )
        if missing
    ]
    ffmpeg_single_capture_hardware_viable = bool(
        ffmpeg_runtime_ready
        and ffmpeg_rga_runtime_ready
        and ffmpeg_rga_crop_runtime_ready
        and ffmpeg_has_rkmpp_mjpeg_decoder
    )
    librga_direct_runtime = _probe_librga_direct_runtime()
    librga_direct_ready = bool(librga_direct_runtime.get("runtime_ready"))
    recommended_next_hardware_path = {
        "name": "in_process_librga_virtualaddr_scale_crop"
        if librga_direct_ready
        else "gstreamer_explicit_rga_transform",
        "component": "librga virtual-address NV12 scale/crop helper"
        if librga_direct_ready
        else "GStreamer RGA scale/crop element",
        "target_backend": GSTREAMER_TARGET_PIPELINE_NAME,
        "reason": (
            "librga completed NV12 resize, crop, and crop-scale for 720p and 4K "
            "source frames on this host. The next shippable step is to use that "
            "from the integrated GStreamer runtime for the YOLO detection branch, "
            "while keeping the current single v4l2src owner and MPP decode/encode."
            if librga_direct_ready
            else (
                "The active GStreamer backend already preserves one v4l2src owner, "
                "MPP MJPEG decode, the high-res raw ring, and MPP H.264 encode. "
                "The missing hardware piece is an explicit stable RGA transform/crop "
                "element in that source graph."
            )
        ),
        "zero_copy_dmabuf": False if librga_direct_ready else None,
        "runtime_ready": librga_direct_ready,
        "remaining_for_full_target": [
            "replace virtual-address librga staging with DMABuf-capable RGA for preview and YOLO when available",
            "feed zone-mask crop rectangles into the librga crop stage once sensor-space bounds are finalized",
        ]
        if librga_direct_ready
        else [
            "install or implement a stable GStreamer RGA transform/crop element",
        ],
        "ffmpeg_alternative_viable_for_mjpg_cameras": ffmpeg_single_capture_hardware_viable,
        "ffmpeg_alternative_blockers": ffmpeg_single_capture_blockers,
    }
    detection_crop_strategy = target_detection_crop_strategy(
        hardware_crop_runtime_available=ffmpeg_rga_crop_runtime_ready,
        hardware_crop_runtime_path=ffmpeg_rga_crop_path,
    )
    ffmpeg_webrtc_source_enabled = os.environ.get("SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    gstreamer_capture_enabled = (
        os.environ.get("SORTER_CAMERA_CAPTURE_BACKEND", "").lower()
        in {"gstreamer", "gstreamer_mpp", "mpp"}
        or os.environ.get("SORTER_ENABLE_GSTREAMER_MPP_CAPTURE", "").lower()
        in {"1", "true", "yes", "on"}
    )
    ffmpeg_webrtc_source_factory_registered = bool(
        ffmpeg_webrtc_source_enabled and _ffmpeg_rkmpp_source_factory_importable()
    )
    gstreamer_capture_source_factory_registered = bool(
        gstreamer_capture_enabled and _gstreamer_capture_source_factory_importable()
    )
    gstreamer_target_runtime = _gstreamer_target_runtime_description()
    known_rockchip_accelerators = _path_exists_map(
        [
            "/dev/dma_heap",
            "/dev/dma_heap/system",
            "/dev/dma_heap/system-dma32",
            "/dev/dma_heap/system-uncached",
            "/dev/dma_heap/system-uncached-dma32",
            "/dev/mpp_service",
            "/dev/mpp-service",
            "/dev/rkvenc",
            "/dev/rkvdec",
            "/dev/vpu_service",
            "/dev/vpu-service",
            "/dev/hevc_service",
            "/dev/hevc-service",
            "/dev/vepu",
            "/dev/h265e",
            "/dev/rga",
            "/dev/dri/renderD128",
        ]
    )
    has_mpp_node = bool(
        known_rockchip_accelerators.get("/dev/mpp_service")
        or known_rockchip_accelerators.get("/dev/mpp-service")
    )
    has_rga_node = bool(known_rockchip_accelerators.get("/dev/rga"))
    has_dma_heap_node = bool(known_rockchip_accelerators.get("/dev/dma_heap"))

    encoder_paths = [
        _encoder_path(
            name="gstreamer_rockchip_mpp",
            available=gst_has_encoder,
            hardware=True,
            target_compliant=True,
            production_ready=gst_has_encoder and gst_has_mpp_jpeg_decoder,
            webrtc_source_factory="gstreamer_capture_mpp"
            if gstreamer_capture_source_factory_registered
            else None,
            command="gst-launch-1.0 ... mpph264enc ..." if gst_has_encoder else None,
            reason=(
                "GStreamer exposes Rockchip MPP JPEG decode and H.264/H.265 encode."
                if gst_has_encoder and gst_has_mpp_jpeg_decoder
                else "GStreamer exposes a Rockchip encoder, but the MPP JPEG decoder is missing."
                if gst_has_encoder
                else "Installed rockchipmpp plugin exposes decoder elements only."
            ),
        ),
        _encoder_path(
            name="ffmpeg_rkmpp",
            available=ffmpeg_has_encoder,
            hardware=True,
            target_compliant=True,
            production_ready=ffmpeg_runtime_ready,
            webrtc_source_factory="ffmpeg_rkmpp"
            if ffmpeg_webrtc_source_factory_registered
            else None,
            command=f"{selected_ffmpeg['path']} -c:v h264_rkmpp ..." if selected_ffmpeg else None,
            reason=(
                "FFmpeg exposes h264_rkmpp and successfully encoded a smoke-test frame."
                if ffmpeg_runtime_ready
                else "FFmpeg exposes h264_rkmpp, but runtime initialization failed."
                if ffmpeg_has_encoder
                else "FFmpeg with h264_rkmpp/hevc_rkmpp is not available."
            ),
        ),
        _encoder_path(
            name="rockchip_mpp_demo",
            available=bool(mpp_encoder_bin),
            hardware=True,
            target_compliant=False,
            production_ready=False,
            command=mpp_encoder_bin,
            reason=(
                "MPP encoder demo is installed and useful for validation, but it is "
                "not a reusable browser/WebRTC streaming encoder path."
            ),
        ),
        _encoder_path(
            name="v4l2_m2m_h264",
            available=v4l2_hw_encoder_available,
            hardware=True,
            target_compliant=True,
            production_ready=v4l2_h264_ready,
            command="ffmpeg -c:v h264_v4l2m2m ..." if v4l2_h264_ready else None,
            reason=(
                "Kernel V4L2 M2M exposes a hardware H.264 encoder path."
                if v4l2_h264_ready
                else v4l2_m2m["reason"]
            ),
        ),
        _encoder_path(
            name="gstreamer_software_h264",
            available=gst_has_software_h264,
            hardware=False,
            target_compliant=False,
            production_ready=False,
            command="gst-launch-1.0 ... openh264enc/x264enc ..." if gst_has_software_h264 else None,
            reason=(
                "Software H.264 encoder is available but excluded by the target architecture."
                if gst_has_software_h264
                else "No GStreamer software H.264 encoder detected."
            ),
        ),
    ]
    production_hardware_path = _select_production_hardware_path(encoder_paths)
    python_webrtc_ready = _module_available("aiortc") and _module_available("av")
    ffmpeg_webrtc_source_runtime_ready = bool(
        production_hardware_path and production_hardware_path.get("name") == "ffmpeg_rkmpp"
    )
    gstreamer_target_ready = bool(
        gst_has_v4l2src
        and gst_has_appsrc
        and gst_has_appsink
        and gst_has_jpeg_parse
        and gst_has_mpp_jpeg_decoder
        and gst_has_encoder
        and gst_has_h264_parse
        and has_mpp_node
        and has_rga_node
        and has_dma_heap_node
    )
    gstreamer_target_contract = _target_capture_pipeline_contract("/dev/video0")
    source_pipeline_candidates = [
        _source_pipeline_candidate(
            name="shared_feed_bgr24_to_ffmpeg_rkmpp",
            role="current_staging",
            available=ffmpeg_webrtc_source_factory_registered,
            target_compliant=False,
            reason=(
                "Consumes CPU BGR24 frames from the existing single capture feed and pipes them to ffmpeg h264_rkmpp."
                if ffmpeg_webrtc_source_factory_registered
                else "Disabled because SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC is not set or the factory is not importable."
            ),
            opens_capture_device=False,
            input_from_single_capture_feed=True,
            raw_ring_branch=True,
            hardware_encode=ffmpeg_runtime_ready,
            zero_copy_dmabuf=False,
            hardware_scale_convert=False,
            hardware_crop=False,
            software_h264_fallback_allowed=False,
        ),
        _source_pipeline_candidate(
            name="forbidden_ffmpeg_v4l2_direct_to_rkmpp",
            role="forbidden_even_if_available",
            available=ffmpeg_runtime_ready,
            target_compliant=False,
            reason="Would let ffmpeg open /dev/videoN directly and compete with the backend raw-ring capture.",
            opens_capture_device=True,
            violates_single_capture=True,
            raw_ring_branch=False,
            hardware_encode=ffmpeg_runtime_ready,
            zero_copy_dmabuf=False,
            hardware_scale_convert=ffmpeg_rga_runtime_ready,
            hardware_crop=ffmpeg_rga_crop_runtime_ready,
            hardware_crop_filter="vpp_rkrga" if ffmpeg_rga_crop_runtime_ready else None,
            hardware_crop_path=ffmpeg_rga_crop_path,
            software_h264_fallback_allowed=False,
        ),
        _source_pipeline_candidate(
            name="ffmpeg_v4l2_single_capture_split_rkmpp_rkrga",
            role="alternate_target_candidate",
            available=bool(ffmpeg_runtime_ready and ffmpeg_rga_crop_runtime_ready),
            target_compliant=False,
            reason=(
                "Would be a valid direction only as a new backend that owns /dev/videoN once "
                "and feeds raw-ring, H.264, and YOLO branches itself. On this image it is not "
                "the preferred next path because FFmpeg lacks Rockchip MJPEG decode for the "
                "current high-res MJPG camera modes."
                if not ffmpeg_single_capture_hardware_viable
                else "Runtime pieces are present, but this backend is not implemented or registered."
            ),
            opens_capture_device=True,
            single_capture_pipeline=True,
            violates_single_capture=False,
            replaces_backend_capture=True,
            raw_ring_branch=True,
            h264_webrtc_branch=True,
            detection_yolo_branch=True,
            hardware_decode_mjpeg=ffmpeg_has_rkmpp_mjpeg_decoder,
            software_decode_mjpeg_available=ffmpeg_has_software_mjpeg_decoder,
            hardware_encode=ffmpeg_runtime_ready,
            hardware_scale_convert=ffmpeg_rga_runtime_ready,
            hardware_scale_convert_filter="scale_rkrga" if ffmpeg_rga_runtime_ready else None,
            hardware_crop=ffmpeg_rga_crop_runtime_ready,
            hardware_crop_filter="vpp_rkrga" if ffmpeg_rga_crop_runtime_ready else None,
            hardware_crop_path=ffmpeg_rga_crop_path,
            zero_copy_dmabuf_target=True,
            implementation_registered=False,
            target_possible_when_implemented=ffmpeg_single_capture_hardware_viable,
            blockers=ffmpeg_single_capture_blockers,
            software_h264_fallback_allowed=False,
        ),
        _source_pipeline_candidate(
            name="in_process_librga_virtualaddr_scale_crop",
            role="next_runtime_step",
            available=librga_direct_ready,
            target_compliant=False,
            reason=(
                "librga runtime-proved NV12 resize, crop, and crop-scale on virtual-address buffers. "
                "This can replace CPU scaling for the YOLO detection frame after the MPP JPEG decode appsink, "
                "but it is not the final zero-copy DMABuf preview path."
                if librga_direct_ready
                else str(librga_direct_runtime.get("reason") or "librga runtime probe is not ready.")
            ),
            opens_capture_device=False,
            input_from_single_capture_feed=True,
            raw_ring_branch=True,
            h264_webrtc_branch=False,
            detection_yolo_branch=True,
            hardware_scale_convert=librga_direct_ready,
            hardware_crop=librga_direct_ready,
            hardware_crop_path="librga_virtualaddr",
            hardware_crop_filter="improcess_crop_scale" if librga_direct_ready else None,
            zero_copy_dmabuf=False,
            input_memory="virtualaddr",
            pixel_format="NV12",
            runtime=librga_direct_runtime,
            implementation_registered=False,
            software_h264_fallback_allowed=False,
        ),
        _source_pipeline_candidate(
            name=GSTREAMER_TARGET_PIPELINE_NAME,
            role="target_candidate",
            available=gstreamer_target_ready,
            target_compliant=False,
            reason=(
                "Host has the required Rockchip MPP pieces, but the active camera backend must still be the integrated tee capture backend."
                if gstreamer_target_ready
                else "Requires v4l2src, appsrc, appsink, jpegparse, mppjpegdec, H.264 parser/encoder, and /dev/mpp_service+/dev/rga+/dev/dma_heap."
            ),
            opens_capture_device=True,
            single_capture_pipeline=True,
            capture_backend_integration_required=True,
            web_rtc_factory_only=False,
            raw_ring_branch=True,
            h264_webrtc_branch=True,
            pipeline_contract=gstreamer_target_contract,
            runtime=gstreamer_target_runtime,
            runtime_module_implemented=bool(gstreamer_target_runtime.get("implemented")),
            runtime_importable=bool(gstreamer_target_runtime.get("runtime_importable")),
            required_launch_elements=(
                gstreamer_target_contract.get("required_launch_elements", {})
                if isinstance(gstreamer_target_contract, dict)
                else {}
            ),
            required_gstreamer_elements={
                "v4l2src": gst_has_v4l2src,
                "appsrc": gst_has_appsrc,
                "appsink": gst_has_appsink,
                "jpegparse": gst_has_jpeg_parse,
                "mppjpegdec": gst_has_mpp_jpeg_decoder,
                "rockchip_rga_convert": gst_has_rga_convert,
                "rockchip_rga_convert_element": gst_rga_convert_element,
                "rockchip_mpp_h264_encoder": gst_has_encoder,
                "h264parse": gst_has_h264_parse,
            },
            required_device_nodes={
                "/dev/mpp_service": has_mpp_node,
                "/dev/rga": has_rga_node,
                "/dev/dma_heap": has_dma_heap_node,
            },
            zero_copy_dmabuf=gstreamer_target_ready,
            hardware_scale_convert=bool(gstreamer_target_ready and gst_has_rga_convert),
            hardware_scale_convert_element=gst_rga_convert_element,
            hardware_crop=False,
            hardware_crop_element=None,
            detection_crop_strategy=detection_crop_strategy,
            software_h264_fallback_allowed=False,
        ),
    ]
    source_pipeline = {
        "target": "single_capture_dmabuf_or_hardware_scale_convert_to_h264_webrtc",
        "source_factory": "gstreamer_capture_mpp"
        if gstreamer_capture_source_factory_registered
        else "ffmpeg_rkmpp"
        if ffmpeg_webrtc_source_enabled
        else None,
        "implementation": "gstreamer_v4l2_mpp_tee_h264"
        if gstreamer_capture_source_factory_registered
        else "staging_bgr24_cpu_pipe_to_h264_rkmpp"
        if ffmpeg_webrtc_source_factory_registered
        else None,
        "input_memory": "gstreamer_v4l2_dmabuf_mpp_decoded_frames"
        if gstreamer_capture_source_factory_registered
        else "cpu_bgr24_frames_from_camera_feed"
        if ffmpeg_webrtc_source_factory_registered
        else None,
        "zero_copy_dmabuf": False,
        "hardware_scale_convert_in_source": False,
        "hardware_scale_convert_element": gst_rga_convert_element,
        "hardware_crop_in_source": False,
        "hardware_crop_element": None,
        "rkrga_filters_advertised": ffmpeg_has_rga_filters,
        "rkrga_runtime_ready": ffmpeg_rga_runtime_ready,
        "rkrga_crop_filter_advertised": ffmpeg_has_rga_crop_filter,
        "rkrga_crop_runtime_ready": ffmpeg_rga_crop_runtime_ready,
        "rkrga_crop_path": ffmpeg_rga_crop_path,
        "direct_librga_runtime_ready": librga_direct_ready,
        "direct_librga_path": "librga_virtualaddr" if librga_direct_ready else None,
        "detection_crop_strategy": detection_crop_strategy,
        "candidates": source_pipeline_candidates,
        "recommended_next_hardware_path": recommended_next_hardware_path,
        "target_capture_backend_required": True,
        "target_capture_backend_integrated": False,
        "target_compliant": False,
        "reason": (
            "GStreamer capture source factory is registered; active camera backends must switch to the integrated v4l2src/MPP tee before the pipeline is target-compliant."
            if gstreamer_capture_source_factory_registered
            else "Current ffmpeg_rkmpp WebRTC source is a staging path: it consumes BGR24 CPU frames from the shared capture feed and pipes them to ffmpeg. It proves one hardware H.264 encoder per source, but it is not the final integrated MPP capture pipeline."
            if ffmpeg_webrtc_source_factory_registered
            else "No hardware H.264 WebRTC source factory is active."
        ),
    }
    try:
        from .h264_webrtc_bridge import describe_hardware_webrtc_bridge

        hardware_webrtc_bridge = describe_hardware_webrtc_bridge(
            source_factory_registered=bool(
                gstreamer_capture_source_factory_registered
                or ffmpeg_webrtc_source_factory_registered
            ),
            runtime_hardware_encoder_ready=bool(
                (gstreamer_capture_source_factory_registered and gst_has_encoder)
                or ffmpeg_webrtc_source_runtime_ready
            ),
        )
        hardware_webrtc_bridge["source_factory"] = (
            "gstreamer_capture_mpp"
            if gstreamer_capture_source_factory_registered
            else "ffmpeg_rkmpp"
            if ffmpeg_webrtc_source_enabled
            else None
        )
    except Exception:
        hardware_webrtc_bridge = {
            "implemented": False,
            "packet_track_available": False,
            "h264_packetizer_available": False,
            "integrated_with_hardware_encoder": False,
            "encoded_frame_input": "av.Packet_or_EncodedH264Frame",
            "media_track": "HardwareH264PacketTrack",
            "uses_pre_encoded_packets": True,
            "raw_frame_input_allowed": False,
            "software_h264_fallback_allowed": False,
            "source_factory": "ffmpeg_rkmpp" if ffmpeg_webrtc_source_enabled else None,
            "source_factory_registered": False,
            "runtime_hardware_encoder_ready": ffmpeg_webrtc_source_runtime_ready,
            "reason": "Hardware H.264 WebRTC packet bridge probe failed.",
        }

    return {
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "release": platform.release(),
        },
        "target": {
            "transport": "webrtc",
            "video_codec": "h264",
            "encoder": "rockchip_mpp",
        },
        "python_webrtc": {
            "ready": python_webrtc_ready,
            "aiortc": _module_available("aiortc"),
            "av": _module_available("av"),
        },
        "rockchip_mpp": {
            "installed": bool(mpp_encoder_bin or mpp_info_bin),
            "encoder_demo": mpp_encoder_bin,
            "info_demo": mpp_info_bin,
            "info": mpp_info.strip()[:2000],
        },
        "gstreamer": {
            "available": bool(gst_bin),
            "rockchipmpp": "rockchipmpp" in gst_output.lower(),
            "elements": {
                "v4l2src": gst_has_v4l2src,
                "appsrc": gst_has_appsrc,
                "appsink": gst_has_appsink,
                "jpegparse": gst_has_jpeg_parse,
                "mppjpegdec": gst_has_mpp_jpeg_decoder,
                "rockchip_rga_convert": gst_has_rga_convert,
                "rockchip_rga_convert_element": gst_rga_convert_element,
                "h264parse": gst_has_h264_parse,
            },
            "videoconvertscale_rga": gst_videoconvertscale_rga,
            "h264_encoder": gst_has_encoder,
            "software_h264_encoder": gst_has_software_h264,
            "usable_for_webrtc_encoder": gst_has_encoder,
        },
        "webrtc_hardware_bridge": hardware_webrtc_bridge,
        "gstreamer_target_runtime": gstreamer_target_runtime,
        "ffmpeg": {
            "available": any(item["available"] for item in ffmpeg_bins),
            "candidates": ffmpeg_bins,
            "rkmpp_h264_encoder": ffmpeg_has_encoder,
            "rkmpp_h264_runtime_ready": ffmpeg_runtime_ready,
            "rkmpp_mjpeg_decoder": ffmpeg_has_rkmpp_mjpeg_decoder,
            "software_mjpeg_decoder": ffmpeg_has_software_mjpeg_decoder,
            "rkrga_filters": ffmpeg_has_rga_filters,
            "rkrga_runtime_ready": ffmpeg_rga_runtime_ready,
            "rkrga_crop_filter": ffmpeg_has_rga_crop_filter,
            "rkrga_crop_runtime_ready": ffmpeg_rga_crop_runtime_ready,
        },
        "librga": librga_direct_runtime,
        "source_pipeline": source_pipeline,
        "devices": {
            "media": _device_paths(["media*"]),
            "video": _device_paths(["video*"]),
            "drm": sorted(str(path) for path in Path("/dev/dri").glob("*") if path.exists())
            if Path("/dev/dri").exists()
            else [],
            "v4l2_m2m": v4l2_m2m,
            "mpp_like": _device_paths(["*mpp*", "*rkv*", "*vpu*", "*vepu*", "*h265*"]),
            "known_rockchip_accelerators": known_rockchip_accelerators,
        },
        "encoder_paths": encoder_paths,
        "selected_encoder_path": production_hardware_path,
        "ready_for_hardware_webrtc": bool(production_hardware_path and python_webrtc_ready),
        "missing": [
            item
            for item, missing in (
                ("aiortc", not _module_available("aiortc")),
                ("av", not _module_available("av")),
                ("hardware_h264_stream_encoder", production_hardware_path is None),
            )
            if missing
        ],
    }


def probe_media_capabilities() -> dict[str, Any]:
    bucket = int(time.monotonic() // _CAPABILITY_CACHE_S)
    return _probe_media_capabilities_cached(bucket)


def _source_key(config: Any) -> str | None:
    url = getattr(config, "url", None)
    if url:
        return f"url:{url}"
    index = getattr(config, "device_index", None)
    if isinstance(index, int) and index >= 0:
        return f"video:{index}"
    return None


def _target_capture_pipeline_contract(
    device_path: str | None,
    *,
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
    input_fourcc: str = "MJPG",
) -> dict[str, Any] | None:
    if not device_path:
        return None
    try:
        return build_gstreamer_target_capture_contract(
            device_path=device_path,
            width=width,
            height=height,
            fps=fps,
            input_fourcc=input_fourcc,
        )
    except Exception as exc:
        return {
            "name": GSTREAMER_TARGET_PIPELINE_NAME,
            "device_path": device_path,
            "ok": False,
            "error": str(exc),
        }


def _frame_summary(frame: Any) -> dict[str, Any] | None:
    if frame is None or getattr(frame, "raw", None) is None:
        return None
    raw = frame.raw
    height, width = raw.shape[:2]
    timestamp = float(getattr(frame, "timestamp", 0.0) or 0.0)
    return {
        "width": int(width),
        "height": int(height),
        "timestamp": timestamp,
        "age_ms": max(0.0, (time.time() - timestamp) * 1000.0) if timestamp > 0 else None,
    }


def _mode_frame_summary(mode: Any) -> dict[str, Any] | None:
    if not isinstance(mode, dict):
        return None
    try:
        width = int(mode.get("width"))
        height = int(mode.get("height"))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    out: dict[str, Any] = {"width": width, "height": height}
    try:
        fps = int(mode.get("fps"))
    except (TypeError, ValueError):
        fps = None
    if fps is not None and fps > 0:
        out["fps"] = fps
    fourcc = mode.get("fourcc")
    if fourcc:
        out["fourcc"] = str(fourcc)
    return out


def _frame_rect_summary(frame: dict[str, Any] | None) -> dict[str, int] | None:
    if not isinstance(frame, dict):
        return None
    try:
        width = int(frame.get("width"))
        height = int(frame.get("height"))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return {"x": 0, "y": 0, "width": width, "height": height}


def _feed_coordinate_space(
    sensor_frame: dict[str, Any] | None,
    *,
    transport_frame: dict[str, Any] | None = None,
    inference_frame: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    sensor_rect = _frame_rect_summary(sensor_frame)
    if sensor_rect is None:
        return None
    return {
        "name": "sensor_frame",
        "units": "pixels",
        "origin": "top_left",
        "width": sensor_rect["width"],
        "height": sensor_rect["height"],
        "frame": "sensor_frame",
        "overlays": "sensor_frame",
        "crop": "sensor_frame",
        "transport": {
            "kind": "scaled_full_frame",
            "source_rect": dict(sensor_rect),
            "output_frame": transport_frame,
        }
        if transport_frame is not None
        else None,
        "inference": {
            "kind": "scaled_full_frame",
            "source_rect": dict(sensor_rect),
            "output_frame": inference_frame,
        }
        if inference_frame is not None
        else None,
    }


def _capture_mode_for_budget(
    capture_backend: dict[str, Any],
    latest_summary: dict[str, Any] | None,
) -> dict[str, int] | None:
    requested = capture_backend.get("requested_mode")
    if isinstance(requested, dict):
        width = requested.get("width")
        height = requested.get("height")
        fps = requested.get("fps")
    else:
        width = latest_summary.get("width") if isinstance(latest_summary, dict) else None
        height = latest_summary.get("height") if isinstance(latest_summary, dict) else None
        fps = None
    try:
        out = {"width": int(width), "height": int(height)}
    except (TypeError, ValueError):
        return None
    if out["width"] <= 0 or out["height"] <= 0:
        return None
    try:
        out["fps"] = int(fps)
    except (TypeError, ValueError):
        pass
    return out


def _capture_exceeds_preview_budget(mode: dict[str, int] | None) -> bool:
    if not isinstance(mode, dict):
        return False
    width = mode.get("width")
    height = mode.get("height")
    if not isinstance(width, int) or not isinstance(height, int):
        return False
    return width > HIGH_RES_PREVIEW_BUDGET_MAX_WIDTH or height > HIGH_RES_PREVIEW_BUDGET_MAX_HEIGHT


def _high_res_preview_hardware_ready(capture_backend: dict[str, Any]) -> bool:
    if bool(capture_backend.get("hardware_preview_scale_convert")):
        return True
    if bool(capture_backend.get("software_scale_convert_fallback")):
        return False
    if not (
        bool(capture_backend.get("target_compliant"))
        and bool(capture_backend.get("h264_webrtc_branch"))
        and bool(capture_backend.get("zero_copy_dmabuf"))
    ):
        return False
    requested = capture_backend.get("requested_mode")
    h264_mode = capture_backend.get("h264_output_mode")
    if not isinstance(requested, dict) or not isinstance(h264_mode, dict):
        return False
    try:
        return (
            int(h264_mode.get("width")) == int(requested.get("width"))
            and int(h264_mode.get("height")) == int(requested.get("height"))
        )
    except (TypeError, ValueError):
        return False


def _json_safe(value: Any) -> Any:
    """Return a JSON-serializable copy of metadata emitted by overlay code."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]

    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except Exception:
            pass

    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return _json_safe(tolist())
        except Exception:
            pass

    return str(value)


def _encoder_path_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    capabilities = payload.get("capabilities", payload)
    return {
        str(item.get("name")): item
        for item in capabilities.get("encoder_paths", [])
        if isinstance(item, dict)
    }


def _available_video_source_keys(capabilities: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for raw_path in capabilities.get("devices", {}).get("video", []):
        path = Path(str(raw_path))
        match = re.fullmatch(r"video(\d+)", path.name)
        if match:
            keys.add(f"video:{int(match.group(1))}")
    return keys


def _video_source_key_from_device_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"/dev/video(\d+)", value)
    if not match:
        return None
    return f"video:{int(match.group(1))}"


def _source_presence_summary(source: str, capabilities: dict[str, Any]) -> dict[str, Any]:
    if source == "unassigned":
        return {
            "source_exists": True,
            "source_presence": "unassigned",
            "expected_device_path": None,
            "source_presence_reason": "No physical camera is assigned.",
        }
    if source.startswith("url:"):
        return {
            "source_exists": True,
            "source_presence": "not_checked",
            "expected_device_path": None,
            "source_presence_reason": "URL/network camera sources are not checked via /dev/video.",
        }
    match = re.fullmatch(r"video:(\d+)", source)
    if not match:
        return {
            "source_exists": False,
            "source_presence": "invalid",
            "expected_device_path": None,
            "source_presence_reason": "Physical source key is not a supported video:N or url:... value.",
        }

    expected_path = f"/dev/video{int(match.group(1))}"
    exists = source in _available_video_source_keys(capabilities)
    return {
        "source_exists": exists,
        "source_presence": "present" if exists else "missing",
        "expected_device_path": expected_path,
        "source_presence_reason": (
            f"{expected_path} is present."
            if exists
            else f"{expected_path} is not present in the current /dev/video device list."
        ),
    }


def _resolve_source_presence_from_backend(
    source: str,
    capture_backend: dict[str, Any],
    capabilities: dict[str, Any],
) -> dict[str, Any] | None:
    backend_source_key = _video_source_key_from_device_path(capture_backend.get("source"))
    if backend_source_key is None:
        return None
    available = backend_source_key in _available_video_source_keys(capabilities)
    if not available:
        return None
    backend_path = str(capture_backend.get("source"))
    return {
        "source_exists": True,
        "source_presence": "resolved",
        "expected_device_path": backend_path,
        "source_presence_reason": f"{source} resolved to {backend_path} by the active capture backend.",
    }


def _source_os_handle_audit(source: str, capabilities: dict[str, Any]) -> dict[str, Any]:
    audit = capabilities.get("devices", {}).get("video_open_handles", {})
    available = bool(audit.get("available"))
    match = re.fullmatch(r"video:(\d+)", source)
    if not match:
        return {
            "available": available,
            "expected_device_path": None,
            "handle_count": 0,
            "process_count": 0,
            "processes": [],
            "not_applicable": True,
            "reason": (
                "OS video handle audit applies only to local video:N sources."
                if source != "unassigned"
                else "No physical camera is assigned."
            ),
        }

    expected_path = f"/dev/video{int(match.group(1))}"
    path_summary = audit.get("paths", {}).get(expected_path, {}) if isinstance(audit, dict) else {}
    return {
        "available": available,
        "expected_device_path": expected_path,
        "handle_count": int(path_summary.get("handle_count", 0) or 0),
        "process_count": int(path_summary.get("process_count", 0) or 0),
        "processes": path_summary.get("processes", []),
        "processes_truncated": int(path_summary.get("processes_truncated", 0) or 0),
        "not_applicable": False,
        "reason": audit.get("reason") if isinstance(audit, dict) else None,
    }


def evaluate_transport_gates(payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate whether the live media plane satisfies the target transport.

    This intentionally excludes software encoders. A green result means the
    process has Python WebRTC pieces and a production hardware H.264 path, while
    preserving the single-capture / one-encoder invariants.
    """
    capabilities = payload.get("capabilities", payload)
    encoder_paths = _encoder_path_map(payload)
    known_devices = capabilities.get("devices", {}).get("known_rockchip_accelerators", {})
    ffmpeg = capabilities.get("ffmpeg", {})
    v4l2_m2m = capabilities.get("devices", {}).get("v4l2_m2m", {})
    webrtc_bridge = capabilities.get("webrtc_hardware_bridge", {})
    source_pipeline = capabilities.get("source_pipeline", {})
    legacy_mjpeg = payload.get("legacy_transports", {}).get("mjpeg", {})
    try:
        legacy_mjpeg_clients = max(0, int(legacy_mjpeg.get("active_clients", 0) or 0))
    except Exception:
        legacy_mjpeg_clients = 0

    gates = {
        "python_webrtc": bool(capabilities.get("python_webrtc", {}).get("ready")),
        "single_capture_per_physical_source": bool(
            payload.get("invariants", {}).get("single_capture_per_physical_source", True)
        ),
        "one_encoder_per_physical_source_target": bool(
            payload.get("invariants", {}).get("one_encoder_per_physical_source_target", True)
        ),
        "ffmpeg_rkmpp_advertised": bool(ffmpeg.get("rkmpp_h264_encoder")),
        "ffmpeg_rkmpp_runtime": bool(ffmpeg.get("rkmpp_h264_runtime_ready")),
        "ffmpeg_rkrga_filters_advertised": bool(ffmpeg.get("rkrga_filters")),
        "ffmpeg_rkrga_runtime": bool(ffmpeg.get("rkrga_runtime_ready")),
        "ffmpeg_rkrga_crop_filter_advertised": bool(ffmpeg.get("rkrga_crop_filter")),
        "ffmpeg_rkrga_crop_runtime": bool(ffmpeg.get("rkrga_crop_runtime_ready")),
        "v4l2_m2m_h264_runtime": bool(v4l2_m2m.get("h264_encoder_ready")),
        "mpp_service_node": bool(
            known_devices.get("/dev/mpp_service") or known_devices.get("/dev/mpp-service")
        ),
        "rga_node": bool(known_devices.get("/dev/rga")),
        "dma_heap_node": bool(known_devices.get("/dev/dma_heap")),
        "drm_render_node": bool(known_devices.get("/dev/dri/renderD128")),
        "production_hardware_encoder": bool(capabilities.get("selected_encoder_path")),
        "hardware_h264_source_factory_registered": bool(
            webrtc_bridge.get("source_factory_registered")
        ),
        "webrtc_hardware_bridge_implemented": bool(webrtc_bridge.get("implemented")),
        "hardware_scale_convert_source_pipeline": bool(
            source_pipeline.get("hardware_scale_convert_in_source")
        ),
        "hardware_crop_source_pipeline": bool(source_pipeline.get("hardware_crop_in_source")),
        "active_high_res_capture_requires_scale": bool(
            source_pipeline.get("active_high_res_capture_requires_scale")
        ),
        "active_high_res_scale_ready": bool(
            source_pipeline.get("active_high_res_scale_ready", True)
        ),
        "active_high_res_preview_hardware_ready": bool(
            source_pipeline.get(
                "active_high_res_preview_hardware_ready",
                source_pipeline.get("active_high_res_scale_ready", True),
            )
        ),
        "zero_copy_source_pipeline": bool(source_pipeline.get("zero_copy_dmabuf")),
        "source_pipeline_target_compliant": bool(source_pipeline.get("target_compliant")),
        "target_capture_backend_integrated": bool(
            payload.get("invariants", {}).get("target_capture_backend_integrated", False)
        ),
        "os_video_handle_audit_available": bool(
            capabilities.get("devices", {}).get("video_open_handles", {}).get("available")
        ),
        "legacy_mjpeg_clients_absent": legacy_mjpeg_clients == 0,
        "assigned_camera_sources_exist": bool(
            payload.get("invariants", {}).get("assigned_physical_sources_exist", True)
        ),
    }
    gates["target_ready"] = bool(capabilities.get("ready_for_hardware_webrtc")) and gates[
        "production_hardware_encoder"
    ]
    gates["target_architecture_compliant"] = bool(
        gates["target_ready"]
        and gates["single_capture_per_physical_source"]
        and gates["one_encoder_per_physical_source_target"]
        and gates["hardware_h264_source_factory_registered"]
        and gates["webrtc_hardware_bridge_implemented"]
        and gates["source_pipeline_target_compliant"]
        and gates["target_capture_backend_integrated"]
        and gates["active_high_res_preview_hardware_ready"]
        and gates["legacy_mjpeg_clients_absent"]
        and gates["assigned_camera_sources_exist"]
    )

    blockers: list[str] = []
    migration_warnings: list[str] = []
    if not gates["python_webrtc"]:
        blockers.append("Python WebRTC dependencies are missing.")
    if not gates["production_hardware_encoder"]:
        blockers.append(
            "No production H.264 hardware encoder path with a WebRTC source factory is selected."
        )
    if gates["target_ready"] and not gates["hardware_h264_source_factory_registered"]:
        blockers.append(
            "Hardware H.264 source factory is not registered "
            "(set SORTER_CAMERA_CAPTURE_BACKEND=gstreamer_mpp or SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC=1)."
        )
    elif gates["target_ready"] and not gates["webrtc_hardware_bridge_implemented"]:
        blockers.append("Hardware H.264 WebRTC encoded-frame bridge is not implemented.")
    if gates["ffmpeg_rkmpp_advertised"] and not gates["ffmpeg_rkmpp_runtime"]:
        blockers.append("ffmpeg exposes h264_rkmpp, but the runtime encode probe fails.")
    if gates["ffmpeg_rkrga_filters_advertised"] and not gates["ffmpeg_rkrga_runtime"]:
        blockers.append("ffmpeg exposes Rockchip RGA filters, but the RGA+RKMPP runtime probe fails.")
    if gates["ffmpeg_rkrga_crop_filter_advertised"] and not gates["ffmpeg_rkrga_crop_runtime"]:
        migration_warnings.append(
            "ffmpeg exposes vpp_rkrga crop, but the RGA crop+RKMPP runtime probe fails."
        )
    if not gates["mpp_service_node"]:
        blockers.append("Rockchip MPP codec device node is missing (/dev/mpp_service).")
    if not gates["rga_node"]:
        blockers.append("Rockchip RGA device node is missing (/dev/rga).")
    if not gates["dma_heap_node"]:
        blockers.append("DMA heap allocator node is missing (/dev/dma_heap).")
    if not gates["single_capture_per_physical_source"]:
        blockers.append("At least one physical camera has more than one capture instance.")
    if gates["target_ready"] and not gates["source_pipeline_target_compliant"]:
        reason = source_pipeline.get("reason")
        blockers.append(
            "Hardware WebRTC source pipeline is still staging, not the final integrated MPP capture target."
            if not isinstance(reason, str) or not reason
            else reason
        )
    if (
        gates["target_ready"]
        and gates["active_high_res_capture_requires_scale"]
        and not gates["active_high_res_preview_hardware_ready"]
    ):
        sources = source_pipeline.get("active_high_res_sources")
        suffix = f" ({', '.join(str(item) for item in sources)})" if isinstance(sources, list) and sources else ""
        blockers.append(
            "Active high-res camera capture exceeds the preview budget, but the source pipeline has neither hardware preview scale/crop nor an unscaled hardware H.264 preview path ready"
            + suffix
            + "."
        )
    if not gates["target_capture_backend_integrated"]:
        blockers.append(
            "Active camera capture backend is not the integrated v4l2src/MPP tee raw-ring/H.264 target."
        )
    if not gates["assigned_camera_sources_exist"]:
        missing_sources = [
            str(item.get("source"))
            for item in payload.get("physical_sources", [])
            if item.get("source") != "unassigned" and item.get("source_exists") is False
        ]
        if missing_sources:
            blockers.append(
                "Assigned camera source is missing on this host: "
                + ", ".join(sorted(missing_sources))
                + "."
            )
        else:
            blockers.append("At least one assigned camera source is missing on this host.")
    if not gates["legacy_mjpeg_clients_absent"]:
        migration_warnings.append(
            f"Legacy per-client MJPEG transport is active ({legacy_mjpeg_clients} client"
            f"{'' if legacy_mjpeg_clients == 1 else 's'})."
        )

    return {
        "gates": gates,
        "blockers": blockers,
        "migration_warnings": migration_warnings,
        "legacy_mjpeg_active_clients": legacy_mjpeg_clients,
        "encoder_paths": encoder_paths,
        "selected_encoder_path": capabilities.get("selected_encoder_path"),
    }


def describe_feed_metadata(
    role: str,
    feed: Any,
    *,
    requested_role: str | None = None,
    config_role: str | None = None,
    physical_source: str | None = None,
    exclude_categories: frozenset[str] | None = None,
    crop: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe the control-plane payload for one camera feed.

    This intentionally emits metadata only. Pixel transport belongs to the
    media plane; overlays, zones, detections, and debug labels should ride a
    WebSocket/WebRTC DataChannel payload shaped like this one.
    """
    device = getattr(feed, "device", None)
    latest = getattr(device, "latest_frame", None)
    describe_overlays = getattr(feed, "describe_overlays", None)
    overlays: list[dict[str, Any]] = []
    if callable(describe_overlays):
        try:
            described = describe_overlays(exclude_categories=exclude_categories)
        except TypeError:
            described = describe_overlays(exclude_categories)
        except Exception:
            described = []
        if isinstance(described, list):
            overlays = [item for item in described if isinstance(item, dict)]

    latest_summary = _frame_summary(latest)
    capture_backend_fn = getattr(device, "describe_capture_backend", None)
    capture_backend: dict[str, Any] = {}
    if callable(capture_backend_fn):
        try:
            described_backend = capture_backend_fn()
        except Exception:
            described_backend = {}
        if isinstance(described_backend, dict):
            capture_backend = described_backend
    transport_frame = _mode_frame_summary(capture_backend.get("h264_output_mode"))
    inference_frame = _mode_frame_summary(capture_backend.get("detection_output_mode"))
    source = physical_source or _source_key(getattr(device, "config", None))
    return {
        "message_type": CAMERA_METADATA_MESSAGE_TYPE,
        "schema_version": CAMERA_METADATA_SCHEMA_VERSION,
        "ok": True,
        "role": str(role),
        "requested_role": str(requested_role or role),
        "config_role": str(config_role or role),
        "physical_source": source,
        "frame": latest_summary,
        "coordinate_space": _json_safe(
            _feed_coordinate_space(
                latest_summary,
                transport_frame=transport_frame,
                inference_frame=inference_frame,
            )
        ),
        "transport_frame": _json_safe(transport_frame),
        "inference_frame": _json_safe(inference_frame),
        "ring_buffer_depth": int(getattr(device, "ring_buffer_depth", 0) or 0),
        "crop": _json_safe(crop),
        "overlays": _json_safe(overlays),
        "overlay_count": len(overlays),
        "control_plane": {
            "transport_target": "websocket_or_webrtc_datachannel",
            "browser_side_render_target": True,
            "payload_contains_pixels": False,
            "frame_timestamp_field": "frame.timestamp",
            "data_channel": camera_metadata_data_channel_spec(),
        },
    }


def _legacy_mjpeg_summary(legacy_streams: dict[str, Any] | None = None) -> dict[str, Any]:
    streams: list[dict[str, Any]] = []
    for key, raw in (legacy_streams or {}).items():
        if not isinstance(raw, dict):
            continue
        clients_raw = raw.get("active_clients", raw.get("clients", 0))
        try:
            active_clients = max(0, int(clients_raw))
        except Exception:
            active_clients = 0
        if active_clients <= 0:
            continue
        item = {
            "key": str(key),
            **{
                str(k): _json_safe(v)
                for k, v in raw.items()
                if k not in {"active_clients", "clients"}
            },
            "active_clients": active_clients,
        }
        streams.append(item)
    streams.sort(
        key=lambda item: (
            str(item.get("physical_source") or ""),
            str(item.get("role") or ""),
            str(item.get("stack") or ""),
            str(item.get("key") or ""),
        )
    )
    active_clients = sum(int(item["active_clients"]) for item in streams)
    return {
        "mjpeg": {
            "active_clients": active_clients,
            "streams": streams,
            "per_client_encode": True,
            "per_client_encode_active": active_clients > 0,
            "target_replacement": "webrtc_media_track",
            "migration_status": "legacy_not_target",
        }
    }


def describe_media_plane(
    camera_service: Any | None,
    *,
    legacy_mjpeg_streams: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe the active camera media topology.

    The result is intentionally transport-agnostic. The current implementation
    still serves MJPEG elsewhere, but this shape models the intended one-capture
    / one-encoder-per-physical-source media plane.
    """
    capabilities = _with_live_video_handle_audit(probe_media_capabilities())
    selected_encoder_path = capabilities.get("selected_encoder_path")
    legacy_transports = _legacy_mjpeg_summary(legacy_mjpeg_streams)
    if camera_service is None:
        return {
            "ok": True,
            "active": False,
            "target": capabilities["target"],
            "capabilities": capabilities,
            "physical_sources": [],
            "encoder_sessions": [],
            "legacy_transports": legacy_transports,
            "roles": {},
            "invariants": {
                "single_capture_per_physical_source": True,
                "one_encoder_per_physical_source_target": True,
                "assigned_physical_sources_exist": True,
                "target_capture_backend_integrated": True,
            },
        }

    devices_by_id: dict[int, Any] = {}
    source_to_device_ids: dict[str, set[int]] = {}
    roles: dict[str, dict[str, Any]] = {}

    for role, feed in getattr(camera_service, "feeds", {}).items():
        device = getattr(feed, "device", None)
        if device is None:
            continue
        devices_by_id[id(device)] = device
        source = _source_key(getattr(device, "config", None)) or "unassigned"
        source_to_device_ids.setdefault(source, set()).add(id(device))
        roles[str(role)] = {
            "physical_source": source,
            "device_id": id(device),
            "health": str(getattr(getattr(feed, "health", None), "value", getattr(feed, "health", ""))),
        }

    physical_sources: list[dict[str, Any]] = []
    encoder_sessions: list[dict[str, Any]] = []
    for source, device_ids in sorted(source_to_device_ids.items()):
        role_names = sorted(role for role, info in roles.items() if info["physical_source"] == source)
        device = devices_by_id[next(iter(device_ids))]
        latest = getattr(device, "latest_frame", None)
        capture_backend_fn = getattr(device, "describe_capture_backend", None)
        capture_backend = (
            capture_backend_fn()
            if callable(capture_backend_fn)
            else {
                "implementation": "unknown",
                "target_compliant": False,
                "reason": "Camera device does not expose capture backend metadata.",
            }
        )
        source_presence = _source_presence_summary(source, capabilities)
        resolved_presence = (
            _resolve_source_presence_from_backend(source, capture_backend, capabilities)
            if isinstance(capture_backend, dict)
            else None
        )
        if resolved_presence is not None:
            source_presence = resolved_presence
        audit_source = (
            _video_source_key_from_device_path(capture_backend.get("source"))
            if isinstance(capture_backend, dict)
            else None
        ) or source
        os_handle_audit = _source_os_handle_audit(audit_source, capabilities)
        if audit_source != source:
            os_handle_audit["logical_source"] = source
        latest_summary = _frame_summary(latest)
        capture_profile = _capture_mode_for_budget(capture_backend, latest_summary)
        capture_exceeds_preview_budget = _capture_exceeds_preview_budget(capture_profile)
        encoder_status = (
            "planned_ready"
            if source != "unassigned" and selected_encoder_path is not None
            else "blocked_missing_hardware_h264_path"
            if source != "unassigned"
            else "unassigned"
        )
        physical_sources.append(
            {
                "source": source,
                "roles": role_names,
                "capture_instances": len(device_ids),
                "encoder_instances_target": 1 if source != "unassigned" else 0,
                "ring_buffer_depth": int(getattr(device, "ring_buffer_depth", 0) or 0),
                "latest_frame": latest_summary,
                "capture_profile": {
                    **(capture_profile or {}),
                    "exceeds_preview_budget": bool(capture_exceeds_preview_budget),
                    "preview_budget": {
                        "max_width": HIGH_RES_PREVIEW_BUDGET_MAX_WIDTH,
                        "max_height": HIGH_RES_PREVIEW_BUDGET_MAX_HEIGHT,
                    },
                }
                if capture_profile is not None
                else None,
                "capture_backend": capture_backend,
                "target_capture_pipeline_contract": _target_capture_pipeline_contract(
                    source_presence.get("expected_device_path"),
                    width=int(latest_summary["width"]) if latest_summary else 1280,
                    height=int(latest_summary["height"]) if latest_summary else 720,
                ),
                "os_handle_audit": os_handle_audit,
                **source_presence,
            }
        )
        if source != "unassigned":
            encoder_sessions.append(
                {
                    "session_key": source,
                    "physical_source": source,
                    "roles": role_names,
                    "codec": "h264",
                    "transport_target": "webrtc_media_track",
                    "encoder_instances_target": 1,
                    "status": encoder_status,
                    "selected_encoder_path": selected_encoder_path,
                    "shares_capture_thread": len(device_ids) <= 1,
                }
            )

    single_capture_ok = all(
        source == "unassigned" or item["capture_instances"] <= 1 for item in physical_sources
    )
    one_encoder_target_ok = all(
        session["encoder_instances_target"] == 1 for session in encoder_sessions
    )
    target_capture_backend_integrated = all(
        source == "unassigned" or bool(item.get("capture_backend", {}).get("target_compliant"))
        for item in physical_sources
    )
    active_hardware_scale_convert = any(
        source != "unassigned" and bool(item.get("capture_backend", {}).get("hardware_scale_convert"))
        for item in physical_sources
    )
    active_hardware_preview_scale_convert = any(
        source != "unassigned"
        and bool(
            item.get("capture_backend", {}).get(
                "hardware_preview_scale_convert",
                item.get("capture_backend", {}).get("hardware_scale_convert"),
            )
        )
        for item in physical_sources
    )
    active_hardware_detection_scale_convert = any(
        source != "unassigned"
        and bool(item.get("capture_backend", {}).get("hardware_detection_scale_convert"))
        for item in physical_sources
    )
    active_hardware_crop = any(
        source != "unassigned" and bool(item.get("capture_backend", {}).get("hardware_crop"))
        for item in physical_sources
    )
    active_hardware_detection_crop_capable = any(
        source != "unassigned"
        and bool(item.get("capture_backend", {}).get("hardware_detection_crop_capable"))
        for item in physical_sources
    )
    active_capabilities = dict(capabilities)
    source_pipeline = dict(active_capabilities.get("source_pipeline", {}))
    active_hardware_scale_convert_element = next(
        (
            item.get("capture_backend", {}).get("hardware_scale_convert_element")
            for item in physical_sources
            if item.get("source") != "unassigned"
            and item.get("capture_backend", {}).get("hardware_scale_convert_element")
        ),
        source_pipeline.get("hardware_scale_convert_element"),
    )
    active_scale_convert_element = next(
        (
            item.get("capture_backend", {}).get("scale_convert_element")
            for item in physical_sources
            if item.get("source") != "unassigned"
            and item.get("capture_backend", {}).get("scale_convert_element")
        ),
        source_pipeline.get("scale_convert_element")
        or active_hardware_scale_convert_element,
    )
    active_software_scale_fallback = any(
        source != "unassigned"
        and bool(item.get("capture_backend", {}).get("software_scale_convert_fallback"))
        for item in physical_sources
    )
    active_hardware_crop_element = next(
        (
            item.get("capture_backend", {}).get("hardware_crop_element")
            for item in physical_sources
            if item.get("source") != "unassigned"
            and item.get("capture_backend", {}).get("hardware_crop_element")
        ),
        source_pipeline.get("hardware_crop_element"),
    )
    active_high_res_sources = [
        str(item.get("source"))
        for item in physical_sources
        if item.get("source") != "unassigned"
        and isinstance(item.get("capture_profile"), dict)
        and bool(item["capture_profile"].get("exceeds_preview_budget"))
    ]
    active_high_res_scale_ready = all(
        bool(
            item.get("capture_backend", {}).get(
                "hardware_preview_scale_convert",
                item.get("capture_backend", {}).get("hardware_scale_convert"),
            )
        )
        for item in physical_sources
        if item.get("source") in active_high_res_sources
    )
    active_high_res_preview_hardware_ready = all(
        _high_res_preview_hardware_ready(item.get("capture_backend", {}))
        for item in physical_sources
        if item.get("source") in active_high_res_sources
    )
    assigned_sources_exist = all(
        source == "unassigned" or bool(item.get("source_exists"))
        for item in physical_sources
    )
    source_pipeline["target_capture_backend_integrated"] = target_capture_backend_integrated
    target_pipeline_candidate_ready = any(
        isinstance(candidate, dict)
        and candidate.get("name") == GSTREAMER_TARGET_PIPELINE_NAME
        and candidate.get("available")
        for candidate in source_pipeline.get("candidates", [])
    )
    if (
        target_capture_backend_integrated
        and target_pipeline_candidate_ready
        and source_pipeline.get("target_capture_backend_required")
    ):
        source_pipeline["implementation"] = GSTREAMER_TARGET_PIPELINE_NAME
        source_pipeline["input_memory"] = "dmabuf_or_hardware_decoded_frames"
        source_pipeline["zero_copy_dmabuf"] = True
        source_pipeline["hardware_scale_convert_in_source"] = active_hardware_scale_convert
        source_pipeline["hardware_preview_scale_convert_in_source"] = active_hardware_preview_scale_convert
        source_pipeline["hardware_detection_scale_convert_in_source"] = active_hardware_detection_scale_convert
        source_pipeline["hardware_scale_convert_element"] = active_hardware_scale_convert_element
        source_pipeline["scale_convert_element"] = active_scale_convert_element
        source_pipeline["software_scale_convert_fallback"] = active_software_scale_fallback
        source_pipeline["hardware_crop_in_source"] = active_hardware_crop
        source_pipeline["hardware_detection_crop_capable"] = active_hardware_detection_crop_capable
        source_pipeline["hardware_crop_element"] = active_hardware_crop_element
        source_pipeline["detection_crop_strategy"] = target_detection_crop_strategy(
            active_media_pipeline_crop=active_hardware_crop,
            hardware_crop_element=active_hardware_crop_element,
            hardware_crop_runtime_available=bool(source_pipeline.get("rkrga_crop_runtime_ready")),
            hardware_crop_runtime_path=source_pipeline.get("rkrga_crop_path"),
        )
        source_pipeline["preview_budget"] = {
            "max_width": HIGH_RES_PREVIEW_BUDGET_MAX_WIDTH,
            "max_height": HIGH_RES_PREVIEW_BUDGET_MAX_HEIGHT,
        }
        source_pipeline["active_high_res_sources"] = active_high_res_sources
        source_pipeline["active_high_res_capture_requires_scale"] = bool(active_high_res_sources)
        source_pipeline["active_high_res_scale_ready"] = bool(active_high_res_scale_ready)
        source_pipeline["active_high_res_preview_hardware_ready"] = bool(
            active_high_res_preview_hardware_ready
        )
        source_pipeline["target_compliant"] = True
        source_pipeline["reason"] = (
            "Active capture backend owns a single v4l2src tee with raw-ring, hardware scale, and H.264 branches."
            if active_hardware_scale_convert
            else "Active capture backend owns a single v4l2src tee with raw-ring and H.264 branches; scale uses the configured converter as a software fallback because no stable GStreamer RGA converter is active."
            if active_software_scale_fallback
            else "Active capture backend owns a single v4l2src tee with raw-ring and H.264 branches; hardware scale is not active in the source path yet."
        )
    elif target_capture_backend_integrated and source_pipeline.get("target_capture_backend_required"):
        source_pipeline["target_compliant"] = False
        source_pipeline["reason"] = "Capture backend is integrated, but the host is missing required GStreamer/Rockchip target pipeline pieces."
    active_capabilities["source_pipeline"] = source_pipeline

    return {
        "ok": True,
        "active": True,
        "target": active_capabilities["target"],
        "capabilities": active_capabilities,
        "physical_sources": physical_sources,
        "encoder_sessions": encoder_sessions,
        "legacy_transports": legacy_transports,
        "roles": roles,
        "invariants": {
            "single_capture_per_physical_source": single_capture_ok,
            "one_encoder_per_physical_source_target": one_encoder_target_ok,
            "assigned_physical_sources_exist": assigned_sources_exist,
            "target_capture_backend_integrated": target_capture_backend_integrated,
            "browser_side_overlays_target": True,
        },
    }
