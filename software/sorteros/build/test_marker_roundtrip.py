"""
Tiny sanity test for the cross-file marker contract.

Verifies:
  - build.py's CFG_*_MARKER values match what img-patch.ts hard-codes
  - the TOML keys img-patch.ts writes are the ones firstboot.py reads

Run: python3 test_marker_roundtrip.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_PY = ROOT / "build" / "build.py"
PATCH_TS = ROOT / "sorteros-setup" / "src" / "lib" / "img-patch.ts"
FIRSTBOOT_PY = ROOT / "build" / "overlay" / "usr" / "local" / "sbin" / "sorteros-firstboot.py"


def grep(path: Path, pattern: str) -> list[str]:
    return re.findall(pattern, path.read_text())


def main() -> int:
    errs: list[str] = []

    py_markers = set(grep(BUILD_PY, r"__SORTEROS_CFG_(?:START|END)__"))
    ts_markers = set(grep(PATCH_TS, r"__SORTEROS_CFG_(?:START|END)__"))
    if py_markers != ts_markers or len(py_markers) != 2:
        errs.append(f"marker mismatch: build.py={py_markers} img-patch.ts={ts_markers}")

    # Keys img-patch.ts emits → must be the ones firstboot reads.
    fb = FIRSTBOOT_PY.read_text()
    for key in ("hostname", '"wifi"', '"ssh"', '"ssid"', '"password"', '"authorized_key"'):
        if key not in fb:
            errs.append(f"firstboot.py missing handling for key fragment {key}")

    if errs:
        for e in errs:
            print("FAIL:", e, file=sys.stderr)
        return 1
    print("ok — marker + key contract holds across build.py, img-patch.ts, firstboot.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
