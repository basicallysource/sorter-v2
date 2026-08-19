#!/usr/bin/env python3
"""Validate front matter on every documentation page under docs/src/content/.

Walks the content tree and verifies that each .md file has the required front
matter fields, that `type` is one of the allowed Diátaxis-based values, and
that `last_verified` is a valid ISO date. Honors the per-section defaults so
authors only need to set page-specific overrides; the defaults here must stay
in sync with FM_DEFAULTS in docs/src/lib/server/content.ts (the renderer's
copy is the one the site actually uses).

Exit codes:
    0  every page passed
    1  one or more pages failed validation
    2  the script could not run (missing content root, ...)

Usage:
    python3 docs/scripts/validate_frontmatter.py
    python3 docs/scripts/validate_frontmatter.py --root /path/to/docs/src/content
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Iterable

REQUIRED_FIELDS = ("title", "type", "audience", "applies_to", "owner", "last_verified")
ALLOWED_TYPES = (
    "tutorial",
    "how-to",
    "reference",
    "explanation",
    "installation",
    "troubleshooting",
    "architecture",
    "landing",
)

EXCLUDED_DIRS: set[str] = set()
EXCLUDED_FILES = {"README.md", "AGENTS.md"}
CREDIT_REQUIRED_PREFIXES = ("hardware/",)

# Per-section frontmatter defaults, matched by path prefix (later, more
# specific matches win). Mirrors FM_DEFAULTS in docs/src/lib/server/content.ts.
SECTION_DEFAULTS: list[tuple[str, dict[str, str]]] = [
    ("", {"owner": "docs", "audience": "all readers", "applies_to": "site", "last_verified": "2026-04-08"}),
    ("hardware", {"section": "hardware", "owner": "hardware", "audience": "self-builder", "applies_to": "hardware-v2"}),
    ("installation", {"section": "installation", "owner": "docs", "audience": "self-hosting operator", "applies_to": "sorter 2.x"}),
    ("sorter", {"section": "sorter", "owner": "sorter", "audience": "self-hosting operator", "applies_to": "sorter 2.x"}),
    ("hive", {"section": "hive", "owner": "hive", "audience": "operator linking a Sorter to Hive", "applies_to": "hive 0.x"}),
    ("lab", {"section": "lab", "owner": "lab", "audience": "contributor", "applies_to": "2026-04-06 measurement set"}),
]

FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_front_matter(text: str) -> dict[str, str] | None:
    """Extract a flat key/value mapping from a front matter block.

    Only top-level scalar keys are returned. Nested structures are ignored
    intentionally — every required field is a scalar string.
    """
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return None
    block = match.group(1)
    out: dict[str, str] = {}
    for line in block.splitlines():
        if not line or line.startswith("#"):
            continue
        if line.startswith(" ") or line.startswith("\t"):
            # nested structure (e.g. defaults: lists). Skip.
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        out[key] = value
    return out


def effective_field(
    field: str,
    page_meta: dict[str, str],
    relative_path: str,
    defaults: list[tuple[str, dict[str, str]]],
) -> str | None:
    """Return the effective value of a field, applying SECTION_DEFAULTS.

    Defaults are matched by prefix; later (more specific) matches win.
    """
    if field in page_meta:
        return page_meta[field]
    value: str | None = None
    for prefix, values in defaults:
        if prefix == "" or relative_path.startswith(prefix):
            if field in values:
                value = values[field]
    return value


def iter_markdown_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.md")):
        if any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.name in EXCLUDED_FILES:
            continue
        yield path


def validate_page(
    path: Path,
    root: Path,
    defaults: list[tuple[str, dict[str, str]]],
) -> list[str]:
    """Return a list of human-readable validation errors for a single page."""
    errors: list[str] = []
    text = path.read_text()
    page_meta = parse_front_matter(text)
    if page_meta is None:
        return [f"{path}: missing front matter block"]

    relative_path = str(path.relative_to(root))

    for field in REQUIRED_FIELDS:
        value = effective_field(field, page_meta, relative_path, defaults)
        if not value:
            errors.append(f"{relative_path}: missing required field '{field}'")
            continue
        if field == "type" and value not in ALLOWED_TYPES:
            errors.append(
                f"{relative_path}: type '{value}' is not one of {', '.join(ALLOWED_TYPES)}"
            )
        if field == "last_verified":
            try:
                dt.date.fromisoformat(value)
            except ValueError:
                errors.append(
                    f"{relative_path}: last_verified '{value}' is not a valid YYYY-MM-DD date"
                )

    if relative_path.startswith(CREDIT_REQUIRED_PREFIXES):
        author = page_meta.get("author")
        authors = page_meta.get("authors")
        if not author and not authors:
            errors.append(
                f"{relative_path}: hardware page must list 'author' or 'authors'"
            )
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

    defaults = SECTION_DEFAULTS

    errors: list[str] = []
    page_count = 0
    for path in iter_markdown_files(root):
        page_count += 1
        errors.extend(validate_page(path, root, defaults))

    if errors:
        print(f"Validated {page_count} pages — {len(errors)} error(s):", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    print(f"Validated {page_count} pages — all passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
