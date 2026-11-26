"""What a bin is named by: the category, the part, the color, or a mix.

A bin holds a "key" in its `category_ids`. With the default (category only) the
key is the profile's category id, as it always was. With the part, the color or
a mix of them the key lists what it is made of, in a fixed order, so one run can
sort by category and color together, or by part and color:

    category only      -> "bricks"
    part only          -> "part:3001"
    color only         -> "color:5"
    category + color   -> "category:bricks|color:5"
    part + color       -> "part:3001|color:5"

Three runs in a row (category, then part, then color) need no extra code: change
the key between the runs, reset the bins' assignments and put the contents of
each bin back in.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

MISC_CATEGORY = "misc"

CATEGORY = "category"
PART = "part"
COLOR = "color"

# The order the pieces of a key are written in, whatever order they were asked for.
COMPONENTS: tuple[str, ...] = (CATEGORY, PART, COLOR)
DEFAULT_COMPONENTS: tuple[str, ...] = (CATEGORY,)

SEPARATOR = "|"
ANY_COLOR = "any_color"


def parseComponents(raw: Any) -> Optional[tuple[str, ...]]:
    """The components named by `raw` (a list or a comma separated string), in
    key order and without repeats. None when it names an unknown component or
    none at all."""
    if isinstance(raw, str):
        raw = [item for item in raw.split(",")]
    if not isinstance(raw, (list, tuple, set)):
        return None
    wanted: set[str] = set()
    for item in raw:
        name = str(item).strip().lower()
        if name not in COMPONENTS:
            return None
        wanted.add(name)
    if not wanted:
        return None
    return tuple(component for component in COMPONENTS if component in wanted)


def normalizeComponents(raw: Any) -> tuple[str, ...]:
    """Like parseComponents, with the default for anything it can't read."""
    return parseComponents(raw) or DEFAULT_COMPONENTS


def binKey(
    components: Iterable[str],
    category_id: Optional[str],
    part_id: Optional[str],
    color_id: Optional[str],
) -> str:
    """The key a piece is routed by.

    Misc stays misc: the discard passthrough is not a bin to sort into. That is
    a piece the profile put in misc when the key includes the category, and a
    piece with no part when it includes the part."""
    parts = normalizeComponents(list(components))
    category = category_id or MISC_CATEGORY
    if parts == DEFAULT_COMPONENTS:
        return category
    if CATEGORY in parts and category == MISC_CATEGORY:
        return MISC_CATEGORY
    if PART in parts and not part_id:
        return MISC_CATEGORY
    color = color_id if color_id not in (None, "") else ANY_COLOR
    tokens = []
    for component in parts:
        if component == CATEGORY:
            tokens.append(f"{CATEGORY}:{category}")
        elif component == PART:
            tokens.append(f"{PART}:{part_id}")
        else:
            tokens.append(f"{COLOR}:{color}")
    return SEPARATOR.join(tokens)


def parseKey(key: str) -> dict[str, str]:
    """What a key is made of, by component. A plain category id is
    {"category": id}."""
    if not any(key.startswith(f"{component}:") for component in COMPONENTS):
        return {CATEGORY: key} if key else {}
    out: dict[str, str] = {}
    for token in key.split(SEPARATOR):
        name, _, value = token.partition(":")
        if name in COMPONENTS and value:
            out[name] = value
    return out
