"""The migration graph has exactly one head.

The release agent and the backend's start both run `alembic upgrade head`,
which refuses a graph with two: a deploy would fail at its first step. Two
branches that each add a migration on the same parent merge cleanly in git and
produce exactly that, so it is checked here, where CI sees it before a release.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[1]


def test_one_alembic_head():
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, (
        f"migration heads {sorted(heads)}: re-parent the newer migration onto the other "
        "(its down_revision), or add a merge migration"
    )
