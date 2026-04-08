#!/usr/bin/env python3
"""Validate front matter on every documentation page under docs/.

Walks docs/ and verifies that each .md file has the required front matter
fields, that `type` is one of the allowed Diátaxis-based values, and that
`last_verified` is a valid ISO date. Honors per-section defaults declared in
docs/_config.yml so authors only need to set page-specific overrides.

Exit codes:
    0  every page passed
    1  one or more pages failed validation
    2  the script could not run (missing docs/, malformed _config.yml, ...)

Usage:
    python3 docs/scripts/validate_frontmatter.py
    python3 docs/scripts/validate_frontmatter.py --root /path/to/docs
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

EXCLUDED_DIRS = {"_site", "vendor", ".bundle", "scripts", "_includes", "_layouts", "_data", "assets"}
EXCLUDED_FILES = {"README.md", "ux-concept-sorting-profiles.md"}

FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_front_matter(text: str) -> dict[str, str] | None:
    """Extract a flat key/value mapping from a Jekyll front matter block.

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


def parse_config_defaults(config_path: Path) -> list[tuple[str, dict[str, str]]]:
    """Parse the per-section defaults block out of _config.yml.

    Returns a list of (path_prefix, values_dict). Order matches _config.yml.
    Pure-stdlib parser — does not depend on PyYAML so the validator can run
    in any environment without extra installs.
    """
    if not config_path.exists():
        return []

    text = config_path.read_text()
    defaults: list[tuple[str, dict[str, str]]] = []

    in_defaults = False
    current_path: str | None = None
    in_values = False
    current_values: dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line == "defaults:":
            in_defaults = True
            continue
        if not in_defaults:
            continue
        if not line.startswith(" "):
            # Left the defaults block.
            if current_path is not None:
                defaults.append((current_path, current_values))
                current_path = None
                current_values = {}
            in_defaults = False
            continue
        stripped = line.strip()
        if stripped.startswith("- scope:"):
            if current_path is not None:
                defaults.append((current_path, current_values))
            current_path = ""
            current_values = {}
            in_values = False
            continue
        if stripped.startswith("path:"):
            value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            current_path = value
            continue
        if stripped == "values:":
            in_values = True
            continue
        if in_values and ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            current_values[key] = value

    if current_path is not None:
        defaults.append((current_path, current_values))

    return defaults


def effective_field(
    field: str,
    page_meta: dict[str, str],
    relative_path: str,
    defaults: list[tuple[str, dict[str, str]]],
) -> str | None:
    """Return the effective value of a field, applying _config.yml defaults.

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
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Path to the docs/ root (default: parent of this script)",
    )
    args = parser.parse_args(argv)

    root: Path = args.root
    if not root.exists():
        print(f"docs root not found: {root}", file=sys.stderr)
        return 2

    config_path = root / "_config.yml"
    defaults = parse_config_defaults(config_path)

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
