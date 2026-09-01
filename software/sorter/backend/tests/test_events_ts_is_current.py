"""Fail when the generated events.ts no longer matches defs/events.py.

events.ts is generated but checked in, and nothing used to enforce that the two
agreed. Editing the models without regenerating is invisible until someone else
regenerates months later and gets a huge reformat plus type errors in unrelated
files — which is exactly what happened (a field went from required to optional
and broke two call sites, and a whole event type had been missing).

This puts the failure at the commit that causes it. It shells out rather than
importing so the diff lands in the test output verbatim.
"""

import os
import shutil
import subprocess
import sys

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOFTWARE_DIR = os.path.dirname(os.path.dirname(BACKEND_DIR))
SCRIPT = os.path.join(SOFTWARE_DIR, "scripts", "export_types.py")
LOCAL_JSON2TS = os.path.join(
    SOFTWARE_DIR, "sorter", "frontend", "node_modules", ".bin", "json2ts"
)


def _json2ts_available() -> bool:
    return os.path.isfile(LOCAL_JSON2TS) or shutil.which("json2ts") is not None


@pytest.mark.skipif(
    not _json2ts_available(),
    reason="json2ts unavailable (frontend deps not installed) — nothing to check against",
)
def test_events_ts_matches_pydantic_models() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, "--check"],
        capture_output=True,
        text=True,
        cwd=SOFTWARE_DIR,
    )
    assert result.returncode == 0, (
        "events.ts is out of date with defs/events.py.\n"
        "Regenerate it in this same change:\n"
        "  python software/scripts/export_types.py\n\n"
        f"{result.stdout}\n{result.stderr}"
    )
