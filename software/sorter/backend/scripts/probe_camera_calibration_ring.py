#!/usr/bin/env python3
"""Probe whether camera calibration reads from the shared raw frame ring.

Exposure/color/zone calibration must not open its own ``/dev/videoN`` capture.
This probe reads the backend media-plane before and after a short sampling
window and verifies that selected camera roles have a fresh raw-ring frame,
one capture instance, no second-capture fallback, and stable OS video handles.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from typing import Any


DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"


def _json_request(url: str, *, timeout_s: float = 5.0) -> dict[str, Any]:
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


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _handle_count(source: dict[str, Any] | None) -> int | None:
    if not isinstance(source, dict):
        return None
    audit = source.get("os_handle_audit")
    if not isinstance(audit, dict) or not bool(audit.get("available")):
        return None
    return _int_or_none(audit.get("handle_count"))


def _process_count(source: dict[str, Any] | None) -> int | None:
    if not isinstance(source, dict):
        return None
    audit = source.get("os_handle_audit")
    if not isinstance(audit, dict) or not bool(audit.get("available")):
        return None
    return _int_or_none(audit.get("process_count"))


def _expected_device_path(source: dict[str, Any] | None) -> str | None:
    if not isinstance(source, dict):
        return None
    audit = source.get("os_handle_audit")
    if not isinstance(audit, dict):
        return None
    path = audit.get("expected_device_path")
    return str(path) if isinstance(path, str) else None


def _latest_frame(calibration: dict[str, Any]) -> dict[str, Any] | None:
    frame = calibration.get("latest_frame")
    return frame if isinstance(frame, dict) else None


def _frame_age_ms(calibration: dict[str, Any]) -> float | None:
    frame = _latest_frame(calibration)
    if frame is None:
        return None
    return _float_or_none(frame.get("age_ms"))


def _frame_timestamp(calibration: dict[str, Any]) -> float | None:
    frame = _latest_frame(calibration)
    if frame is None:
        return None
    return _float_or_none(frame.get("timestamp"))


def _frame_size(calibration: dict[str, Any]) -> tuple[int | None, int | None]:
    frame = _latest_frame(calibration)
    if frame is None:
        return None, None
    return _int_or_none(frame.get("width")), _int_or_none(frame.get("height"))


def evaluate_calibration_ring(
    *,
    roles: list[str],
    before: dict[str, Any],
    after: dict[str, Any],
    max_age_ms: float,
    require_frame_advance: bool = False,
) -> dict[str, Any]:
    role_results: list[dict[str, Any]] = []
    missing: list[str] = []

    if not roles:
        missing.append("No camera roles were selected for calibration ring probing.")

    for role in roles:
        source_key = _physical_source_for_role(after, role) or _physical_source_for_role(before, role)
        before_source = _source_item(before, source_key)
        after_source = _source_item(after, source_key)
        calibration = (
            after_source.get("calibration_frame_source")
            if isinstance(after_source, dict) and isinstance(after_source.get("calibration_frame_source"), dict)
            else {}
        )
        before_calibration = (
            before_source.get("calibration_frame_source")
            if isinstance(before_source, dict) and isinstance(before_source.get("calibration_frame_source"), dict)
            else {}
        )
        role_missing: list[str] = []
        ring_depth = _int_or_none(calibration.get("ring_buffer_depth")) or 0
        age_ms = _frame_age_ms(calibration)
        before_ts = _frame_timestamp(before_calibration)
        after_ts = _frame_timestamp(calibration)
        width, height = _frame_size(calibration)
        before_handles = _handle_count(before_source)
        after_handles = _handle_count(after_source)
        capture_instances = (
            _int_or_none(after_source.get("capture_instances")) if isinstance(after_source, dict) else None
        )

        if source_key is None:
            role_missing.append(f"Role {role!r} is not mapped to a physical source.")
        if after_source is None:
            role_missing.append(f"Physical source for role {role!r} is absent from the media-plane.")
        elif after_source.get("source_exists") is False:
            role_missing.append(f"Physical source {source_key} for role {role!r} does not exist.")
        if calibration.get("kind") != "raw_ring_buffer":
            role_missing.append(
                f"Calibration source for role {role!r} is {calibration.get('kind')!r}; expected raw_ring_buffer."
            )
        if not bool(calibration.get("available")):
            role_missing.append(f"Calibration raw ring buffer is unavailable for role {role!r}.")
        if ring_depth <= 0:
            role_missing.append(f"Ring buffer depth for role {role!r} is {ring_depth}; expected > 0.")
        if not bool(calibration.get("latest_frame_available")):
            role_missing.append(f"No latest raw frame is available for role {role!r}.")
        if width is None or height is None or width <= 0 or height <= 0:
            role_missing.append(f"Latest raw frame for role {role!r} has no valid dimensions.")
        if age_ms is None:
            role_missing.append(f"Latest raw frame age is unavailable for role {role!r}.")
        elif age_ms > max_age_ms:
            role_missing.append(
                f"Latest raw frame age for role {role!r} is {age_ms:.1f} ms; "
                f"expected <= {max_age_ms:.1f} ms."
            )
        if bool(calibration.get("uses_second_capture")):
            role_missing.append(f"Calibration for role {role!r} is using a second capture.")
        if bool(calibration.get("uses_legacy_direct_stream_cache")):
            role_missing.append(f"Calibration for role {role!r} is using the legacy direct stream cache.")
        if capture_instances is None:
            role_missing.append(f"Capture instance count is unavailable for role {role!r}.")
        elif capture_instances > 1:
            role_missing.append(
                f"Capture instances for role {role!r}: {capture_instances}; expected <= 1."
            )
        if after_handles is None:
            role_missing.append(f"OS video handle audit is unavailable for role {role!r}.")
        if before_handles is not None and after_handles is not None and after_handles > before_handles:
            role_missing.append(
                f"/dev/video handle count for role {role!r} grew from {before_handles} to {after_handles}."
            )
        if require_frame_advance and before_ts is not None and after_ts is not None and after_ts <= before_ts:
            role_missing.append(
                f"Raw ring frame timestamp for role {role!r} did not advance during the sample window."
            )

        missing.extend(role_missing)
        role_results.append(
            {
                "role": role,
                "ok": not role_missing,
                "physical_source": source_key,
                "kind": calibration.get("kind"),
                "available": bool(calibration.get("available")),
                "ring_buffer_depth": ring_depth,
                "latest_frame_available": bool(calibration.get("latest_frame_available")),
                "latest_frame_age_ms": age_ms,
                "latest_frame_width": width,
                "latest_frame_height": height,
                "uses_second_capture": bool(calibration.get("uses_second_capture")),
                "uses_legacy_direct_stream_cache": bool(calibration.get("uses_legacy_direct_stream_cache")),
                "capture_instances": capture_instances,
                "handle_count_before": before_handles,
                "handle_count_after": after_handles,
                "process_count_after": _process_count(after_source),
                "expected_device_path": _expected_device_path(after_source),
                "source_exists": None if not isinstance(after_source, dict) else after_source.get("source_exists"),
                "missing": role_missing,
            }
        )

    return {
        "ok": not missing,
        "roles": roles,
        "max_age_ms": max_age_ms,
        "require_frame_advance": require_frame_advance,
        "results": role_results,
        "missing": missing,
    }


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    base_url = args.backend_url.rstrip("/")
    before = _json_request(_media_plane_url(base_url))
    if not before.get("ok"):
        return {"ok": False, "reason": "Could not read media-plane before calibration ring sample.", "before": before}
    roles = _roles_to_check(before, roles=_split_roles(args.roles), all_assigned=bool(args.all_assigned))
    time.sleep(max(0.0, float(args.sample_s)))
    after = _json_request(_media_plane_url(base_url))
    if not after.get("ok"):
        return {"ok": False, "reason": "Could not read media-plane after calibration ring sample.", "after": after}
    result = evaluate_calibration_ring(
        roles=roles,
        before=before,
        after=after,
        max_age_ms=max(0.0, float(args.max_age_ms)),
        require_frame_advance=bool(args.require_frame_advance),
    )
    return {
        "ok": bool(result.get("ok")),
        "result": result,
    }


def _print_text(payload: dict[str, Any]) -> None:
    result = payload.get("result", {})
    print("Camera Calibration Ring Probe")
    print(f"  ok: {payload.get('ok')}")
    if payload.get("reason"):
        print(f"  reason: {payload.get('reason')}")
    if isinstance(result, dict):
        print(f"  roles: {', '.join(result.get('roles', []))}")
        print(f"  max_age_ms: {result.get('max_age_ms')}")
        print(f"  require_frame_advance: {result.get('require_frame_advance')}")
        for item in result.get("results", []):
            if not isinstance(item, dict):
                continue
            print(
                f"  {item.get('role')}: ok={item.get('ok')} "
                f"source={item.get('physical_source')} "
                f"kind={item.get('kind')} available={item.get('available')} "
                f"ring={item.get('ring_buffer_depth')} latest={item.get('latest_frame_available')} "
                f"age_ms={item.get('latest_frame_age_ms')} "
                f"second_capture={item.get('uses_second_capture')} "
                f"handles={item.get('handle_count_before')}->{item.get('handle_count_after')} "
                f"captures={item.get('capture_instances')} "
                f"path={item.get('expected_device_path')}"
            )
            missing = item.get("missing")
            if isinstance(missing, list) and missing:
                for detail in missing:
                    print(f"    - {detail}")
        missing = result.get("missing")
        if isinstance(missing, list) and missing:
            print("  missing:")
            for item in missing:
                print(f"    - {item}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe calibration access to shared raw frame ring buffers.")
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument(
        "--roles",
        default="c_channel_2",
        help="Comma-separated camera roles to probe unless --all-assigned is set.",
    )
    parser.add_argument("--all-assigned", action="store_true", help="Probe every assigned role in the media-plane.")
    parser.add_argument("--sample-s", type=float, default=0.75)
    parser.add_argument("--max-age-ms", type=float, default=5000.0)
    parser.add_argument("--require-frame-advance", action="store_true")
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
    raise SystemExit(main(sys.argv[1:]))
