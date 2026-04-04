from __future__ import annotations

import sys
from pathlib import Path


PROFILE_BUILDER_DIR = Path(__file__).resolve().parents[4] / "sorting_profile_builder"

if str(PROFILE_BUILDER_DIR) not in sys.path:
    sys.path.insert(0, str(PROFILE_BUILDER_DIR))

import db as builder_db  # type: ignore  # noqa: E402
import parts_cache as builder_parts_cache  # type: ignore  # noqa: E402
import rule_engine as builder_rule_engine  # type: ignore  # noqa: E402
import sorting_profile as builder_sorting_profile  # type: ignore  # noqa: E402


__all__ = [
    "PROFILE_BUILDER_DIR",
    "builder_db",
    "builder_parts_cache",
    "builder_rule_engine",
    "builder_sorting_profile",
]
