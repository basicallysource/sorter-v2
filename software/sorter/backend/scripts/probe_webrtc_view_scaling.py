#!/usr/bin/env python3
"""Exercise WebRTC camera fanout and report backend scaling evidence.

This is an acceptance probe for the target camera transport. It opens multiple
WebRTC views for one camera role and verifies that the backend keeps one active
hardware source and one active encoder for the physical camera.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"


@dataclass
class OpenedPeer:
    peer: Any
    metadata_channel: Any


def _json_request(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout_s: float = 20.0,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if payload is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))
        except Exception:
            detail = {"detail": exc.reason}
        return {
            "ok": False,
            "status_code": exc.code,
            "error": detail,
        }
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "status_code": None,
            "error": str(exc),
        }
    return data if isinstance(data, dict) else {"ok": False, "error": "non-object JSON response"}


def _sessions_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/cameras/webrtc/sessions"


def _offer_url(base_url: str, role: str) -> str:
    return f"{base_url.rstrip('/')}/api/cameras/webrtc/offer/{role}"


def _role_physical_source(sessions_payload: dict[str, Any], role: str) -> str | None:
    for session in sessions_payload.get("sessions", []):
        if not isinstance(session, dict):
            continue
        roles = session.get("roles")
        if isinstance(roles, list) and role in roles:
            source = session.get("physical_source")
            return str(source) if isinstance(source, str) else None
    return None


def _process_resource(runtime: dict[str, Any]) -> dict[str, float] | None:
    raw = runtime.get("process_resource")
    if not isinstance(raw, dict):
        return None
    try:
        return {
            "wall_time_monotonic_s": float(raw["wall_time_monotonic_s"]),
            "process_cpu_seconds": float(raw["process_cpu_seconds"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _cpu_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_resource = _process_resource(before.get("runtime", {}))
    after_resource = _process_resource(after.get("runtime", {}))
    if before_resource is None or after_resource is None:
        return {
            "available": False,
            "reason": "WebRTC runtime process_resource snapshots are unavailable.",
        }
    elapsed_s = max(0.0, after_resource["wall_time_monotonic_s"] - before_resource["wall_time_monotonic_s"])
    cpu_s = max(0.0, after_resource["process_cpu_seconds"] - before_resource["process_cpu_seconds"])
    return {
        "available": True,
        "elapsed_s": round(elapsed_s, 6),
        "process_cpu_seconds": round(cpu_s, 6),
        "cpu_seconds_per_wall_second": round(cpu_s / elapsed_s, 6) if elapsed_s > 0 else None,
    }


def evaluate_view_scaling_result(
    *,
    role: str,
    requested_views: int,
    opened_views: int,
    before_sessions: dict[str, Any],
    after_sessions: dict[str, Any],
) -> dict[str, Any]:
    runtime = after_sessions.get("runtime", {}) if isinstance(after_sessions, dict) else {}
    invariants = after_sessions.get("runtime_invariants", {}) if isinstance(after_sessions, dict) else {}
    source = _role_physical_source(after_sessions, role)
    active_peers_by_source = runtime.get("active_peer_count_by_source", {})
    encoders_by_source = runtime.get("active_encoder_instances_by_source", {})
    fanout_by_source = runtime.get("fanout_subscriber_count_by_source", {})
    active_peers = int(active_peers_by_source.get(source, 0) or 0) if isinstance(active_peers_by_source, dict) else 0
    active_encoders = int(encoders_by_source.get(source, 0) or 0) if isinstance(encoders_by_source, dict) else 0
    fanout_subscribers = int(fanout_by_source.get(source, 0) or 0) if isinstance(fanout_by_source, dict) else 0
    missing: list[str] = []

    if source is None:
        missing.append(f"Role {role!r} is not mapped to a physical source.")
    if opened_views != requested_views:
        missing.append(f"Opened {opened_views} of {requested_views} requested WebRTC views.")
    if active_peers < opened_views:
        missing.append(
            f"Runtime reports {active_peers} active peers for {source}, expected at least {opened_views}."
        )
    if active_encoders != (1 if opened_views > 0 else 0):
        missing.append(
            f"Runtime reports {active_encoders} active encoders for {source}, expected one."
        )
    if fanout_subscribers < opened_views:
        missing.append(
            f"Fanout reports {fanout_subscribers} subscribers for {source}, expected at least {opened_views}."
        )
    for invariant in (
        "one_active_encoder_per_physical_source",
        "encoder_count_does_not_scale_with_views",
        "multi_view_sources_share_one_encoder",
        "fanout_subscribers_match_active_peers",
        "software_h264_fallback_forbidden",
    ):
        if not bool(invariants.get(invariant)):
            missing.append(f"Runtime invariant failed: {invariant}.")

    return {
        "ok": not missing,
        "role": role,
        "physical_source": source,
        "requested_views": requested_views,
        "opened_views": opened_views,
        "active_peers_for_source": active_peers,
        "active_encoders_for_source": active_encoders,
        "fanout_subscribers_for_source": fanout_subscribers,
        "active_view_to_encoder_ratio": runtime.get("active_view_to_encoder_ratio"),
        "encoder_scaling_model": runtime.get("encoder_scaling_model"),
        "cpu_delta": _cpu_delta(before_sessions, after_sessions),
        "missing": missing,
    }


async def _open_peer(base_url: str, role: str, sessions_payload: dict[str, Any]) -> OpenedPeer:
    from aiortc import RTCPeerConnection, RTCSessionDescription

    peer = RTCPeerConnection()
    peer.addTransceiver("video", direction="recvonly")
    spec = sessions_payload.get("control_plane", {}).get("metadata_data_channel", {})
    label = str(spec.get("label") or "camera-metadata")
    channel = peer.createDataChannel(
        label,
        ordered=bool(spec.get("ordered", False)),
        maxRetransmits=int(spec.get("max_retransmits", 0) or 0),
    )
    offer = await peer.createOffer()
    await peer.setLocalDescription(offer)
    await _wait_for_ice_gathering_complete(peer)
    local = peer.localDescription
    if local is None:
        await peer.close()
        raise RuntimeError("aiortc did not produce a local WebRTC offer.")
    answer = _json_request(
        "POST",
        _offer_url(base_url, role),
        {"type": local.type, "sdp": local.sdp},
    )
    if not answer.get("ok"):
        await peer.close()
        raise RuntimeError(json.dumps(answer, sort_keys=True))
    await peer.setRemoteDescription(RTCSessionDescription(sdp=str(answer["sdp"]), type=str(answer["type"])))
    return OpenedPeer(peer=peer, metadata_channel=channel)


async def _wait_for_ice_gathering_complete(peer: Any, timeout_s: float = 3.0) -> None:
    if getattr(peer, "iceGatheringState", None) == "complete":
        return
    event = asyncio.Event()

    @peer.on("icegatheringstatechange")
    def _on_ice_gathering_state_change() -> None:
        if peer.iceGatheringState == "complete":
            event.set()

    try:
        await asyncio.wait_for(event.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        pass


async def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    base_url = args.backend_url.rstrip("/")
    before = _json_request("GET", _sessions_url(base_url))
    if not before.get("ok"):
        return {
            "ok": False,
            "reason": "Could not read WebRTC session runtime before opening views.",
            "before": before,
        }
    if not before.get("target_ready"):
        return {
            "ok": False,
            "reason": "Hardware WebRTC transport is not target-ready.",
            "before": before,
            "blockers": before.get("blockers", []),
        }
    if not before.get("target_architecture_compliant"):
        return {
            "ok": False,
            "reason": "Hardware WebRTC transport is not target-architecture compliant.",
            "before": before,
            "blockers": before.get("blockers", []),
            "migration_warnings": before.get("migration_warnings", []),
            "gates": before.get("gates", {}),
        }

    peers: list[OpenedPeer] = []
    failures: list[str] = []
    try:
        for _ in range(max(0, int(args.views))):
            try:
                peers.append(await _open_peer(base_url, args.role, before))
            except Exception as exc:
                failures.append(str(exc))
                break
        await asyncio.sleep(max(0.0, float(args.settle_s)))
        after = _json_request("GET", _sessions_url(base_url))
        result = evaluate_view_scaling_result(
            role=args.role,
            requested_views=max(0, int(args.views)),
            opened_views=len(peers),
            before_sessions=before,
            after_sessions=after if after.get("ok") else {},
        )
        if failures:
            result["ok"] = False
            result.setdefault("missing", []).extend(failures)
        return {
            "ok": bool(result.get("ok")),
            "before": before,
            "after": after,
            "result": result,
        }
    finally:
        for opened in peers:
            try:
                close = getattr(opened.metadata_channel, "close", None)
                if callable(close):
                    close()
            except Exception:
                pass
            await opened.peer.close()
        await asyncio.sleep(0.1)


def _print_text(payload: dict[str, Any]) -> None:
    result = payload.get("result", {})
    print("WebRTC View Scaling Probe")
    print(f"  ok: {payload.get('ok')}")
    if payload.get("reason"):
        print(f"  reason: {payload.get('reason')}")
    if result:
        print(f"  role: {result.get('role')}")
        print(f"  physical_source: {result.get('physical_source')}")
        print(f"  requested_views: {result.get('requested_views')}")
        print(f"  opened_views: {result.get('opened_views')}")
        print(f"  active_peers_for_source: {result.get('active_peers_for_source')}")
        print(f"  active_encoders_for_source: {result.get('active_encoders_for_source')}")
        print(f"  fanout_subscribers_for_source: {result.get('fanout_subscribers_for_source')}")
        print(f"  active_view_to_encoder_ratio: {result.get('active_view_to_encoder_ratio')}")
        print(f"  encoder_scaling_model: {result.get('encoder_scaling_model')}")
        cpu_delta = result.get("cpu_delta")
        if isinstance(cpu_delta, dict):
            print(f"  cpu_delta: {cpu_delta}")
        missing = result.get("missing")
        if isinstance(missing, list) and missing:
            print("  missing:")
            for item in missing:
                print(f"    - {item}")
    blockers = payload.get("blockers")
    if isinstance(blockers, list) and blockers:
        print("  blockers:")
        for blocker in blockers:
            print(f"    - {blocker}")
    warnings = payload.get("migration_warnings")
    if isinstance(warnings, list) and warnings:
        print("  migration_warnings:")
        for warning in warnings:
            print(f"    - {warning}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe WebRTC multi-view encoder scaling.")
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--role", default="c_channel_2")
    parser.add_argument("--views", type=int, default=3)
    parser.add_argument("--settle-s", type=float, default=1.0)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = asyncio.run(run_probe(args))
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_text(payload)
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
