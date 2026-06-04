#!/usr/bin/env python3
"""Probe the integrated GStreamer/Rockchip target capture pipeline.

The target camera transport is not "ffmpeg opens /dev/videoN". It is one
capture owner per physical camera with a tee: one branch feeds the raw frame
ring and calibration/detection, the other branch feeds hardware H.264 packets
for WebRTC. This probe checks that shape explicitly.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from vision.gstreamer_target_capture import TARGET_PIPELINE_NAME


DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
FORBIDDEN_DIRECT_PIPELINE_NAME = "forbidden_ffmpeg_v4l2_direct_to_rkmpp"
FORBIDDEN_SOFTWARE_ELEMENTS = {"x264enc", "openh264enc", "videoconvert", "videoscale", "jpegdec"}


def _json_request(url: str, *, timeout_s: float = 20.0) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc)}
    return payload if isinstance(payload, dict) else {"ok": False, "error": "non-object JSON"}


def _media_plane_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/cameras/media-plane"


def _split_roles(raw_roles: str | None) -> list[str]:
    if not raw_roles:
        return []
    roles: list[str] = []
    for item in raw_roles.split(","):
        role = item.strip()
        if role and role not in roles:
            roles.append(role)
    return roles


def _assigned_roles(payload: dict[str, Any]) -> list[str]:
    roles = payload.get("roles")
    if not isinstance(roles, dict):
        return []
    return sorted(str(role) for role, info in roles.items() if isinstance(info, dict))


def _roles_to_check(payload: dict[str, Any], *, roles: list[str], all_assigned: bool) -> list[str]:
    selected = _assigned_roles(payload) if all_assigned else roles
    return list(dict.fromkeys(selected))


def _candidate_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    candidates = (
        payload.get("capabilities", {})
        .get("source_pipeline", {})
        .get("candidates", [])
    )
    if not isinstance(candidates, list):
        return {}
    return {
        str(item.get("name")): item
        for item in candidates
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }


def _source_pipeline(payload: dict[str, Any]) -> dict[str, Any]:
    pipeline = payload.get("capabilities", {}).get("source_pipeline", {})
    return pipeline if isinstance(pipeline, dict) else {}


def _physical_source_for_role(payload: dict[str, Any], role: str) -> str | None:
    role_info = payload.get("roles", {}).get(role)
    if isinstance(role_info, dict) and isinstance(role_info.get("physical_source"), str):
        return str(role_info["physical_source"])
    for source in payload.get("physical_sources", []):
        if not isinstance(source, dict):
            continue
        source_roles = source.get("roles")
        if isinstance(source_roles, list) and role in source_roles and isinstance(source.get("source"), str):
            return str(source["source"])
    return None


def _source_item(payload: dict[str, Any], source_key: str | None) -> dict[str, Any] | None:
    if not source_key:
        return None
    for source in payload.get("physical_sources", []):
        if isinstance(source, dict) and source.get("source") == source_key:
            return source
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _target_candidate_missing(candidate: dict[str, Any] | None) -> list[str]:
    missing: list[str] = []
    if not isinstance(candidate, dict):
        return [f"Target source-pipeline candidate {TARGET_PIPELINE_NAME!r} is missing."]
    if not bool(candidate.get("available")):
        missing.append(f"Target source-pipeline candidate {TARGET_PIPELINE_NAME!r} is not available.")
    required_elements = candidate.get("required_gstreamer_elements")
    if isinstance(required_elements, dict):
        missing.extend(
            f"GStreamer element requirement failed: {name}."
            for name, ok in sorted(required_elements.items())
            if not bool(ok)
        )
    required_nodes = candidate.get("required_device_nodes")
    if isinstance(required_nodes, dict):
        missing.extend(
            f"Device-node requirement failed: {name}."
            for name, ok in sorted(required_nodes.items())
            if not bool(ok)
        )
    if not bool(candidate.get("single_capture_pipeline")):
        missing.append("Target candidate is not marked as a single-capture pipeline.")
    if not bool(candidate.get("raw_ring_branch")):
        missing.append("Target candidate does not expose a raw-ring branch.")
    if not bool(candidate.get("h264_webrtc_branch")):
        missing.append("Target candidate does not expose an H.264 WebRTC branch.")
    if bool(candidate.get("software_h264_fallback_allowed")):
        missing.append("Target candidate allows software H.264 fallback.")
    if not bool(candidate.get("runtime_module_implemented")):
        missing.append("Target candidate runtime module is not implemented.")
    if not bool(candidate.get("runtime_importable")):
        runtime = candidate.get("runtime") if isinstance(candidate.get("runtime"), dict) else {}
        reason = runtime.get("reason")
        missing.append(
            "Target candidate runtime module is not importable."
            + (f" {reason}" if reason else "")
        )
    missing.extend(_target_pipeline_contract_missing(candidate.get("pipeline_contract")))
    return missing


def _target_pipeline_contract_missing(contract: Any) -> list[str]:
    missing: list[str] = []
    if not isinstance(contract, dict):
        return ["Target candidate does not expose a concrete GStreamer pipeline contract."]
    if contract.get("name") != TARGET_PIPELINE_NAME:
        missing.append(f"Target pipeline contract name is {contract.get('name')!r}.")
    topology = contract.get("topology")
    if not isinstance(topology, dict):
        missing.append("Target pipeline contract does not include topology metadata.")
    else:
        for key in ("single_capture_pipeline", "raw_ring_branch", "h264_webrtc_branch"):
            if not bool(topology.get(key)):
                missing.append(f"Target pipeline contract topology is missing {key}.")
    launch_pipeline = str(contract.get("launch_pipeline") or "")
    if not launch_pipeline:
        missing.append("Target pipeline contract does not include a launch pipeline.")
    else:
        tokens = set(launch_pipeline.split())
        found_forbidden = sorted(FORBIDDEN_SOFTWARE_ELEMENTS & tokens)
        if found_forbidden:
            missing.append(
                "Target pipeline contract contains forbidden software elements: "
                + ", ".join(found_forbidden)
            )
        if launch_pipeline.split().count("v4l2src") != 1:
            missing.append("Target pipeline contract must contain exactly one v4l2src element.")
        if launch_pipeline.count("sorter_capture_tee.") < 2:
            missing.append("Target pipeline contract does not expose both tee branches.")
    required_nodes = contract.get("required_device_nodes")
    if not isinstance(required_nodes, list) or not {
        "/dev/mpp_service",
        "/dev/rga",
        "/dev/dma_heap",
    } <= set(str(item) for item in required_nodes):
        missing.append("Target pipeline contract does not list the required Rockchip device nodes.")
    required_elements = contract.get("required_gstreamer_elements")
    if not isinstance(required_elements, dict) or not {
        "v4l2src",
        "appsink",
        "jpegparse",
        "mppjpegdec",
        "rockchip_mpp_h264_encoder",
        "h264parse",
    } <= set(required_elements):
        missing.append("Target pipeline contract does not list all required GStreamer elements.")
    if bool(contract.get("software_h264_fallback_allowed")):
        missing.append("Target pipeline contract allows software H.264 fallback.")
    return missing


def _forbidden_candidate_missing(candidate: dict[str, Any] | None) -> list[str]:
    if not isinstance(candidate, dict):
        return [f"Forbidden source-pipeline candidate {FORBIDDEN_DIRECT_PIPELINE_NAME!r} is missing."]
    missing: list[str] = []
    if not bool(candidate.get("opens_capture_device")):
        missing.append("Forbidden direct ffmpeg candidate is not marked as opening /dev/videoN.")
    if not bool(candidate.get("violates_single_capture")):
        missing.append("Forbidden direct ffmpeg candidate is not marked as violating single capture.")
    if bool(candidate.get("target_compliant")):
        missing.append("Forbidden direct ffmpeg candidate is target-compliant; this would regress the architecture.")
    return missing


def evaluate_target_capture_pipeline(
    *,
    payload: dict[str, Any],
    roles: list[str],
) -> dict[str, Any]:
    missing: list[str] = []
    role_results: list[dict[str, Any]] = []
    pipeline = _source_pipeline(payload)
    candidates = _candidate_map(payload)
    target_candidate = candidates.get(TARGET_PIPELINE_NAME)
    forbidden_candidate = candidates.get(FORBIDDEN_DIRECT_PIPELINE_NAME)

    if not roles:
        missing.append("No camera roles were selected for target capture pipeline probing.")
    missing.extend(_target_candidate_missing(target_candidate))
    missing.extend(_forbidden_candidate_missing(forbidden_candidate))

    if not bool(pipeline.get("target_capture_backend_integrated")):
        missing.append("Media-plane source pipeline is not using the integrated target capture backend.")
    if pipeline.get("implementation") != TARGET_PIPELINE_NAME:
        missing.append(
            f"Media-plane source pipeline implementation is {pipeline.get('implementation')!r}; "
            f"expected {TARGET_PIPELINE_NAME!r}."
        )
    if not bool(pipeline.get("target_compliant")):
        missing.append("Media-plane source pipeline is not target-compliant.")
    if not bool(pipeline.get("zero_copy_dmabuf")):
        missing.append("Media-plane source pipeline does not report zero-copy/DMABUF.")

    for role in roles:
        role_missing: list[str] = []
        source_key = _physical_source_for_role(payload, role)
        source = _source_item(payload, source_key)
        capture_backend = (
            source.get("capture_backend")
            if isinstance(source, dict) and isinstance(source.get("capture_backend"), dict)
            else {}
        )
        source_contract = (
            source.get("target_capture_pipeline_contract")
            if isinstance(source, dict)
            else None
        )
        capture_instances = _int_or_none(source.get("capture_instances")) if isinstance(source, dict) else None

        if source_key is None:
            role_missing.append(f"Role {role!r} is not mapped to a physical source.")
        if source is None:
            role_missing.append(f"Physical source for role {role!r} is absent from the media-plane.")
        elif source.get("source_exists") is False:
            role_missing.append(f"Physical source {source_key} for role {role!r} does not exist.")
        if capture_instances is None:
            role_missing.append(f"Capture instance count is unavailable for role {role!r}.")
        elif capture_instances > 1:
            role_missing.append(
                f"Capture instances for role {role!r}: {capture_instances}; expected <= 1."
            )
        if capture_backend.get("implementation") != TARGET_PIPELINE_NAME:
            role_missing.append(
                f"Capture backend for role {role!r} is {capture_backend.get('implementation')!r}; "
                f"expected {TARGET_PIPELINE_NAME!r}."
            )
        if not bool(capture_backend.get("single_capture_owner")):
            role_missing.append(f"Capture backend for role {role!r} is not a single capture owner.")
        if not bool(capture_backend.get("raw_ring_branch")):
            role_missing.append(f"Capture backend for role {role!r} does not expose the raw-ring branch.")
        if not bool(capture_backend.get("h264_webrtc_branch")):
            role_missing.append(f"Capture backend for role {role!r} does not expose the H.264 WebRTC branch.")
        if not bool(capture_backend.get("zero_copy_dmabuf")):
            role_missing.append(f"Capture backend for role {role!r} does not report zero-copy/DMABUF.")
        if not bool(capture_backend.get("target_compliant")):
            role_missing.append(f"Capture backend for role {role!r} is not target-compliant.")
        if not isinstance(source_contract, dict):
            role_missing.append(f"Role {role!r} does not expose a target capture pipeline contract.")
        else:
            role_missing.extend(
                f"Target capture pipeline contract for role {role!r}: {detail}"
                for detail in _target_pipeline_contract_missing(source_contract)
            )

        missing.extend(role_missing)
        role_results.append(
            {
                "role": role,
                "ok": not role_missing,
                "physical_source": source_key,
                "capture_instances": capture_instances,
                "capture_backend": capture_backend,
                "target_capture_pipeline_contract": source_contract,
                "missing": role_missing,
            }
        )

    return {
        "ok": not missing,
        "roles": roles,
        "target_pipeline": TARGET_PIPELINE_NAME,
        "source_pipeline": pipeline,
        "target_candidate": target_candidate,
        "forbidden_direct_candidate": forbidden_candidate,
        "results": role_results,
        "missing": missing,
    }


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    base_url = args.backend_url.rstrip("/")
    payload = _json_request(_media_plane_url(base_url))
    if not payload.get("ok"):
        return {"ok": False, "reason": "Could not read media-plane.", "media_plane": payload}
    roles = _roles_to_check(payload, roles=_split_roles(args.roles), all_assigned=bool(args.all_assigned))
    result = evaluate_target_capture_pipeline(payload=payload, roles=roles)
    return {"ok": bool(result.get("ok")), "result": result}


def _print_text(payload: dict[str, Any]) -> None:
    result = payload.get("result", {})
    print("GStreamer Target Capture Pipeline Probe")
    print(f"  ok: {payload.get('ok')}")
    if payload.get("reason"):
        print(f"  reason: {payload.get('reason')}")
    if not isinstance(result, dict):
        return
    print(f"  target_pipeline: {result.get('target_pipeline')}")
    pipeline = result.get("source_pipeline")
    if isinstance(pipeline, dict):
        print(
            "  source_pipeline: "
            f"implementation={pipeline.get('implementation')} "
            f"integrated={pipeline.get('target_capture_backend_integrated')} "
            f"target={pipeline.get('target_compliant')} "
            f"zero_copy={pipeline.get('zero_copy_dmabuf')} "
            f"hw_convert={pipeline.get('hardware_scale_convert_in_source')}"
        )
    target_candidate = result.get("target_candidate")
    if isinstance(target_candidate, dict):
        print(
            "  target_candidate: "
            f"available={target_candidate.get('available')} "
            f"target={target_candidate.get('target_compliant')} "
            f"runtime={target_candidate.get('runtime_importable')}"
        )
        elements = target_candidate.get("required_gstreamer_elements")
        if isinstance(elements, dict):
            missing = [name for name, ok in sorted(elements.items()) if not bool(ok)]
            print(f"    missing_elements: {', '.join(missing) if missing else 'none'}")
        nodes = target_candidate.get("required_device_nodes")
        if isinstance(nodes, dict):
            missing = [name for name, ok in sorted(nodes.items()) if not bool(ok)]
            print(f"    missing_nodes: {', '.join(missing) if missing else 'none'}")
        contract = target_candidate.get("pipeline_contract")
        if isinstance(contract, dict):
            topology = contract.get("topology") if isinstance(contract.get("topology"), dict) else {}
            print(
                "    pipeline_contract: "
                f"name={contract.get('name')} "
                f"single_capture={topology.get('single_capture_pipeline')} "
                f"raw_branch={topology.get('raw_ring_branch')} "
                f"h264_branch={topology.get('h264_webrtc_branch')} "
                f"zero_copy={contract.get('zero_copy_dmabuf')}"
            )
            launch = str(contract.get("launch_pipeline") or "")
            if launch:
                print(f"    launch_pipeline: {launch}")
    for item in result.get("results", []):
        if not isinstance(item, dict):
            continue
        capture_backend = item.get("capture_backend") if isinstance(item.get("capture_backend"), dict) else {}
        contract = item.get("target_capture_pipeline_contract")
        print(
            f"  {item.get('role')}: ok={item.get('ok')} "
            f"source={item.get('physical_source')} "
            f"captures={item.get('capture_instances')} "
            f"backend={capture_backend.get('implementation')} "
            f"raw={capture_backend.get('raw_ring_branch')} "
            f"h264={capture_backend.get('h264_webrtc_branch')} "
            f"target={capture_backend.get('target_compliant')}"
        )
        missing = item.get("missing")
        if isinstance(missing, list) and missing:
            for detail in missing:
                print(f"    - {detail}")
        if isinstance(contract, dict) and contract.get("launch_pipeline"):
            print(f"    target_launch_pipeline: {contract.get('launch_pipeline')}")
    missing = result.get("missing")
    if isinstance(missing, list) and missing:
        print("  missing:")
        for item in missing:
            print(f"    - {item}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe the integrated GStreamer target capture pipeline.")
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument(
        "--roles",
        default="c_channel_2",
        help="Comma-separated camera roles to probe unless --all-assigned is set.",
    )
    parser.add_argument("--all-assigned", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_probe(args)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_text(payload)
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
