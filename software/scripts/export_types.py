"""Generate the frontend's events.ts from the pydantic models in defs.events.

Run after ANY change to defs/events.py:

    python software/scripts/export_types.py software/sorter/frontend/src/lib/api/events.ts

or, from anywhere, with no arguments — it defaults to that path:

    python software/scripts/export_types.py

``--check`` regenerates into a temp file and diffs it against the committed one
without writing, exiting non-zero when they differ. tests/test_events_ts_is_current.py
runs this so a stale events.ts fails at the commit that caused it, instead of
ambushing whoever regenerates months later with an unrelated 150-line diff.

Determinism note: pydantic2ts shells out to ``json2ts``. Left to itself it
resolves that off $PATH — i.e. whatever json-schema-to-typescript happens to be
installed GLOBALLY on that machine — even though the frontend already pins the
package in its devDependencies. We pass the repo-local binary explicitly so the
output depends on the lockfile and not on the developer.
"""

import argparse
import filecmp
import os
import shutil
import subprocess
import sys
import tempfile

REPO_SOFTWARE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_SOFTWARE, "sorter", "backend"))

from pydantic2ts import generate_typescript_defs  # noqa: E402
from defs.events import SocketEvent  # noqa: E402
from typing import get_args  # noqa: E402

DEFAULT_OUTPUT = os.path.join(
    REPO_SOFTWARE, "sorter", "frontend", "src", "lib", "api", "events.ts"
)
LOCAL_JSON2TS = os.path.join(
    REPO_SOFTWARE, "sorter", "frontend", "node_modules", ".bin", "json2ts"
)
REGEN_HINT = "python software/scripts/export_types.py"


def json2tsCommand() -> str:
    if os.path.isfile(LOCAL_JSON2TS) and os.access(LOCAL_JSON2TS, os.X_OK):
        return LOCAL_JSON2TS
    fallback = shutil.which("json2ts")
    if fallback is None:
        raise SystemExit(
            "json2ts not found. Install the frontend deps first:\n"
            "  cd software/sorter/frontend && npm install"
        )
    # Deliberately loud: a global json2ts is a different version from the one
    # the lockfile pins, so the generated file may differ from everyone else's.
    print(
        f"WARNING: using global json2ts ({fallback}) — "
        f"{LOCAL_JSON2TS} is missing. Run `npm install` in software/sorter/frontend "
        f"for reproducible output.",
        file=sys.stderr,
    )
    return fallback


def exportSocketEvent(output_path: str) -> None:
    generate_typescript_defs(
        "defs.events",
        output_path,
        exclude=["ServerToMainThreadEvent", "MainThreadToServerCommand"],
        json2ts_cmd=json2tsCommand(),
    )

    # dynamically generate SocketEvent union from Python union type
    event_types = get_args(SocketEvent)
    if not event_types:
        # single type union gets simplified by Python
        union_str = SocketEvent.__name__
    else:
        union_str = " | ".join([t.__name__ for t in event_types])

    with open(output_path, "a") as f:
        f.write(f"\nexport type SocketEvent = {union_str};\n")


def check(output_path: str) -> int:
    if not os.path.isfile(output_path):
        print(f"{output_path} does not exist — run:\n  {REGEN_HINT}", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        candidate = os.path.join(tmp, "events.ts")
        exportSocketEvent(candidate)
        if filecmp.cmp(candidate, output_path, shallow=False):
            print(f"{output_path} is up to date.")
            return 0
        print(
            f"{output_path} is STALE — it does not match defs/events.py.\n"
            f"Regenerate it in the same change that touched the models:\n"
            f"  {REGEN_HINT}\n",
            file=sys.stderr,
        )
        # Show the diff so the caller can see whether it's their change or
        # accumulated drift from someone else's.
        subprocess.run(
            ["diff", "-u", output_path, candidate],
            check=False,
        )
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("output", nargs="?", default=DEFAULT_OUTPUT)
    ap.add_argument(
        "--check",
        action="store_true",
        help="Verify the committed file matches the models; write nothing.",
    )
    args = ap.parse_args()
    if args.check:
        return check(args.output)
    exportSocketEvent(args.output)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
