#!/usr/bin/env python3
"""The popover family is one implementation kept in two places; this proves it.

docs/ and parts-calculator/ are separate npm packages with separate builds, and
nothing links them at build time, so the shared floating layer lives as a byte
identical copy in each. That is fine as long as a change to one is a change to
both, which is what this checks. Run from anywhere:

    python parts-calculator/scripts/check_popover_sync.py
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
A = ROOT / "parts-calculator" / "src" / "lib" / "popover"
B = ROOT / "docs" / "src" / "lib" / "popover"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if not A.is_dir() or not B.is_dir():
        print(f"missing popover directory: {A if not A.is_dir() else B}")
        return 1

    names_a = {p.name for p in A.iterdir() if p.is_file()}
    names_b = {p.name for p in B.iterdir() if p.is_file()}
    problems: list[str] = []

    for name in sorted(names_a - names_b):
        problems.append(f"{name}: in parts-calculator, missing from docs")
    for name in sorted(names_b - names_a):
        problems.append(f"{name}: in docs, missing from parts-calculator")
    for name in sorted(names_a & names_b):
        if digest(A / name) != digest(B / name):
            problems.append(f"{name}: the two copies differ")

    if problems:
        print("The popover family has drifted between the two apps:\n")
        for line in problems:
            print(f"  - {line}")
        print(
            "\nThey have to stay byte identical. Copy the side you changed over "
            "the other:\n"
            "  cp parts-calculator/src/lib/popover/* docs/src/lib/popover/"
        )
        return 1

    print(f"popover family in sync ({len(names_a)} files)")
    return 0


# Not wired into .github/workflows/check-parts.yml yet: this account's token has
# no `workflow` scope, so a PR from it cannot touch that file. One line, next to
# the other checks:
#
#     - run: python parts-calculator/scripts/check_popover_sync.py


if __name__ == "__main__":
    sys.exit(main())
