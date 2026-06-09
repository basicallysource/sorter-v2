#!/usr/bin/env python3
"""Probe whether the host satisfies the target camera transport stack.

Exit codes:
  0: target camera transport architecture is compliant
  1: probe failed
  2: probe succeeded, but the target transport architecture is not ready
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
DEFAULT_IMAGE_CONTRACT_PATH = Path("/etc/sorteros/camera-transport-target.json")
DEFAULT_FIRSTBOOT_STATUS_PATH = Path("/var/lib/sorteros/camera-transport-status.json")
BACKEND_DIR = Path(__file__).resolve().parents[1]
SOFTWARE_DIR = BACKEND_DIR.parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _command_output(args: list[str], timeout_s: float = 3.0) -> str:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except Exception as exc:
        return f"error: {exc}"
    return "\n".join(part for part in (result.stdout, result.stderr) if part).strip()


def _load_env_file(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        if not all(part.isalnum() for part in key.split("_")):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def _load_sorter_env() -> None:
    _load_env_file(SOFTWARE_DIR / ".env")
    _load_env_file(BACKEND_DIR / ".env")


def _os_release() -> dict[str, str]:
    path = Path("/etc/os-release")
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in raw_line or raw_line.startswith("#"):
            continue
        key, value = raw_line.split("=", 1)
        result[key] = value.strip().strip('"')
    return result


def _dpkg_package_versions(names: list[str]) -> dict[str, str | None]:
    if not names:
        return {}
    output = _command_output(["dpkg-query", "-W", *names], timeout_s=3.0)
    result: dict[str, str | None] = {name: None for name in names}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            result[parts[0]] = parts[1]
    return result


def _sorteros_image_contract(path: Path = DEFAULT_IMAGE_CONTRACT_PATH) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _sorteros_camera_transport_status(
    path: Path = DEFAULT_FIRSTBOOT_STATUS_PATH,
) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _fetch_backend_media_plane(base_url: str) -> dict[str, Any] | None:
    url = f"{base_url.rstrip('/')}/api/cameras/media-plane"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def _fetch_backend_webrtc_sessions(base_url: str) -> dict[str, Any] | None:
    url = f"{base_url.rstrip('/')}/api/cameras/webrtc/sessions"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _local_media_plane_payload() -> dict[str, Any]:
    from vision.media_plane import describe_media_plane

    return describe_media_plane(None)


def evaluate_transport_gates(payload: dict[str, Any]) -> dict[str, Any]:
    from vision.media_plane import evaluate_transport_gates as _evaluate_transport_gates

    return _evaluate_transport_gates(payload)


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    _load_sorter_env()
    backend_payload = None if args.local else _fetch_backend_media_plane(args.backend_url)
    backend_webrtc_sessions = None if args.local else _fetch_backend_webrtc_sessions(args.backend_url)
    source = "backend" if backend_payload is not None else "local"
    media_plane = backend_payload if backend_payload is not None else _local_media_plane_payload()

    return {
        "source": source,
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "kernel": platform.release(),
            "euid": os.geteuid() if hasattr(os, "geteuid") else None,
            "os_release": _os_release(),
            "sorteros_image_contract": _sorteros_image_contract(),
            "sorteros_camera_transport_status": _sorteros_camera_transport_status(),
            "packages": _dpkg_package_versions(
                [
                    "linux-image-rockchip64",
                    "linux-dtb-rockchip64",
                    "rockchip-multimedia-config",
                    "ffmpeg",
                    "librockchip-mpp1",
                    "librockchip-mpp-dev",
                    "librockchip-vpu0",
                    "librga2",
                    "librga-dev",
                    "libv4l-rkmpp",
                    "gstreamer1.0-rockchip1",
                    "v4l-utils",
                ]
            ),
        },
        "media_plane": media_plane,
        "webrtc_sessions": backend_webrtc_sessions,
        "evaluation": evaluate_transport_gates(media_plane),
    }


def _print_text_report(report: dict[str, Any]) -> None:
    host = report["host"]
    os_release = host.get("os_release", {})
    media_plane = report["media_plane"]
    capabilities = media_plane.get("capabilities", media_plane)
    evaluation = report["evaluation"]
    gates = evaluation["gates"]

    print("Camera Transport Stack Probe")
    print(f"  Source: {report['source']}")
    print(f"  OS: {os_release.get('PRETTY_NAME', 'unknown')}")
    print(f"  Kernel: {host.get('kernel')} ({host.get('machine')})")
    print(f"  EUID: {host.get('euid')}")
    print()
    print("Gates")
    for name, value in gates.items():
        marker = "OK" if value else "--"
        print(f"  {marker} {name}")
    print()
    print("Target Result")
    print(f"  target_ready: {gates.get('target_ready')}")
    print(f"  target_architecture_compliant: {gates.get('target_architecture_compliant')}")
    print(f"  legacy_mjpeg_active_clients: {evaluation.get('legacy_mjpeg_active_clients', 0)}")
    print()
    contract = host.get("sorteros_image_contract")
    if contract:
        print("SorterOS Image Contract")
        print(f"  profile: {contract.get('profile')}")
        print(f"  image_version: {contract.get('image_version')}")
        print(f"  branch: {contract.get('branch')}")
        required_machine = contract.get("required_machine")
        if required_machine:
            print(f"  required_machine: {required_machine}")
        kernel_patterns = [
            str(pattern)
            for pattern in contract.get("required_kernel_release_patterns", [])
            if isinstance(pattern, str)
        ]
        if kernel_patterns:
            print(f"  required_kernel_release_patterns: {', '.join(kernel_patterns)}")
        backend_env = contract.get("backend_env") if isinstance(contract.get("backend_env"), dict) else {}
        if backend_env:
            print(f"  backend_env: {', '.join(sorted(str(key) for key in backend_env))}")
        nodes = [
            str(node)
            for node in contract.get("required_device_nodes", [])
            if isinstance(node, str)
        ]
        if nodes:
            print("  required_device_nodes:")
            for node in nodes:
                print(f"    - {node}")
        acceptance_commands = [
            str(command)
            for command in contract.get("acceptance_probe_commands", [])
            if isinstance(command, str)
        ]
        if acceptance_commands:
            print("  acceptance_probe_commands:")
            for command in acceptance_commands:
                print(f"    - {command}")
        print()
    firstboot_status = host.get("sorteros_camera_transport_status")
    if firstboot_status:
        print("SorterOS Camera Transport Firstboot Status")
        print(f"  ok: {firstboot_status.get('ok')}")
        print(f"  profile: {firstboot_status.get('profile')}")
        platform_info = firstboot_status.get("platform")
        if isinstance(platform_info, dict):
            print(f"  kernel_release: {platform_info.get('kernel_release')}")
            print(f"  machine: {platform_info.get('machine')}")
        if firstboot_status.get("machine_mismatch"):
            print(f"  machine_mismatch: {firstboot_status.get('machine_mismatch')}")
        print(f"  target_ready: {firstboot_status.get('target_ready')}")
        print(
            "  target_architecture_compliant: "
            f"{firstboot_status.get('target_architecture_compliant')}"
        )
        missing_kernel_patterns = firstboot_status.get("missing_kernel_release_patterns")
        if isinstance(missing_kernel_patterns, list) and missing_kernel_patterns:
            print("  missing_kernel_release_patterns:")
            for pattern in missing_kernel_patterns:
                print(f"    - {pattern}")
        missing_nodes = firstboot_status.get("missing_device_nodes")
        if isinstance(missing_nodes, list) and missing_nodes:
            print("  missing_device_nodes:")
            for node in missing_nodes:
                print(f"    - {node}")
        missing_packages = firstboot_status.get("missing_packages")
        if isinstance(missing_packages, list) and missing_packages:
            print("  missing_packages:")
            for package in missing_packages:
                print(f"    - {package}")
        missing_gates = firstboot_status.get("missing_runtime_gates")
        if isinstance(missing_gates, list) and missing_gates:
            print("  missing_runtime_gates:")
            for gate in missing_gates:
                print(f"    - {gate}")
        print()
    print("Encoder Paths")
    for item in capabilities.get("encoder_paths", []):
        marker = "READY" if item.get("production_ready") else "seen" if item.get("available") else "--"
        print(f"  {marker:5} {item.get('name')}: {item.get('reason')}")
    print()
    bridge = capabilities.get("webrtc_hardware_bridge", {})
    if bridge:
        print("WebRTC Hardware Bridge")
        print(f"  implemented: {bridge.get('implemented')}")
        print(f"  packet_track_available: {bridge.get('packet_track_available')}")
        print(f"  h264_packetizer_available: {bridge.get('h264_packetizer_available')}")
        print(f"  integrated_with_hardware_encoder: {bridge.get('integrated_with_hardware_encoder')}")
        print(f"  source_factory: {bridge.get('source_factory')}")
        print(f"  source_factory_registered: {bridge.get('source_factory_registered')}")
        print(f"  runtime_hardware_encoder_ready: {bridge.get('runtime_hardware_encoder_ready')}")
        print(f"  raw_frame_input_allowed: {bridge.get('raw_frame_input_allowed')}")
        print(f"  software_h264_fallback_allowed: {bridge.get('software_h264_fallback_allowed')}")
        if bridge.get("reason"):
            print(f"  reason: {bridge.get('reason')}")
        print()
    source_pipeline = capabilities.get("source_pipeline", {})
    if source_pipeline:
        print("Source Pipeline")
        print(f"  implementation: {source_pipeline.get('implementation')}")
        print(f"  input_memory: {source_pipeline.get('input_memory')}")
        print(f"  zero_copy_dmabuf: {source_pipeline.get('zero_copy_dmabuf')}")
        print(
            "  hardware_scale_convert_in_source: "
            f"{source_pipeline.get('hardware_scale_convert_in_source')}"
        )
        print(f"  hardware_scale_convert_element: {source_pipeline.get('hardware_scale_convert_element')}")
        print(f"  hardware_crop_in_source: {source_pipeline.get('hardware_crop_in_source')}")
        print(f"  hardware_crop_element: {source_pipeline.get('hardware_crop_element')}")
        print(f"  preview_budget: {source_pipeline.get('preview_budget')}")
        print(
            "  active_high_res_capture_requires_scale: "
            f"{source_pipeline.get('active_high_res_capture_requires_scale')}"
        )
        print(f"  active_high_res_scale_ready: {source_pipeline.get('active_high_res_scale_ready')}")
        print(f"  active_high_res_sources: {source_pipeline.get('active_high_res_sources')}")
        print(f"  rkrga_filters_advertised: {source_pipeline.get('rkrga_filters_advertised')}")
        print(f"  rkrga_runtime_ready: {source_pipeline.get('rkrga_runtime_ready')}")
        print(f"  rkrga_crop_filter_advertised: {source_pipeline.get('rkrga_crop_filter_advertised')}")
        print(f"  rkrga_crop_runtime_ready: {source_pipeline.get('rkrga_crop_runtime_ready')}")
        print(f"  rkrga_crop_path: {source_pipeline.get('rkrga_crop_path')}")
        print(f"  direct_librga_runtime_ready: {source_pipeline.get('direct_librga_runtime_ready')}")
        print(f"  direct_librga_path: {source_pipeline.get('direct_librga_path')}")
        crop_strategy = source_pipeline.get("detection_crop_strategy")
        if isinstance(crop_strategy, dict):
            print("  detection_crop_strategy:")
            print(f"    target_stage: {crop_strategy.get('target_stage')}")
            print(f"    current_stage: {crop_strategy.get('current_stage')}")
            print(
                "    active_media_pipeline_crop: "
                f"{crop_strategy.get('active_media_pipeline_crop')}"
            )
            print(f"    hardware_crop_element: {crop_strategy.get('hardware_crop_element')}")
            print(
                "    hardware_crop_runtime_available: "
                f"{crop_strategy.get('hardware_crop_runtime_available')}"
            )
            print(f"    hardware_crop_runtime_path: {crop_strategy.get('hardware_crop_runtime_path')}")
            print(f"    software_videocrop_allowed: {crop_strategy.get('software_videocrop_allowed')}")
            if crop_strategy.get("reason"):
                print(f"    reason: {crop_strategy.get('reason')}")
        print(
            "  target_capture_backend_integrated: "
            f"{source_pipeline.get('target_capture_backend_integrated')}"
        )
        print(f"  target_compliant: {source_pipeline.get('target_compliant')}")
        if source_pipeline.get("reason"):
            print(f"  reason: {source_pipeline.get('reason')}")
        candidates = source_pipeline.get("candidates")
        if isinstance(candidates, list) and candidates:
            print("  candidates:")
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                marker = "READY" if candidate.get("target_compliant") else "seen" if candidate.get("available") else "--"
                print(
                    "    "
                    f"{marker:5} {candidate.get('name')} "
                    f"role={candidate.get('role')} "
                    f"opens_capture={candidate.get('opens_capture_device')} "
                    f"target={candidate.get('target_compliant')}"
                )
                if candidate.get("violates_single_capture"):
                    print("      violates_single_capture: True")
                if candidate.get("reason"):
                    print(f"      reason: {candidate.get('reason')}")
        print()
    webrtc_sessions = report.get("webrtc_sessions")
    if isinstance(webrtc_sessions, dict):
        runtime = webrtc_sessions.get("runtime")
        runtime_invariants = webrtc_sessions.get("runtime_invariants")
        print("WebRTC Runtime")
        print(f"  target_ready: {webrtc_sessions.get('target_ready')}")
        print(f"  target_architecture_compliant: {webrtc_sessions.get('target_architecture_compliant')}")
        if isinstance(runtime, dict):
            print(f"  active_peer_count: {runtime.get('active_peer_count')}")
            print(f"  active_hardware_source_count: {runtime.get('active_hardware_source_count')}")
            print(f"  active_encoder_instances: {runtime.get('active_encoder_instances')}")
            print(f"  active_view_to_encoder_ratio: {runtime.get('active_view_to_encoder_ratio')}")
            print(f"  encoder_scaling_model: {runtime.get('encoder_scaling_model')}")
            process_resource = runtime.get("process_resource")
            if isinstance(process_resource, dict):
                print(
                    "  process_resource: "
                    f"cpu_s={process_resource.get('process_cpu_seconds')} "
                    f"rss_kb={process_resource.get('max_rss_kb')}"
                )
            sources = runtime.get("active_hardware_sources")
            if isinstance(sources, list) and sources:
                print(f"  active_hardware_sources: {', '.join(str(item) for item in sources)}")
        if isinstance(runtime_invariants, dict):
            print("  runtime_invariants:")
            for name, value in sorted(runtime_invariants.items()):
                marker = "OK" if value else "--"
                print(f"    {marker} {name}")
        print()
    print("Known Rockchip Devices")
    known = capabilities.get("devices", {}).get("known_rockchip_accelerators", {})
    for path, exists in known.items():
        marker = "OK" if exists else "--"
        print(f"  {marker} {path}")
    print()
    v4l2 = capabilities.get("devices", {}).get("v4l2_m2m", {})
    if v4l2:
        print(f"V4L2 M2M: {v4l2.get('reason')}")
        for item in v4l2.get("devices", []):
            print(
                "  "
                f"{item.get('path')} {item.get('role')} {item.get('card_type')} "
                f"capture={item.get('current_capture_format')} "
                f"output={item.get('current_output_format')} "
                f"h264_ready={item.get('production_h264_candidate')}"
            )
        print()
    video_handles = capabilities.get("devices", {}).get("video_open_handles", {})
    if isinstance(video_handles, dict):
        print("OS Video Handles")
        print(f"  available: {video_handles.get('available')}")
        if video_handles.get("reason"):
            print(f"  reason: {video_handles.get('reason')}")
        print(f"  total_handles: {video_handles.get('total_handles')}")
        print(f"  total_processes: {video_handles.get('total_processes')}")
        if video_handles.get("permission_denied") or video_handles.get("scan_errors"):
            print(f"  permission_denied: {video_handles.get('permission_denied')}")
            print(f"  scan_errors: {video_handles.get('scan_errors')}")
        paths = video_handles.get("paths")
        if isinstance(paths, dict) and paths:
            for path, item in sorted(paths.items()):
                print(
                    "  "
                    f"{path} handles={item.get('handle_count')} "
                    f"processes={item.get('process_count')}"
                )
                processes = item.get("processes")
                if isinstance(processes, list):
                    for process in processes[:5]:
                        if not isinstance(process, dict):
                            continue
                        print(
                            "    "
                            f"pid={process.get('pid')} fds={process.get('fd_count')} "
                            f"cmd={process.get('command')}"
                        )
                    if item.get("processes_truncated"):
                        print(f"    ... {item.get('processes_truncated')} more processes")
        print()
    if media_plane.get("physical_sources"):
        print("Physical Sources")
        for item in media_plane.get("physical_sources", []):
            latest = item.get("latest_frame")
            latest_available = isinstance(latest, dict)
            print(
                "  "
                f"{item.get('source')} roles={item.get('roles')} "
                f"captures={item.get('capture_instances')} ring={item.get('ring_buffer_depth')} "
                f"exists={item.get('source_exists')} "
                f"latest={latest_available}"
            )
            os_handles = item.get("os_handle_audit")
            if isinstance(os_handles, dict):
                print(
                    "    "
                    f"os_handles={os_handles.get('handle_count')} "
                    f"os_processes={os_handles.get('process_count')} "
                    f"path={os_handles.get('expected_device_path')}"
                )
        print()
    if evaluation["blockers"]:
        print("Blockers")
        for blocker in evaluation["blockers"]:
            print(f"  - {blocker}")
    else:
        print("Blockers")
        print("  none")
    warnings = evaluation.get("migration_warnings", [])
    if warnings:
        print()
        print("Migration Warnings")
        for warning in warnings:
            print(f"  - {warning}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe camera transport hardware readiness.")
    parser.add_argument(
        "--backend-url",
        default=DEFAULT_BACKEND_URL,
        help="Sorter backend base URL used for the live media-plane endpoint.",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Run local probes instead of reading the live backend endpoint.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full JSON report.")
    parser.add_argument(
        "--readiness-only",
        action="store_true",
        help=(
            "Exit 0 when the hardware WebRTC/H.264 path is ready, even if "
            "legacy MJPEG clients are still active. The default exit gate is "
            "the stricter target architecture compliance."
        ),
    )
    return parser.parse_args(argv)


def _exit_gate(report: dict[str, Any], *, readiness_only: bool = False) -> bool:
    gates = report.get("evaluation", {}).get("gates", {})
    if readiness_only:
        return bool(gates.get("target_ready"))
    return bool(gates.get("target_architecture_compliant"))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_report(args)
    except Exception as exc:
        print(f"probe failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_text_report(report)
    return 0 if _exit_gate(report, readiness_only=args.readiness_only) else 2


if __name__ == "__main__":
    raise SystemExit(main())
