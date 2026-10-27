"""The machine's saved zones.

They live in local_state under the blob the old zone editor wrote, as a
``zones`` document beside the old keys, which every save writes again from the
zones: a machine switched back to an older version keeps its zones.
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from typing import Any, Callable, Mapping

import local_state

from .model import CHANNELS, ChannelZones, fromDict, fromLegacyBlob, toDict, toLegacyBlob

DOCUMENT_VERSION = 1

_lock = threading.Lock()
_listeners: list[Callable[[], None]] = []


def loadZones() -> dict[int, ChannelZones]:
    blob = local_state.get_channel_zones_blob() or {}
    doc = blob.get("zones")
    if isinstance(doc, Mapping) and isinstance(doc.get("channels"), Mapping):
        out: dict[int, ChannelZones] = {}
        for key, raw in doc["channels"].items():
            try:
                channel = int(key)
            except (TypeError, ValueError):
                continue
            zones = fromDict(raw, channel)
            if zones is not None:
                out[channel] = zones
        return out
    return fromLegacyBlob(blob)


def loadChannel(channel: int) -> ChannelZones | None:
    return loadZones().get(channel)


def revision() -> int:
    return local_state.channel_zones_revision()


def saveZones(zones_by_channel: Mapping[int, ChannelZones]) -> dict[int, ChannelZones]:
    kept = {ch: z for ch, z in zones_by_channel.items() if ch in CHANNELS}
    blob: dict[str, Any] = toLegacyBlob(kept)
    blob["zones"] = {
        "version": DOCUMENT_VERSION,
        "channels": {str(ch): toDict(z) for ch, z in sorted(kept.items())},
    }
    local_state.set_channel_zones_blob(blob)
    for listener in list(_listeners):
        try:
            listener()
        except Exception:
            pass
    return kept


def saveChannel(zones: ChannelZones) -> dict[int, ChannelZones]:
    with _lock:
        current = loadZones()
        current[zones.channel] = _stamped(zones)
        return saveZones(current)


def updateChannel(channel: int, change: Callable[[ChannelZones], ChannelZones | None]) -> ChannelZones | None:
    """Apply ``change`` to the saved zones of one channel under the store's
    lock, so an adjustment made while running never overwrites an edit saved
    a moment before. Saves only when ``change`` returns new zones."""
    with _lock:
        current = loadZones()
        before = current.get(channel)
        if before is None:
            return None
        after = change(before)
        if after is None or after == before:
            return before
        current[channel] = _stamped(after)
        saveZones(current)
        return current[channel]


def deleteChannel(channel: int) -> dict[int, ChannelZones]:
    with _lock:
        current = loadZones()
        current.pop(channel, None)
        return saveZones(current)


def subscribe(listener: Callable[[], None]) -> Callable[[], None]:
    _listeners.append(listener)

    def unsubscribe() -> None:
        if listener in _listeners:
            _listeners.remove(listener)

    return unsubscribe


def _stamped(zones: ChannelZones) -> ChannelZones:
    return replace(zones, updated_at=round(time.time(), 3))
