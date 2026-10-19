"""The defaults this sorter's primary Hive holds for every sorter.

Every setting a person can change has its default in this sorter's code, so it
works with no Hive at all. Hive also holds a block of defaults it can change for
the whole fleet (Hive's services/machine_defaults.py). Every heartbeat reply
names the block's version; when the primary Hive's differs from the one kept
here, the block is fetched again (GET /api/machine/defaults, through
hive_uploads). A value from the block replaces the code's default; a setting
the person saved wins over both.

The block is nested by namespace, and value() reads one leaf by its path:

- sharing.<stream>: whether an optional stream is shared (sharing.py).
- steppers.* and steppers.<motor>.<setting>: the driver settings
  (hardware_settings/steppers.py). A driver takes its settings at start, so a
  changed default reaches it at the next start.
- sample_capture.<setting>.

Each reader checks a value as it checks a saved one, so a value from a newer
Hive that this sorter cannot use is ignored. What is kept (local_state
`hive_defaults`): the target it came from, the version, the block, and when it
was received; a restart with Hive unreachable keeps using it.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

_lock = threading.Lock()
_cached: dict[str, Any] | None = None


def _state() -> dict[str, Any]:
    global _cached
    with _lock:
        if _cached is None:
            from local_state import get_hive_defaults_state

            raw = get_hive_defaults_state()
            _cached = raw if isinstance(raw, dict) and isinstance(raw.get("defaults"), dict) else {}
        return _cached


def invalidate() -> None:
    """Read what is kept again on next use (tests)."""
    global _cached
    with _lock:
        _cached = None


def status() -> dict[str, Any]:
    """Where the defaults in use come from, for the settings pages."""
    state = _state()
    return {
        "target_id": state.get("target_id"),
        "version": state.get("version"),
        "received_at": state.get("received_at"),
    }


def namespace(name: str) -> dict[str, Any]:
    block = _state().get("defaults") or {}
    value = block.get(name)
    return value if isinstance(value, dict) else {}


def value(path: str, code_default: Any, valid: Callable[[Any], bool]) -> Any:
    """Hive's default at `path` ("sharing.network"), or the code's when Hive
    has none this sorter can use."""
    node: Any = _state().get("defaults") or {}
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return code_default
        node = node[part]
    try:
        return node if valid(node) else code_default
    except Exception:
        return code_default


def noteVersion(target_id: str, version: Any, fetch: Callable[[str | None], dict[str, Any] | None]) -> bool:
    """The primary Hive's heartbeat named `version`. Fetch the block when it is
    not the one kept (`fetch(etag)` returns the block, or None when the Hive
    answered that it is unchanged). True when a new block was kept."""
    if not isinstance(version, str) or not version:
        return False
    state = _state()
    if state.get("version") == version and state.get("target_id") == target_id:
        return False
    etag = f'"{state["version"]}"' if state.get("target_id") == target_id and state.get("version") else None
    try:
        block = fetch(etag)
    except Exception as exc:
        log.warning("hive defaults: could not fetch version %s: %s", version, exc)
        return False
    if block is None:
        return False
    defaults = block.get("defaults") if isinstance(block, dict) else None
    fetched_version = block.get("version") if isinstance(block, dict) else None
    if not isinstance(defaults, dict) or not isinstance(fetched_version, str):
        log.warning("hive defaults: the block from %s has no defaults; keeping the one we have", target_id)
        return False
    keep(target_id, fetched_version, defaults)
    log.info("hive defaults: now version %s from %s", fetched_version, target_id)
    return True


def keep(target_id: str, version: str, defaults: dict[str, Any]) -> None:
    global _cached
    from local_state import set_hive_defaults_state

    state = {"target_id": target_id, "version": version, "defaults": defaults, "received_at": time.time()}
    with _lock:
        set_hive_defaults_state(state)
        _cached = state
