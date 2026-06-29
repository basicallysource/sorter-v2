"""Single source of truth for where persistent machine state lives.

All calibration/config state (camera assignment, polygons, aruco config, baselines,
records, machine id) is stored under one directory chosen by the ``CONFIG_DIR`` env var.
On the AGX this points at the ``sv2_configs`` store (alongside ``.env``, sorting_profile,
bin_layout, etc.), so state survives re-cloning the repo and there is one place to back up.

If ``CONFIG_DIR`` is unset (e.g. local dev) it falls back to the ``client/`` folder, the
historical location. ``.env`` must be loaded before this module is first imported.
"""

import os
from pathlib import Path

_FALLBACK_DIR = Path(__file__).resolve().parent

CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", str(_FALLBACK_DIR))).expanduser()


def config_path(name: str) -> Path:
    """Absolute path to ``name`` inside the active config dir."""
    return CONFIG_DIR / name
