"""Where this machine's config file, machine.toml, is.

Every reader and writer of it asks machine_toml_path(); nothing else reads
MACHINE_SPECIFIC_PARAMS_PATH. When a dozen places each read the variable with a
fallback of their own, settings saved from the UI could land in a file the
running machine never read.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "MACHINE_SPECIFIC_PARAMS_PATH"
BACKEND_DIR = Path(__file__).resolve().parent
DEFAULT_PATH = BACKEND_DIR.parents[1] / "machine.toml"  # software/, beside machine.example.toml


def machine_toml_path() -> Path:
    """software/machine.toml, or MACHINE_SPECIFIC_PARAMS_PATH if it's set.

    A relative value is taken from the backend directory: machines set it in
    software/.env as "../../machine.toml", written for a backend started there,
    and a script started anywhere else has to find the same file."""
    raw = os.environ.get(ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_PATH
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()
