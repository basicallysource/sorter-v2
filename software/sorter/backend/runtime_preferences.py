"""Shared reader for ``blob/runtime_preferences.json``.

The file is written by the ``/api/runtimes/preferences`` endpoint and maps a
model-format id (``"onnx"``, ``"ncnn"``, ...) to the user's preferred option
id for that format (``"ncnn-vulkan"``, ``"onnx-coreml"``, ...).

Both the benchmark route and the production ML factory import from here so
the live inference path honors whatever the UI last selected.

Kept at the backend root (not under ``server/``) so ``vision/ml/factory.py``
can import it without dragging in FastAPI / pydantic.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path


log = logging.getLogger(__name__)


PREFS_PATH = Path(__file__).resolve().parent / "blob" / "runtime_preferences.json"


def read_runtime_preferences(path: Path | None = None) -> dict[str, str]:
    """Return ``{format_id: option_id}`` from the prefs file, or ``{}`` if absent.

    Parsing is defensive: a corrupt or unreadable file returns ``{}`` so
    callers can fall back to their own defaults without blowing up live
    inference.
    """
    target = path or PREFS_PATH
    try:
        raw = json.loads(target.read_text())
    except FileNotFoundError:
        return {}
    except Exception as exc:  # pragma: no cover - log + ignore
        log.warning("Failed to read runtime preferences from %s: %s", target, exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}


def preferred_option(
    format_id: str,
    *,
    default: str,
    path: Path | None = None,
) -> str:
    """Return the option_id chosen for ``format_id`` or ``default``."""
    prefs = read_runtime_preferences(path=path)
    return prefs.get(format_id, default)
