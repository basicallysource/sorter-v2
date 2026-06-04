#!/usr/bin/env python3
"""Probe whether multiple camera views add /dev/video capture handles.

The target transport uses WebRTC, but the capture invariant is transport
independent: opening dashboard/settings-style views must not open a second
``/dev/videoN`` handle. This probe keeps several feed clients alive briefly and
compares the backend media-plane handle audit before, during, and after.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any


DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"


@dataclass
class StreamClientResult:
    url: str
    connected: bool = False
    bytes_read: int = 0
    error: str | None = None
    done: threading.Event = field(default_factory=threading.Event)
    ready: threading.Event = field(default_factory=threading.Event)


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


def _stream_url(base_url: str, role: str, *, index: int) -> str:
    variants = [
        {
            "annotated": "0",
            "layer": "raw",
            "direct": "0",
            "dashboard": "0",
            "color_correct": "1",
            "show_regions": "0",
        },
        {
            "annotated": "1",
            "layer": "annotated",
            "direct": "0",
            "dashboard": "1",
            "color_correct": "1",
            "show_regions": "1",
        },
        {
            "annotated": "1",
            "layer": "annotated",
            "direct": "0",
            "dashboard": "0",
            "color_correct": "1",
            "show_regions": "0",
        },
    ]
    params = {
        **variants[index % len(variants)],
        "stream_epoch": f"handle-probe-{int(time.time())}",
        "stream_retry": str(index),
    }
    query = urllib.parse.urlencode(params)
    return f"{base_url.rstrip('/')}/api/cameras/feed/{urllib.parse.quote(role)}?{query}"


def _physical_source_for_role(payload: dict[str, Any], role: str) -> str | None:
    role_info = payload.get("roles", {}).get(role)
    if isinstance(role_info, dict) and isinstance(role_info.get("physical_source"), str):
        return str(role_info["physical_source"])
    for source in payload.get("physical_sources", []):
        if not isinstance(source, dict):
            continue
        roles = source.get("roles")
        if isinstance(roles, list) and role in roles and isinstance(source.get("source"), str):
            return str(source["source"])
    return None


def _source_summary(payload: dict[str, Any], source_key: str | None) -> dict[str, Any]:
    if not source_key:
        return {
            "source": None,
            "handle_count": None,
            "process_count": None,
            "capture_instances": None,
            "expected_device_path": None,
            "audit_available": False,
        }
    for source in payload.get("physical_sources", []):
        if not isinstance(source, dict) or source.get("source") != source_key:
            continue
        audit = source.get("os_handle_audit") if isinstance(source.get("os_handle_audit"), dict) else {}
        return {
            "source": source_key,
            "handle_count": int(audit.get("handle_count", 0) or 0),
            "process_count": int(audit.get("process_count", 0) or 0),
            "capture_instances": int(source.get("capture_instances", 0) or 0),
            "expected_device_path": audit.get("expected_device_path"),
            "audit_available": bool(audit.get("available")),
            "roles": source.get("roles", []),
        }
    return {
        "source": source_key,
        "handle_count": None,
        "process_count": None,
        "capture_instances": None,
        "expected_device_path": None,
        "audit_available": False,
    }


def _legacy_mjpeg_clients(payload: dict[str, Any]) -> int:
    try:
        return max(
            0,
            int(payload.get("legacy_transports", {}).get("mjpeg", {}).get("active_clients", 0) or 0),
        )
    except Exception:
        return 0


def evaluate_handle_stability(
    *,
    role: str,
    expected_clients: int,
    connected_clients: int,
    before: dict[str, Any],
    during: dict[str, Any],
    after: dict[str, Any],
    allowed_handle_delta: int = 0,
) -> dict[str, Any]:
    source = (
        _physical_source_for_role(during, role)
        or _physical_source_for_role(before, role)
        or _physical_source_for_role(after, role)
    )
    before_summary = _source_summary(before, source)
    during_summary = _source_summary(during, source)
    after_summary = _source_summary(after, source)
    missing: list[str] = []

    if source is None:
        missing.append(f"Role {role!r} is not mapped to a physical source.")
    if connected_clients < expected_clients:
        missing.append(f"Connected {connected_clients} of {expected_clients} requested stream clients.")
    if not during_summary["audit_available"]:
        missing.append("OS video handle audit is unavailable during the stream test.")
    if during_summary["capture_instances"] is None or during_summary["capture_instances"] > 1:
        missing.append(
            f"Capture instances during stream test: {during_summary['capture_instances']}; expected <= 1."
        )

    before_handles = before_summary["handle_count"]
    during_handles = during_summary["handle_count"]
    after_handles = after_summary["handle_count"]
    if before_handles is None or during_handles is None:
        missing.append("Could not compare /dev/video handle counts before/during stream clients.")
    elif during_handles > before_handles + max(0, int(allowed_handle_delta)):
        missing.append(
            f"/dev/video handle count grew from {before_handles} to {during_handles}; "
            f"allowed delta is {allowed_handle_delta}."
        )
    if before_handles is not None and after_handles is not None and after_handles > before_handles:
        missing.append(
            f"/dev/video handle count after cleanup is {after_handles}, above before count {before_handles}."
        )

    return {
        "ok": not missing,
        "role": role,
        "physical_source": source,
        "expected_clients": expected_clients,
        "connected_clients": connected_clients,
        "allowed_handle_delta": allowed_handle_delta,
        "legacy_mjpeg_active_clients_during": _legacy_mjpeg_clients(during),
        "before": before_summary,
        "during": during_summary,
        "after": after_summary,
        "missing": missing,
    }


def _stream_client(result: StreamClientResult, *, duration_s: float) -> None:
    deadline = time.monotonic() + max(0.1, duration_s)
    try:
        request = urllib.request.Request(result.url, method="GET")
        with urllib.request.urlopen(request, timeout=5.0) as response:
            result.connected = True
            result.ready.set()
            while time.monotonic() < deadline:
                chunk = response.read(4096)
                if not chunk:
                    break
                result.bytes_read += len(chunk)
    except Exception as exc:
        result.error = str(exc)
        result.ready.set()
    finally:
        result.done.set()


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    base_url = args.backend_url.rstrip("/")
    before = _json_request(_media_plane_url(base_url))
    if not before.get("ok"):
        return {"ok": False, "reason": "Could not read media-plane before stream clients.", "before": before}

    clients = [
        StreamClientResult(url=_stream_url(base_url, args.role, index=index))
        for index in range(max(0, int(args.clients)))
    ]
    threads = [
        threading.Thread(
            target=_stream_client,
            kwargs={"result": result, "duration_s": float(args.duration_s)},
            daemon=True,
        )
        for result in clients
    ]
    for thread in threads:
        thread.start()
    ready_deadline = time.monotonic() + max(1.0, float(args.ready_timeout_s))
    for result in clients:
        remaining = max(0.0, ready_deadline - time.monotonic())
        result.ready.wait(remaining)
    time.sleep(max(0.0, float(args.settle_s)))
    during = _json_request(_media_plane_url(base_url))
    for thread in threads:
        thread.join(timeout=max(0.1, float(args.duration_s) + 2.0))
    time.sleep(max(0.0, float(args.cleanup_settle_s)))
    after = _json_request(_media_plane_url(base_url))
    connected = sum(1 for result in clients if result.connected)
    result = evaluate_handle_stability(
        role=args.role,
        expected_clients=max(0, int(args.clients)),
        connected_clients=connected,
        before=before,
        during=during if during.get("ok") else {},
        after=after if after.get("ok") else {},
        allowed_handle_delta=max(0, int(args.allowed_handle_delta)),
    )
    client_payloads = [
        {
            "url": item.url,
            "connected": item.connected,
            "bytes_read": item.bytes_read,
            "error": item.error,
        }
        for item in clients
    ]
    return {
        "ok": bool(result.get("ok")),
        "result": result,
        "clients": client_payloads,
        "during_media_plane_error": None if during.get("ok") else during,
        "after_media_plane_error": None if after.get("ok") else after,
    }


def _print_text(payload: dict[str, Any]) -> None:
    result = payload.get("result", {})
    print("Camera Handle Stability Probe")
    print(f"  ok: {payload.get('ok')}")
    if payload.get("reason"):
        print(f"  reason: {payload.get('reason')}")
    if result:
        print(f"  role: {result.get('role')}")
        print(f"  physical_source: {result.get('physical_source')}")
        print(f"  expected_clients: {result.get('expected_clients')}")
        print(f"  connected_clients: {result.get('connected_clients')}")
        print(f"  legacy_mjpeg_active_clients_during: {result.get('legacy_mjpeg_active_clients_during')}")
        for name in ("before", "during", "after"):
            item = result.get(name)
            if not isinstance(item, dict):
                continue
            print(
                f"  {name}: handles={item.get('handle_count')} "
                f"processes={item.get('process_count')} "
                f"captures={item.get('capture_instances')} "
                f"path={item.get('expected_device_path')}"
            )
        missing = result.get("missing")
        if isinstance(missing, list) and missing:
            print("  missing:")
            for item in missing:
                print(f"    - {item}")
    clients = payload.get("clients")
    if isinstance(clients, list) and clients:
        print("  clients:")
        for client in clients:
            if not isinstance(client, dict):
                continue
            print(
                f"    - connected={client.get('connected')} "
                f"bytes={client.get('bytes_read')} error={client.get('error')}"
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe /dev/video handle stability under multiple views.")
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--role", default="c_channel_2")
    parser.add_argument("--clients", type=int, default=2)
    parser.add_argument("--duration-s", type=float, default=3.0)
    parser.add_argument("--settle-s", type=float, default=0.75)
    parser.add_argument("--cleanup-settle-s", type=float, default=0.5)
    parser.add_argument("--ready-timeout-s", type=float, default=4.0)
    parser.add_argument("--allowed-handle-delta", type=int, default=0)
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
