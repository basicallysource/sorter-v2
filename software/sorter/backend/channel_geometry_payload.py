from __future__ import annotations

from typing import Any

from perception.channel import REVERSE_TRAVEL_CHANNELS
from zones.model import CAMERA_ROLE, ChannelZones, channelPolygon
from zones.store import loadZones

# The classification channel's camera is the "carousel" role, also addressed by
# its own role name in some capture paths.
_CHANNEL_FOR_ROLE: dict[str, int] = {role: channel for channel, role in CAMERA_ROLE.items()}
_CHANNEL_FOR_ROLE.setdefault("classification_channel", 4)


def channelIdForRole(role: str) -> int | None:
    # The channel number (2, 3, 4) a camera role films; None for any other role.
    return _CHANNEL_FOR_ROLE.get(role)


def _span(name: str, start: float, end: float) -> dict[str, Any]:
    return {
        "zone_type": name,
        "start_outer_angle": round(start, 3),
        "end_outer_angle": round(end, 3),
        "start_inner_angle": round(start, 3),
        "end_inner_angle": round(end, 3),
    }


def channelGeometry(zones: ChannelZones, role: str) -> dict[str, Any]:
    # The wire shape Hive parses into sample_channel_geometry: the channel's
    # outline + the ring and its zones.
    ring = zones.ring
    arc_zones = [_span("drop", zones.drop.start, zones.drop.end), _span("exit", zones.exit.start, zones.exit.end)]
    precise = zones.precise
    if precise is not None:
        arc_zones.append(_span("precise", precise.start, precise.end))
    return {
        "source_role": role,
        "frame_width": zones.frame[0],
        "frame_height": zones.frame[1],
        "polygon": [[round(x, 1), round(y, 1)] for x, y in channelPolygon(zones)],
        "center": [round(ring.center[0], 2), round(ring.center[1], 2)],
        "inner_radius": round(ring.inner_radius, 2),
        "outer_radius": round(ring.outer_radius, 2),
        "exit_outer_radius": round(ring.exit_radius, 2),
        "section_zero_angle_deg": round(zones.reference_angle, 3),
        "reverse": zones.channel in REVERSE_TRAVEL_CHANNELS,
        "arc_zones": arc_zones,
    }


def buildChannelGeometryForRole(role: str) -> dict[str, Any] | None:
    # Read live on every sample, so a zone change shows on the next one.
    channel = channelIdForRole(role)
    if channel is None:
        return None
    zones = loadZones().get(channel)
    return channelGeometry(zones, role) if zones is not None else None
