#!/usr/bin/env python3
"""Check that every photo and video in the docs has a credit in its caption.

Barthel asked (2026-08-26) for every image and video to carry a credit —
who took it, who rendered it, or an explicit note that the source isn't
recorded — rather than leaving photographer/renderer implicit. This walks
the content tree looking for `<img>` tags and video embeds, and checks that
one of the known credit phrases appears nearby (in the same figcaption, or
on the line right after a video embed).

This deliberately does not try to parse HTML properly: docs pages mix
Liquid, markdown and raw HTML, and a short regex window catches everything
the real convention produces without a parser. Recognized phrasing is
whatever `PR #434 <https://github.com/basicallysource/sorter-v2/pull/434>`_
established; match that style for a new page rather than inventing new
wording.

Exit codes:
    0  every image/video passed
    1  one or more are missing a credit
    2  the script could not run (missing content root, ...)

Usage:
    python3 docs/scripts/validate_credits.py
    python3 docs/scripts/validate_credits.py --root /path/to/docs/src/content
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable

# notes/ pages are never edited after publication (see docs/AGENTS.md,
# "Engineering notes"), so they are exempt rather than perpetually failing.
EXCLUDED_DIRS = {"notes"}
EXCLUDED_FILES = {"README.md", "AGENTS.md"}

IMG_TAG = re.compile(r"<img\b[^>]*>")
VIDEO_EMBED = re.compile(r'<div class="video-embed[^"]*">')
FIGURE_CLOSE = re.compile(r"</figure>")

CREDIT_MARKERS = re.compile(
    r"Photo:|Photo courtesy|Photos by|courtesy of|Reference photo|Render:|"
    r"Rendered from|Drawn from|Manufacturer|recorded|WireViz-generated|Video:",
    re.IGNORECASE,
)

# How far past the tag to look for a credit phrase before giving up. A
# figcaption is short, so this only needs to reach the end of one.
WINDOW = 500


def iter_markdown_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.md")):
        if any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.name in EXCLUDED_FILES:
            continue
        yield path


def check_page(path: Path, root: Path) -> list[str]:
    text = path.read_text()
    relative_path = str(path.relative_to(root))
    errors: list[str] = []

    for match in IMG_TAG.finditer(text):
        end = match.end()
        figure_end = FIGURE_CLOSE.search(text, end)
        window_end = min(end + WINDOW, figure_end.end() if figure_end else len(text))
        window = text[end:window_end]
        if not CREDIT_MARKERS.search(window):
            snippet = match.group(0)[:80]
            errors.append(f"{relative_path}: image with no credit nearby: {snippet}")

    for match in VIDEO_EMBED.finditer(text):
        window = text[match.end():match.end() + WINDOW]
        if not CREDIT_MARKERS.search(window):
            errors.append(f"{relative_path}: video embed with no credit line after it")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "src" / "content",
        help="Path to the content root (default: docs/src/content)",
    )
    args = parser.parse_args(argv)

    root: Path = args.root
    if not root.exists():
        print(f"content root not found: {root}", file=sys.stderr)
        return 2

    errors: list[str] = []
    page_count = 0
    for path in iter_markdown_files(root):
        page_count += 1
        errors.extend(check_page(path, root))

    if errors:
        print(f"Checked {page_count} pages — {len(errors)} uncredited image/video(s):", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    print(f"Checked {page_count} pages — every photo and video is credited.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
