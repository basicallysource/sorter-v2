"""Env-var parsing for the rt shadow-mode feature toggle.

``RT_SHADOW_FEEDS`` is a comma-separated list of role slugs (``c1``/``c2``/
``c3``/``c4``). Empty or absent means shadow mode is off. Unknown roles are
logged and skipped — we never let a typo crash the main startup path.
"""

from __future__ import annotations

import logging
import os

_LOG = logging.getLogger(__name__)


# Allowed roles for shadow feeds. These are the short rt-side slugs; the
# bootstrap layer is responsible for mapping them to the legacy camera-service
# role names ("c_channel_2", etc.) when it actually resolves a camera.
SHADOW_ROLE_ALLOWLIST: frozenset[str] = frozenset({"c1", "c2", "c3", "c4"})

_ENV_VAR = "RT_SHADOW_FEEDS"


def parse_shadow_feeds_env(env_value: str | None = None) -> list[str]:
    """Parse ``RT_SHADOW_FEEDS`` into a validated list of role slugs.

    Pass ``env_value`` directly in tests; otherwise the function reads
    ``os.environ``. Return preserves input order, de-duplicates, logs + skips
    any role outside :data:`SHADOW_ROLE_ALLOWLIST`.
    """
    raw = env_value if env_value is not None else os.environ.get(_ENV_VAR, "")
    if not raw or not raw.strip():
        return []

    roles: list[str] = []
    seen: set[str] = set()
    for token in raw.split(","):
        role = token.strip().lower()
        if not role:
            continue
        if role not in SHADOW_ROLE_ALLOWLIST:
            _LOG.warning(
                "RT shadow: skipping unknown role %r (allowed=%s)",
                role,
                sorted(SHADOW_ROLE_ALLOWLIST),
            )
            continue
        if role in seen:
            continue
        seen.add(role)
        roles.append(role)
    return roles


__all__ = ["SHADOW_ROLE_ALLOWLIST", "parse_shadow_feeds_env"]
