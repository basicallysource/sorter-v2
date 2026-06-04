"""WebRTC camera transport session registry.

This module is the control-plane half of the target camera transport:
one WebRTC media session per physical camera source, with metadata riding next
to it over WebSocket/DataChannel. It deliberately refuses to fall back to
software H.264 or MJPEG when the Rockchip hardware encoder path is not ready.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import resource
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

from .h264_webrtc_bridge import HardwareH264PacketTrack, HardwareH264SourceFanout
from .media_plane import (
    camera_metadata_data_channel_spec,
    describe_media_plane,
    evaluate_transport_gates,
)

logger = logging.getLogger(__name__)

# SorterOS exposes a USB-C direct-connect fallback network on usb0
# (172.31.42.0/24). aioice gathers ICE host candidates from *every* interface,
# so it advertises 172.31.42.x to LAN browsers that can never reach it — and,
# worse, on this multi-homed box the device-side ICE agent emits connectivity
# checks *from* that interface's source address toward the LAN peer, which
# reverse-path filtering / asymmetric routing drops. The result is that ICE
# never nominates a working pair even though a reachable LAN candidate exists.
# Restrict host-candidate gathering to routable IPv4 interfaces so only the LAN
# (and its server-reflexive) candidates are offered.
_ICE_EXCLUDED_NETWORKS = ("172.31.42.0/24",)


def _install_ice_interface_policy() -> None:
    import ipaddress

    try:
        from aioice import ice as _aioice_ice
    except Exception:  # pragma: no cover - aioice always present with aiortc
        return
    original = getattr(_aioice_ice, "get_host_addresses", None)
    if original is None or getattr(original, "_sorter_ice_filtered", False):
        return

    excluded = [ipaddress.ip_network(net) for net in _ICE_EXCLUDED_NETWORKS]

    def _filtered(use_ipv4: bool, use_ipv6: bool) -> list[str]:
        kept: list[str] = []
        for addr in original(use_ipv4=use_ipv4, use_ipv6=use_ipv6):
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                continue
            # IPv6 ULA/link-local candidates only add dead pairs for a LAN
            # IPv4 browser; keep ICE to the routable IPv4 LAN.
            if ip.version != 4:
                continue
            if ip.is_link_local or any(ip in net for net in excluded):
                continue
            kept.append(addr)
        return kept

    _filtered._sorter_ice_filtered = True  # type: ignore[attr-defined]
    _aioice_ice.get_host_addresses = _filtered
    logger.info("ICE host-candidate policy installed (excluding %s)", _ICE_EXCLUDED_NETWORKS)


_install_ice_interface_policy()


class WebRtcTransportError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.code = str(code)
        self.message = str(message)
        self.payload = payload or {}

    def to_http_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            **self.payload,
        }


@dataclass
class WebRtcSourceSession:
    session_id: str
    physical_source: str
    roles: set[str]
    device_id: int
    created_at: float
    updated_at: float
    active_peer_count: int = 0
    encoder_instances_active: int = 0
    offer_count: int = 0
    last_offer_at: float | None = None
    state: str = "idle"
    selected_encoder_path: dict[str, Any] | None = None
    blockers: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "physical_source": self.physical_source,
            "roles": sorted(self.roles),
            "device_id": self.device_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "active_peer_count": self.active_peer_count,
            "encoder_instances_active": self.encoder_instances_active,
            "offer_count": self.offer_count,
            "last_offer_at": self.last_offer_at,
            "state": self.state,
            "selected_encoder_path": self.selected_encoder_path,
            "blockers": list(self.blockers),
        }


HardwareH264SourceFactory = Callable[..., Any]
CameraMetadataProvider = Callable[[str], Any]
_METADATA_SEND_INTERVAL_S = 0.1


def _process_resource_snapshot() -> dict[str, Any]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "wall_time_monotonic_s": round(time.monotonic(), 6),
        "process_cpu_seconds": round(float(usage.ru_utime + usage.ru_stime), 6),
        "user_cpu_seconds": round(float(usage.ru_utime), 6),
        "system_cpu_seconds": round(float(usage.ru_stime), 6),
        "max_rss_kb": int(usage.ru_maxrss),
    }


def _feed_source_key(feed: Any) -> str | None:
    device = getattr(feed, "device", None)
    config = getattr(device, "config", None)
    if config is None:
        return None
    url = getattr(config, "url", None)
    if url:
        return f"url:{url}"
    index = getattr(config, "device_index", None)
    if isinstance(index, int) and index >= 0:
        return f"video:{index}"
    return None


def _feed_device_id(feed: Any) -> int | None:
    device = getattr(feed, "device", None)
    return id(device) if device is not None else None


def _webrtc_runtime_summary(
    *,
    sessions: list[dict[str, Any]],
    active_hardware_sources: set[str],
    active_hardware_source_details: dict[str, dict[str, Any]] | None = None,
    metadata_task_count: int,
) -> dict[str, Any]:
    active_hardware_source_details = active_hardware_source_details or {}
    sources = [
        str(item.get("physical_source"))
        for item in sessions
        if isinstance(item.get("physical_source"), str)
    ]
    active_encoder_instances_by_source: dict[str, int] = {}
    active_peer_count_by_source: dict[str, int] = {}
    for item in sessions:
        source = item.get("physical_source")
        if not isinstance(source, str):
            continue
        try:
            active_encoder_instances_by_source[source] = max(
                0,
                int(item.get("encoder_instances_active", 0) or 0),
            )
        except Exception:
            active_encoder_instances_by_source[source] = 0
        try:
            active_peer_count_by_source[source] = max(
                0,
                int(item.get("active_peer_count", 0) or 0),
            )
        except Exception:
            active_peer_count_by_source[source] = 0

    source_set = set(sources)
    active_hardware_sources_known = sorted(active_hardware_sources & source_set)
    active_hardware_sources_unknown = sorted(active_hardware_sources - source_set)
    active_encoder_total = sum(active_encoder_instances_by_source.values())
    active_peer_total = sum(active_peer_count_by_source.values())
    sources_with_active_peers = {
        source
        for source, peers in active_peer_count_by_source.items()
        if peers > 0
    }
    sources_with_multi_view_peers = {
        source
        for source, peers in active_peer_count_by_source.items()
        if peers > 1
    }
    max_active_peers_per_source = (
        max(active_peer_count_by_source.values())
        if active_peer_count_by_source
        else 0
    )
    max_active_encoder_instances_per_source = (
        max(active_encoder_instances_by_source.values())
        if active_encoder_instances_by_source
        else 0
    )
    one_encoder_per_source = all(
        count <= 1 for count in active_encoder_instances_by_source.values()
    )
    multi_view_sources_share_one_encoder = all(
        active_encoder_instances_by_source.get(source, 0) == 1
        for source in sources_with_multi_view_peers
    )
    encoder_count_does_not_scale_with_views = (
        one_encoder_per_source and multi_view_sources_share_one_encoder
    )
    fanout_subscriber_count_by_source: dict[str, int] = {}
    for source, detail in active_hardware_source_details.items():
        raw_count = detail.get("fanout_subscriber_count")
        if raw_count is None:
            continue
        try:
            fanout_subscriber_count_by_source[source] = max(0, int(raw_count))
        except Exception:
            continue
    fanout_subscribers_match_active_peers = all(
        fanout_subscriber_count_by_source.get(source, 0)
        == active_peer_count_by_source.get(source, 0)
        for source in sources_with_active_peers
    )
    active_view_to_encoder_ratio = (
        round(active_peer_total / active_encoder_total, 3)
        if active_encoder_total > 0
        else None
    )

    return {
        "physical_source_count": len(source_set),
        "session_count": len(sessions),
        "active_peer_count": active_peer_total,
        "active_peer_count_by_source": active_peer_count_by_source,
        "max_active_peers_per_source": max_active_peers_per_source,
        "sources_with_multi_view_peers": sorted(sources_with_multi_view_peers),
        "active_hardware_source_count": len(active_hardware_sources),
        "active_hardware_sources": sorted(active_hardware_sources),
        "active_hardware_source_details": active_hardware_source_details,
        "active_hardware_sources_without_session": active_hardware_sources_unknown,
        "fanout_subscriber_count_by_source": fanout_subscriber_count_by_source,
        "active_encoder_instances": active_encoder_total,
        "active_encoder_instances_by_source": active_encoder_instances_by_source,
        "max_active_encoder_instances_per_source": max_active_encoder_instances_per_source,
        "active_view_to_encoder_ratio": active_view_to_encoder_ratio,
        "encoder_scaling_model": (
            "per_physical_source"
            if encoder_count_does_not_scale_with_views
            else "per_view_or_invalid"
        ),
        "metadata_sender_count": max(0, int(metadata_task_count)),
        "process_resource": _process_resource_snapshot(),
        "invariants": {
            "one_media_session_per_physical_source": len(sources) == len(source_set),
            "one_active_hardware_source_per_physical_source": (
                len(active_hardware_sources_known) == len(active_hardware_sources)
                and len(active_hardware_sources) <= len(source_set)
            ),
            "one_active_encoder_per_physical_source": one_encoder_per_source,
            "multi_view_sources_share_one_encoder": multi_view_sources_share_one_encoder,
            "encoder_count_does_not_scale_with_views": encoder_count_does_not_scale_with_views,
            "fanout_subscribers_match_active_peers": fanout_subscribers_match_active_peers,
            "active_peers_have_encoder": all(
                active_encoder_instances_by_source.get(source, 0) == 1
                for source in sources_with_active_peers
            ),
            "metadata_payloads_are_pixel_free": True,
            "software_h264_fallback_forbidden": True,
        },
    }


class CameraWebRtcSessionRegistry:
    """Tracks desired/active WebRTC sessions by physical camera source."""

    def __init__(self, hardware_source_factory: HardwareH264SourceFactory | None = None) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, WebRtcSourceSession] = {}
        self._hardware_source_factory = hardware_source_factory
        self._hardware_sources: dict[str, Any] = {}
        self._source_create_locks: dict[str, asyncio.Lock] = {}
        self._peers_by_source: dict[str, set[Any]] = {}
        self._metadata_tasks_by_peer: dict[Any, set[asyncio.Task[Any]]] = {}
        self._track_subscriptions_by_peer: dict[Any, set[Any]] = {}

    def reset(self) -> None:
        with self._lock:
            tasks = [task for tasks in self._metadata_tasks_by_peer.values() for task in tasks]
            self._sessions.clear()
            self._hardware_sources.clear()
            self._source_create_locks.clear()
            self._peers_by_source.clear()
            self._metadata_tasks_by_peer.clear()
            subscriptions = [
                subscription
                for subscriptions in self._track_subscriptions_by_peer.values()
                for subscription in subscriptions
            ]
            self._track_subscriptions_by_peer.clear()
        for task in tasks:
            task.cancel()
        for subscription in subscriptions:
            close = getattr(subscription, "close", None)
            if callable(close):
                close()

    async def aclose(self) -> None:
        with self._lock:
            peers = [peer for peers in self._peers_by_source.values() for peer in peers]
            sources = list(self._hardware_sources.values())
            metadata_tasks = [
                task for tasks in self._metadata_tasks_by_peer.values() for task in tasks
            ]
            self._peers_by_source.clear()
            self._hardware_sources.clear()
            self._source_create_locks.clear()
            self._metadata_tasks_by_peer.clear()
            subscriptions = [
                subscription
                for subscriptions in self._track_subscriptions_by_peer.values()
                for subscription in subscriptions
            ]
            self._track_subscriptions_by_peer.clear()
            self._sessions.clear()
        await _cancel_tasks(metadata_tasks)
        for subscription in subscriptions:
            close = getattr(subscription, "close", None)
            if callable(close):
                close()
        for peer in peers:
            await _close_peer(peer)
        for source in sources:
            await _stop_hardware_source(source)

    def set_hardware_source_factory(self, factory: HardwareH264SourceFactory | None) -> None:
        with self._lock:
            self._hardware_source_factory = factory
            self._hardware_sources.clear()
            self._source_create_locks.clear()

    def _ensure_session(
        self,
        *,
        physical_source: str,
        roles: list[str],
        device_id: int,
        evaluation: dict[str, Any],
    ) -> WebRtcSourceSession:
        now = time.time()
        selected = evaluation.get("selected_encoder_path")
        blockers = [
            str(item)
            for item in evaluation.get("blockers", [])
            if isinstance(item, str)
        ]
        gates = evaluation.get("gates", {})
        target_state = (
            "blocked_missing_hardware_h264_path"
            if not gates.get("target_ready")
            else "blocked_missing_webrtc_hardware_bridge"
            if not gates.get("webrtc_hardware_bridge_implemented")
            else "blocked_target_architecture_noncompliant"
            if not gates.get("target_architecture_compliant")
            else "ready_for_offer"
        )

        session = self._sessions.get(physical_source)
        if session is None:
            session = WebRtcSourceSession(
                session_id=uuid4().hex,
                physical_source=physical_source,
                roles=set(roles),
                device_id=device_id,
                created_at=now,
                updated_at=now,
                state=target_state,
                selected_encoder_path=selected,
                blockers=blockers,
            )
            self._sessions[physical_source] = session
        else:
            session.roles = set(roles)
            session.device_id = device_id
            session.updated_at = now
            if (
                target_state == "ready_for_offer"
                and session.active_peer_count > 0
                and session.encoder_instances_active > 0
                and session.state == "answer_created"
            ):
                session.state = "answer_created"
            else:
                session.state = target_state
            session.selected_encoder_path = selected
            session.blockers = blockers
            if target_state != "ready_for_offer":
                session.encoder_instances_active = 0
                session.active_peer_count = 0
        return session

    def describe(
        self,
        camera_service: Any | None,
        *,
        media_plane_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        media_plane = media_plane_payload or describe_media_plane(camera_service)
        evaluation = evaluate_transport_gates(media_plane)

        sessions: list[dict[str, Any]] = []
        with self._lock:
            for source in media_plane.get("physical_sources", []):
                physical_source = source.get("source")
                if not isinstance(physical_source, str) or physical_source == "unassigned":
                    continue
                roles = [
                    str(role)
                    for role in source.get("roles", [])
                    if isinstance(role, str)
                ]
                device_id = 0
                for role in roles:
                    role_info = media_plane.get("roles", {}).get(role)
                    if isinstance(role_info, dict) and isinstance(role_info.get("device_id"), int):
                        device_id = int(role_info["device_id"])
                        break
                session = self._ensure_session(
                    physical_source=physical_source,
                    roles=roles,
                    device_id=device_id,
                    evaluation=evaluation,
                )
                sessions.append(session.as_dict())

            known_sources = {item["physical_source"] for item in sessions}
            for source in list(self._sessions):
                if source not in known_sources:
                    del self._sessions[source]
            active_hardware_source_details = {
                str(source): {
                    "fanout": hasattr(hardware_source, "subscribe"),
                    "fanout_subscriber_count": getattr(
                        hardware_source,
                        "active_subscriber_count",
                        None,
                    ),
                    "upstream_source_type": type(
                        getattr(hardware_source, "source", hardware_source)
                    ).__name__,
                }
                for source, hardware_source in self._hardware_sources.items()
            }
            runtime = _webrtc_runtime_summary(
                sessions=sessions,
                active_hardware_sources=set(self._hardware_sources),
                active_hardware_source_details=active_hardware_source_details,
                metadata_task_count=sum(
                    1
                    for tasks in self._metadata_tasks_by_peer.values()
                    for task in tasks
                    if not task.done()
                ),
            )
        runtime_invariants = runtime["invariants"]
        runtime_compliant = all(bool(value) for value in runtime_invariants.values())

        return {
            "ok": True,
            "active": bool(media_plane.get("active")),
            "target": {
                "transport": "webrtc",
                "video_codec": "h264",
                "encoder": "rockchip_mpp",
            },
            "target_ready": bool(evaluation.get("gates", {}).get("target_ready")),
            "target_architecture_compliant": bool(
                evaluation.get("gates", {}).get("target_architecture_compliant")
                and runtime_compliant
            ),
            "gates": evaluation.get("gates", {}),
            "blockers": evaluation.get("blockers", []),
            "migration_warnings": evaluation.get("migration_warnings", []),
            "sessions": sessions,
            "runtime": {key: value for key, value in runtime.items() if key != "invariants"},
            "runtime_invariants": runtime_invariants,
            "control_plane": {
                "metadata_transport_target": "websocket_or_webrtc_datachannel",
                "metadata_data_channel": camera_metadata_data_channel_spec(),
                "payload_contains_pixels": False,
                "one_media_session_per_physical_source": True,
                "software_h264_fallback_allowed": False,
            },
        }

    async def prepare_offer(
        self,
        role: str,
        *,
        sdp: str,
        offer_type: str,
        camera_service: Any | None,
        media_plane_payload: dict[str, Any] | None = None,
        metadata_provider: CameraMetadataProvider | None = None,
    ) -> dict[str, Any]:
        if not isinstance(sdp, str) or not sdp.strip():
            raise WebRtcTransportError(400, "invalid_offer", "WebRTC offer SDP is required.")
        if offer_type != "offer":
            raise WebRtcTransportError(400, "invalid_offer_type", "WebRTC SDP type must be 'offer'.")
        if camera_service is None:
            raise WebRtcTransportError(503, "camera_service_unavailable", "Camera service is not running.")

        feed = camera_service.get_feed(role) if hasattr(camera_service, "get_feed") else None
        if feed is None:
            raise WebRtcTransportError(404, "camera_feed_not_active", f"Camera feed '{role}' is not active.")

        physical_source = _feed_source_key(feed)
        device_id = _feed_device_id(feed)
        if physical_source is None or device_id is None:
            raise WebRtcTransportError(
                409,
                "camera_source_unassigned",
                f"Camera feed '{role}' has no assigned physical source.",
            )

        media_plane = media_plane_payload or describe_media_plane(camera_service)
        evaluation = evaluate_transport_gates(media_plane)
        session_roles: list[str] = []
        for source in media_plane.get("physical_sources", []):
            if source.get("source") == physical_source:
                session_roles = [
                    str(item)
                    for item in source.get("roles", [])
                    if isinstance(item, str)
                ]
                break
        if not session_roles:
            session_roles = [role]

        with self._lock:
            session = self._ensure_session(
                physical_source=physical_source,
                roles=session_roles,
                device_id=device_id,
                evaluation=evaluation,
            )
            session.offer_count += 1
            session.last_offer_at = time.time()
            session.updated_at = session.last_offer_at

        if not evaluation.get("gates", {}).get("target_ready"):
            raise WebRtcTransportError(
                503,
                "hardware_webrtc_transport_unavailable",
                "Hardware H.264 WebRTC transport is not ready on this host.",
                payload={
                    "role": role,
                    "physical_source": physical_source,
                    "session": session.as_dict(),
                    "metadata_data_channel": camera_metadata_data_channel_spec(),
                    "gates": evaluation.get("gates", {}),
                    "blockers": evaluation.get("blockers", []),
                    "migration_warnings": evaluation.get("migration_warnings", []),
                    "selected_encoder_path": evaluation.get("selected_encoder_path"),
                },
            )

        if not evaluation.get("gates", {}).get("webrtc_hardware_bridge_implemented"):
            raise WebRtcTransportError(
                501,
                "hardware_webrtc_bridge_not_implemented",
                "Hardware encoder is ready, but the encoded-frame WebRTC bridge is not implemented yet.",
                payload={
                    "role": role,
                    "physical_source": physical_source,
                    "session": session.as_dict(),
                    "metadata_data_channel": camera_metadata_data_channel_spec(),
                    "selected_encoder_path": evaluation.get("selected_encoder_path"),
                },
            )

        if not evaluation.get("gates", {}).get("target_architecture_compliant"):
            raise WebRtcTransportError(
                409,
                "hardware_webrtc_transport_noncompliant",
                "Hardware H.264 WebRTC transport is available, but the active media-plane does not satisfy the target architecture.",
                payload={
                    "role": role,
                    "physical_source": physical_source,
                    "session": session.as_dict(),
                    "metadata_data_channel": camera_metadata_data_channel_spec(),
                    "gates": evaluation.get("gates", {}),
                    "blockers": evaluation.get("blockers", []),
                    "migration_warnings": evaluation.get("migration_warnings", []),
                    "selected_encoder_path": evaluation.get("selected_encoder_path"),
                },
            )

        source = await self._get_or_create_hardware_source(
            physical_source=physical_source,
            roles=session_roles,
            feed=feed,
            session=session,
            selected_encoder_path=evaluation.get("selected_encoder_path"),
        )
        return await self._create_hardware_answer(
            role=role,
            physical_source=physical_source,
            session=session,
            source=source,
            sdp=sdp,
            offer_type=offer_type,
            selected_encoder_path=evaluation.get("selected_encoder_path"),
            metadata_provider=metadata_provider,
        )

    async def _get_or_create_hardware_source(
        self,
        *,
        physical_source: str,
        roles: list[str],
        feed: Any,
        session: WebRtcSourceSession,
        selected_encoder_path: dict[str, Any] | None,
    ) -> Any:
        create_lock = self._source_create_lock(physical_source)
        async with create_lock:
            return await self._get_or_create_hardware_source_locked(
                physical_source=physical_source,
                roles=roles,
                feed=feed,
                session=session,
                selected_encoder_path=selected_encoder_path,
            )

    def _source_create_lock(self, physical_source: str) -> asyncio.Lock:
        with self._lock:
            create_lock = self._source_create_locks.get(physical_source)
            if create_lock is None:
                create_lock = asyncio.Lock()
                self._source_create_locks[physical_source] = create_lock
            return create_lock

    async def _get_or_create_hardware_source_locked(
        self,
        *,
        physical_source: str,
        roles: list[str],
        feed: Any,
        session: WebRtcSourceSession,
        selected_encoder_path: dict[str, Any] | None,
    ) -> Any:
        with self._lock:
            existing = self._hardware_sources.get(physical_source)
            factory = self._hardware_source_factory
        if existing is not None:
            return existing
        if factory is None:
            raise WebRtcTransportError(
                501,
                "hardware_h264_source_unavailable",
                "Hardware WebRTC bridge is enabled, but no hardware H.264 source factory is registered.",
                payload={
                    "physical_source": physical_source,
                    "roles": roles,
                    "session": session.as_dict(),
                    "selected_encoder_path": selected_encoder_path,
                },
            )

        try:
            source = factory(
                physical_source=physical_source,
                roles=list(roles),
                feed=feed,
                session=session,
                selected_encoder_path=selected_encoder_path,
            )
            if inspect.isawaitable(source):
                source = await source
        except WebRtcTransportError:
            raise
        except Exception as exc:
            raise WebRtcTransportError(
                501,
                "hardware_h264_source_unavailable",
                f"Hardware H.264 source could not be created: {exc}",
                payload={
                    "physical_source": physical_source,
                    "roles": roles,
                    "session": session.as_dict(),
                    "selected_encoder_path": selected_encoder_path,
                },
            ) from exc
        if isinstance(source, HardwareH264SourceFanout):
            fanout = source
        elif hasattr(source, "recv_encoded_h264"):
            fanout = HardwareH264SourceFanout(source)
        else:
            raise WebRtcTransportError(
                501,
                "hardware_h264_source_invalid",
                "Hardware H.264 source must expose recv_encoded_h264().",
                payload={"physical_source": physical_source, "session": session.as_dict()},
            )
        with self._lock:
            cached = self._hardware_sources.get(physical_source)
            if cached is not None:
                return cached
            self._hardware_sources[physical_source] = fanout
        return fanout

    async def _create_hardware_answer(
        self,
        *,
        role: str,
        physical_source: str,
        session: WebRtcSourceSession,
        source: Any,
        sdp: str,
        offer_type: str,
        selected_encoder_path: dict[str, Any] | None,
        metadata_provider: CameraMetadataProvider | None,
    ) -> dict[str, Any]:
        from aiortc import RTCPeerConnection, RTCRtpSender, RTCSessionDescription

        # Belt-and-suspenders against churn: drop any already-dead peers for this
        # source and cap how many can coexist, so a rapidly-retrying client can
        # never pile up zombie encoders even if a teardown is briefly delayed.
        await self._reap_dead_peers(physical_source)

        peer = RTCPeerConnection()
        if not hasattr(source, "subscribe"):
            await peer.close()
            raise WebRtcTransportError(
                501,
                "hardware_h264_fanout_unavailable",
                "Hardware H.264 source fanout is not available.",
                payload={"physical_source": physical_source, "session": session.as_dict()},
            )
        subscription = source.subscribe()

        def _on_track_stop() -> None:
            subscription.close()
            try:
                asyncio.create_task(self._drop_peer(physical_source, peer))
            except RuntimeError:
                pass

        track = HardwareH264PacketTrack(subscription, on_stop=_on_track_stop)
        transceiver = peer.addTransceiver(track, direction="sendonly")
        h264_codecs = [
            codec for codec in RTCRtpSender.getCapabilities("video").codecs
            if codec.mimeType.lower() == "video/h264"
        ]
        if not h264_codecs:
            subscription.close()
            await peer.close()
            raise WebRtcTransportError(
                501,
                "browser_h264_negotiation_unavailable",
                "aiortc does not expose an H.264 RTP packetizer.",
                payload={"physical_source": physical_source, "session": session.as_dict()},
            )
        transceiver.setCodecPreferences(h264_codecs)

        @peer.on("connectionstatechange")
        async def _on_connection_state_change() -> None:
            if peer.connectionState in {"failed", "closed", "disconnected"}:
                await self._drop_peer(physical_source, peer)

        metadata_spec = camera_metadata_data_channel_spec()
        metadata_label = str(metadata_spec["label"])
        if metadata_provider is not None:

            @peer.on("datachannel")
            def _on_datachannel(channel: Any) -> None:
                if getattr(channel, "label", None) != metadata_label:
                    return
                self._register_metadata_sender(
                    peer=peer,
                    role=role,
                    channel=channel,
                    metadata_provider=metadata_provider,
                )

        try:
            await peer.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=offer_type))
            answer = await peer.createAnswer()
            await peer.setLocalDescription(answer)
            await _wait_for_ice_gathering_complete(peer)
        except Exception as exc:
            subscription.close()
            metadata_tasks = self._pop_peer_metadata_tasks(peer)
            await peer.close()
            await _cancel_tasks(metadata_tasks)
            raise WebRtcTransportError(
                400,
                "webrtc_answer_failed",
                f"Could not create hardware H.264 WebRTC answer: {exc}",
                payload={"physical_source": physical_source, "session": session.as_dict()},
            ) from exc

        local = peer.localDescription
        if local is None or not local.sdp or "H264" not in local.sdp:
            subscription.close()
            metadata_tasks = self._pop_peer_metadata_tasks(peer)
            await peer.close()
            await _cancel_tasks(metadata_tasks)
            raise WebRtcTransportError(
                406,
                "browser_h264_codec_not_negotiated",
                "The WebRTC offer did not negotiate H.264, and software transcoding is forbidden.",
                payload={"physical_source": physical_source, "session": session.as_dict()},
            )

        with self._lock:
            self._peers_by_source.setdefault(physical_source, set()).add(peer)
            self._track_subscriptions_by_peer.setdefault(peer, set()).add(subscription)
            session.active_peer_count = len(self._peers_by_source.get(physical_source, set()))
            session.encoder_instances_active = 1
            session.state = "answer_created"
            session.updated_at = time.time()

        return {
            "ok": True,
            "type": local.type,
            "sdp": local.sdp,
            "role": role,
            "physical_source": physical_source,
            "session": session.as_dict(),
            "transport": "webrtc",
            "video_codec": "h264",
            "encoder": "rockchip_mpp",
            "metadata_data_channel": camera_metadata_data_channel_spec(),
            "metadata_payload_contains_pixels": False,
            "selected_encoder_path": selected_encoder_path,
            "software_h264_fallback_allowed": False,
        }

    def _register_metadata_sender(
        self,
        *,
        peer: Any,
        role: str,
        channel: Any,
        metadata_provider: CameraMetadataProvider,
    ) -> None:
        task = asyncio.create_task(
            _send_camera_metadata_loop(
                role=role,
                channel=channel,
                metadata_provider=metadata_provider,
                interval_s=_METADATA_SEND_INTERVAL_S,
            )
        )
        with self._lock:
            self._metadata_tasks_by_peer.setdefault(peer, set()).add(task)

        def _forget(done_task: asyncio.Task[Any]) -> None:
            with self._lock:
                tasks = self._metadata_tasks_by_peer.get(peer)
                if tasks is None:
                    return
                tasks.discard(done_task)
                if not tasks:
                    self._metadata_tasks_by_peer.pop(peer, None)

        task.add_done_callback(_forget)

    def _pop_peer_metadata_tasks(self, peer: Any) -> list[asyncio.Task[Any]]:
        with self._lock:
            return list(self._metadata_tasks_by_peer.pop(peer, set()))

    async def _reap_dead_peers(self, physical_source: str, *, max_peers: int = 4) -> None:
        """Drop already-dead peers for a source and cap coexisting peers.

        Defensive bound on top of the per-peer ``_close_peer`` teardown: enforces
        the one-active-encoder-per-source invariant under client churn so a
        transient stall + retry storm cannot accumulate zombies.
        """
        dead_states = {"failed", "closed", "disconnected"}
        with self._lock:
            peers = list(self._peers_by_source.get(physical_source, set()))
        for peer in peers:
            if getattr(peer, "connectionState", None) in dead_states:
                await self._drop_peer(physical_source, peer)
        with self._lock:
            remaining = list(self._peers_by_source.get(physical_source, set()))
        # Still over budget → evict not-yet-connected peers (never an
        # established viewer) until within the cap.
        if len(remaining) > max_peers:
            evictable = [
                peer
                for peer in remaining
                if getattr(peer, "connectionState", None) != "connected"
            ]
            for peer in evictable[: len(remaining) - max_peers]:
                await self._drop_peer(physical_source, peer)

    async def _drop_peer(self, physical_source: str, peer: Any) -> None:
        source_to_stop = None
        metadata_tasks: list[asyncio.Task[Any]]
        subscriptions: list[Any]
        with self._lock:
            metadata_tasks = list(self._metadata_tasks_by_peer.pop(peer, set()))
            subscriptions = list(self._track_subscriptions_by_peer.pop(peer, set()))
            peers = self._peers_by_source.get(physical_source)
            if peers is not None:
                peers.discard(peer)
                if not peers:
                    self._peers_by_source.pop(physical_source, None)
                    source_to_stop = self._hardware_sources.pop(physical_source, None)
            elif physical_source in self._hardware_sources:
                source_to_stop = self._hardware_sources.pop(physical_source, None)
            session = self._sessions.get(physical_source)
            if session is not None:
                session.active_peer_count = len(self._peers_by_source.get(physical_source, set()))
                session.encoder_instances_active = 1 if session.active_peer_count > 0 else 0
                if session.active_peer_count <= 0 and session.state == "answer_created":
                    session.state = "ready_for_offer"
                session.updated_at = time.time()
        for subscription in subscriptions:
            close = getattr(subscription, "close", None)
            if callable(close):
                close()
        await _cancel_tasks(metadata_tasks)
        if source_to_stop is not None:
            await _stop_hardware_source(source_to_stop)
        await _close_peer(peer)


async def _wait_for_ice_gathering_complete(peer: Any, timeout_s: float = 2.0) -> None:
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


async def _close_peer(peer: Any) -> None:
    """Close an RTCPeerConnection once, idempotently.

    Dropping a peer must actually close it so its ICE/DTLS transport ends
    immediately; otherwise the connection lingers ~30-60s until ICE times out,
    and a rapidly-retrying client piles up zombie peers. Guarded so the
    track-stop and connection-state-change paths can't double-close.
    """
    if peer is None:
        return
    if getattr(peer, "_sorter_closing", False):
        return
    try:
        peer._sorter_closing = True
    except Exception:
        pass
    close = getattr(peer, "close", None)
    if not callable(close):
        return
    try:
        result = close()
        if inspect.isawaitable(result):
            await result
    except Exception:
        pass


async def _stop_hardware_source(source: Any) -> None:
    stop = getattr(source, "stop", None)
    if not callable(stop):
        return
    result = stop()
    if inspect.isawaitable(result):
        await result


async def _cancel_tasks(tasks: list[asyncio.Task[Any]]) -> None:
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _metadata_payload_for_role(
    metadata_provider: CameraMetadataProvider,
    role: str,
) -> dict[str, Any]:
    payload = metadata_provider(role)
    if inspect.isawaitable(payload):
        payload = await payload
    if isinstance(payload, dict):
        return payload
    return {
        "ok": False,
        "role": role,
        "message_type": "camera.feed_metadata",
        "detail": "Camera metadata provider returned a non-object payload.",
    }


def _metadata_frame_timestamp(payload: dict[str, Any]) -> float | None:
    frame = payload.get("frame")
    if not isinstance(frame, dict):
        return None
    timestamp = frame.get("timestamp")
    return float(timestamp) if isinstance(timestamp, (int, float)) else None


def _metadata_error_payload(role: str, exc: Exception) -> dict[str, Any]:
    return {
        "ok": False,
        "role": role,
        "message_type": "camera.feed_metadata",
        "status_code": int(getattr(exc, "status_code", 500) or 500),
        "detail": str(getattr(exc, "detail", None) or exc),
    }


async def _send_camera_metadata_loop(
    *,
    role: str,
    channel: Any,
    metadata_provider: CameraMetadataProvider,
    interval_s: float = _METADATA_SEND_INTERVAL_S,
) -> None:
    last_frame_ts: float | None = None
    sleep_s = max(0.033, float(interval_s))
    while getattr(channel, "readyState", "closed") != "closed":
        if getattr(channel, "readyState", None) != "open":
            await asyncio.sleep(min(0.05, sleep_s))
            continue
        try:
            payload = await _metadata_payload_for_role(metadata_provider, role)
        except Exception as exc:
            payload = _metadata_error_payload(role, exc)

        frame_ts = _metadata_frame_timestamp(payload)
        if frame_ts is None or frame_ts != last_frame_ts:
            channel.send(json.dumps(payload, separators=(",", ":"), allow_nan=False))
            last_frame_ts = frame_ts
        await asyncio.sleep(sleep_s)


def _default_hardware_source_factory() -> HardwareH264SourceFactory | None:
    capture_backend = os.environ.get("SORTER_CAMERA_CAPTURE_BACKEND", "").lower()
    gstreamer_capture_enabled = os.environ.get("SORTER_ENABLE_GSTREAMER_MPP_CAPTURE", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if capture_backend in {"gstreamer", "gstreamer_mpp", "mpp"} or gstreamer_capture_enabled:
        from .gstreamer_h264_source import create_gstreamer_capture_h264_source

        return create_gstreamer_capture_h264_source

    enabled = os.environ.get("SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not enabled:
        return None
    from .ffmpeg_h264_source import create_ffmpeg_rkmpp_h264_source

    return create_ffmpeg_rkmpp_h264_source


_REGISTRY = CameraWebRtcSessionRegistry(hardware_source_factory=_default_hardware_source_factory())


def get_camera_webrtc_registry() -> CameraWebRtcSessionRegistry:
    return _REGISTRY
