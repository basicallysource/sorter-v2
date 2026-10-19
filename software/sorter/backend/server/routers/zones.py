"""A channel's zones: read them, save them, and find them in its camera's pictures."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from server import shared_state
from zones import watch
from zones.finder import defaultZones, findInChild
from zones.model import CAMERA_ROLE, CHANNELS, fromDict, toDict
from zones.store import loadZones, revision, saveChannel

router = APIRouter()


def _channel(channel: int) -> int:
    if channel not in CHANNELS:
        raise HTTPException(status_code=404, detail=f"Channel {channel} has no zones; channels are 2, 3 and 4.")
    return channel


def _cameraFrames(channel: int) -> list:
    service = shared_state.camera_service
    if service is None:
        raise HTTPException(status_code=503, detail="The cameras are not running.")
    thread = service.get_capture_thread_for_role(CAMERA_ROLE[channel])
    if thread is None:
        raise HTTPException(status_code=404, detail=f"No camera is set for channel {channel}.")
    recent = [f.raw for f in thread.drain_ring_buffer(60)[::10] if getattr(f, "raw", None) is not None]
    if not recent and thread.latest_frame is not None:
        recent = [thread.latest_frame.raw]
    if not recent:
        raise HTTPException(status_code=503, detail=f"Channel {channel}'s camera has no picture yet.")
    return recent


@router.get("/api/zones")
def getZones() -> Dict[str, Any]:
    zones = loadZones()
    return {
        "revision": revision(),
        "channels": {str(ch): toDict(zones[ch]) if ch in zones else None for ch in CHANNELS},
    }


@router.put("/api/zones/{channel}")
def putZones(channel: int, body: Dict[str, Any]) -> Dict[str, Any]:
    zones = fromDict(body, _channel(channel))
    if zones is None:
        raise HTTPException(
            status_code=400,
            detail="Zones need frame, center, inner_radius, outer_radius, and drop and exit with start and end.",
        )
    saved = saveChannel(zones)[channel]
    return {"revision": revision(), "zones": toDict(saved)}


@router.post("/api/zones/{channel}/find")
def findChannelZones(channel: int) -> Dict[str, Any]:
    """Zones found in the channel's pictures, not saved: the editor shows them
    and the person saves them. Pictures from the last minutes of running are
    used when there are some, so pieces and the turning disc average out."""
    _channel(channel)
    live = _cameraFrames(channel)
    h, w = live[0].shape[:2]
    history = watch.recentFrames(channel)
    current = loadZones().get(channel)
    try:
        found = findInChild(channel, history + live if len(history) >= 3 else live, current, (w, h))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"The zones could not be found: {exc}")
    return {"zones": toDict(found.zones), "report": found.report()}


@router.get("/api/zones/watch")
def pieceWatch() -> Dict[str, Any]:
    """What the machine has seen of its pieces while running: how many it saw
    fall and land on the next channel, and how long landing took."""
    running = watch.current()
    if running is None:
        return {"running": False}
    return {"running": True, **running.report()}


@router.get("/api/zones/{channel}/default")
def defaultChannelZones(channel: int) -> Dict[str, Any]:
    """A start for a channel with nothing saved, at its camera's size."""
    live = _cameraFrames(_channel(channel))
    h, w = live[0].shape[:2]
    return {"zones": toDict(defaultZones(channel, (w, h)))}
