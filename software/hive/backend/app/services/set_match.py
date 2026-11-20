"""Which LEGO sets a lot's pieces could be (partly) built from.

A lot is a batch of bulk LEGO a sorter has identified piece by piece: so many
of this part in this color, in BrickLink's ids. ``match_sets`` ranks the sets
the lot plausibly holds, and returns none when nothing really matches
(agent-docs/set-match.md has the reasoning and the measurements).

**What counts as a match.** Every set shares its common bricks with thousands
of others, so the pieces a set has in common with a lot say little: a mixed
lot of a few thousand pieces covers half of a thousand small sets by accident.
What tells is a set's distinctive lines. A line (a part in a color) is weighed
by how surprising it is to find in this lot: ``ln(1 / chance)``, where the
chance is read off the lot itself, as the share of the catalog's part + colors
that as many sets contain which the lot has. That is an inverse document
frequency (the fewer sets contain a line, the more it weighs) that knows the
lot's size: in a lot of 4,000 pieces a part twenty sets contain is a find, in
one of 40,000 it is not. A line is distinctive when that chance is small, a
set's *evidence* is the surprise of its distinctive lines found, and its
*distinctive share* is that over the surprise of all its distinctive lines. A
set is returned when enough of its distinctive lines are in the lot, they are
most of what is distinctive about it, and a fair share of its pieces is there
too. Common bricks carry no evidence, so they never make a match alone.

**One set per piece.** Sets of one theme and year share their unusual parts,
so a set in a lot brings its siblings along. The sets that pass are taken
likeliest first, each one's pieces out of the lot before the next is matched
again; a set that no longer passes is dropped.

**What a set needs.** The lines of its first inventory version, spares left
out. Stickers, printed parts and minifigure body parts are not required (a
sorter rarely sees one as its own part) and are counted apart. A part stands
for its mold variants where the catalog can tell (parts that share a BrickLink
number, and parts numbered the same but for a closing letter), since they look
alike to a camera. A line is covered only by its part in its own color; the
same part in another color is reported apart, never counted.

**The index.** Built once from parts.db and kept in this process as numpy
arrays (about 30 MB): every set's lines, and for every part + color the sets
that need it (an inverted index). A lot's lines each pull one slice of that
index, so a lot of thousands of lines is scored against every set in a few
array passes. ``SetMatchService`` builds it on a thread the first time it is
asked and again after a catalog sync changes parts.db.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import logging
import os
import re
import sqlite3
import threading
import time
from array import array
from contextlib import closing
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from app.services.profile_engine.db import VARIANT_NAME_RE, VARIANT_PART_NUM_RE

logger = logging.getLogger(__name__)

# The defaults of a request. Why these, and what they were measured on, is in
# agent-docs/set-match.md.

# A set smaller than this (in required pieces) is too small to tell from
# chance.
DEFAULT_MIN_SET_PIECES = 20
# A line is distinctive when the lot had at most this chance of holding it.
DEFAULT_DISTINCTIVE_CHANCE = 0.1
# This many of the set's distinctive lines are in the lot...
DEFAULT_MIN_DISTINCTIVE_LINES = 3
# ...carrying this much surprise between them, in nats (three lines the lot
# had one chance in thirty of holding each)...
DEFAULT_MIN_EVIDENCE = 10.0
# ...which is this share of the surprise of all its distinctive lines.
DEFAULT_MIN_DISTINCTIVE_SHARE = 0.6
# And this share of the set's required pieces is in the lot.
DEFAULT_MIN_SHARE = 0.4

DEFAULT_LIMIT = 20
DEFAULT_MISSING_LIMIT = 30

# A part + color as one number: the part's id above the color's bits.
# Rebrickable's color ids run from -1 ([Unknown]) to 9999 ([No Color]).
_COLOR_BITS = 14
_COLOR_SPAN = 1 << _COLOR_BITS

# A mold variant by its number: the same digits with a closing letter (3062a
# and 3062b, 4085a to 4085d). Families of more letters than this are sizes of
# a thing (a string or a hose by length), not variants of one mold.
_MOLD_LETTER_RE = re.compile(r"^(\d+)[a-z]$")
_MOLD_FAMILY_MAX = 4

# What a set does not require, by Rebrickable's category names. Minifigure
# accessories and tools (cups, taps, wrenches) are often part of the build and
# stay required.
_STICKER_CATEGORY = "Stickers"
_FIGURE_PREFIXES = ("Minifig", "Minidoll")
_REQUIRED_FIGURE_CATEGORIES = frozenset({"Minifig Accessories", "Minifig Shields, Weapons, & Tools"})

_SYNC_META_KEYS = (
    "profile_catalog.last_sync.sets",
    "profile_catalog.last_sync.parts",
    "profile_catalog.last_sync.colors",
)


def _required(part_num: str, name: str, category: str | None) -> bool:
    """Whether a set needs this part to count as built."""
    if category == _STICKER_CATEGORY:
        return False
    if category and category.startswith(_FIGURE_PREFIXES) and category not in _REQUIRED_FIGURE_CATEGORIES:
        return False
    return not (VARIANT_PART_NUM_RE.search(part_num.lower()) or VARIANT_NAME_RE.search(name.lower()))


@dataclass
class SetMatchIndex:
    # Sets, by index, in set number order.
    set_nums: list[str]
    set_names: list[str]
    set_years: list[int | None]
    set_img_urls: list[str | None]
    set_num_parts: list[int | None]
    # Other sets with exactly a set's lines (one box sold under several
    # numbers). Only the first of them is matched.
    same_contents: dict[int, list[str]]
    # Per set: every non-spare piece, and the required ones.
    total_pieces: np.ndarray
    need: np.ndarray
    # Every set's lines, one after another: set s has line_start[s] to
    # line_start[s + 1]. A line is a key (part + color), a quantity, the
    # part as the set lists it, and whether it is required.
    line_start: np.ndarray
    line_key: np.ndarray
    line_qty: np.ndarray
    line_part: np.ndarray
    line_required: np.ndarray
    # Keys, sorted by code: how many sets contain each, and which rarity
    # band that puts it in (key_band); band_keys is how many keys some set
    # requires each band has.
    key_code: np.ndarray
    key_sets: np.ndarray
    key_band: np.ndarray
    band_keys: np.ndarray
    # The inverted index: key k's required lines are post_start[k] to
    # post_start[k + 1], each a set and the quantity it needs.
    post_start: np.ndarray
    post_set: np.ndarray
    post_need: np.ndarray
    post_key: np.ndarray
    # Parts, by id: Rebrickable's number and name, and the id of the part
    # standing for its mold variants.
    part_nums: list[str]
    part_names: list[str]
    part_canon: np.ndarray
    # A BrickLink item number or Rebrickable part number to that part's id.
    part_lookup: dict[str, int]
    # BrickLink color id to Rebrickable's and back, and names by Rebrickable id.
    color_from_bricklink: dict[int, int]
    color_to_bricklink: dict[int, int]
    color_names: dict[int, str]
    matched_sets: int
    built_in_s: float
    sync_version: tuple[tuple[str, str], ...]


def _sync_version(conn: sqlite3.Connection) -> tuple[tuple[str, str], ...]:
    placeholders = ", ".join("?" for _ in _SYNC_META_KEYS)
    return tuple(
        conn.execute(f"SELECT key, value FROM meta WHERE key IN ({placeholders}) ORDER BY key", _SYNC_META_KEYS)
    )


def _connect(db_path: str) -> sqlite3.Connection:
    if not os.path.exists(db_path):
        # Connecting would create an empty file.
        raise FileNotFoundError(f"no parts catalog at {db_path}")
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA query_only = ON")
    return conn


def _load_colors(conn: sqlite3.Connection) -> tuple[dict[int, int], dict[int, int], dict[int, str]]:
    from_bricklink: dict[int, int] = {}
    to_bricklink: dict[int, int] = {}
    names: dict[int, str] = {}
    for color_id, name, extra in conn.execute("SELECT id, name, extra FROM colors ORDER BY id"):
        names[color_id] = name
        try:
            ext_ids = json.loads(extra or "{}").get("external_ids", {}).get("BrickLink", {}).get("ext_ids", [])
        except (ValueError, AttributeError):
            continue
        for ext_id in ext_ids if isinstance(ext_ids, list) else []:
            try:
                bricklink_id = int(ext_id)
            except (TypeError, ValueError):
                continue
            from_bricklink.setdefault(bricklink_id, color_id)
            to_bricklink.setdefault(color_id, bricklink_id)
    return from_bricklink, to_bricklink, names


def _first_inventories(conn: sqlite3.Connection, set_index: dict[str, int]) -> dict[int, int]:
    """Inventory id to set index, for each set's first inventory version (the
    set as released: later versions are corrections and re-releases)."""
    first: dict[int, tuple[int, int]] = {}
    for inventory_id, version, set_num in conn.execute("SELECT id, version, set_num FROM rebrickable_inventories"):
        s = set_index.get(set_num)
        if s is None:
            # A minifigure's inventory ("fig-…"), or a set the list lacks.
            continue
        candidate = (version, inventory_id)
        if s not in first or candidate < first[s]:
            first[s] = candidate
    return {inventory_id: s for s, (_version, inventory_id) in first.items()}


def _mold_variants(conn: sqlite3.Connection, part_ids: dict[str, int]) -> list[int]:
    """Each part's canonical part: the one standing for the parts a camera
    cannot tell from it. Joined (union-find) are the parts that share a
    BrickLink item number, which is how the sorter names them, and the parts
    numbered the same but for a closing letter."""
    parent = list(range(len(part_ids)))

    def find(p: int) -> int:
        while parent[p] != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p

    def union(a: int, b: int) -> None:
        a, b = find(a), find(b)
        if a != b:
            parent[max(a, b)] = min(a, b)

    by_item: dict[str, int] = {}
    for part_num, item_no in conn.execute("SELECT part_num, item_no FROM part_bricklink_ids"):
        p = part_ids.get(part_num)
        if p is None:
            continue
        other = by_item.setdefault(item_no, p)
        if other != p:
            union(other, p)

    families: dict[str, list[int]] = {}
    for part_num, p in part_ids.items():
        lettered = _MOLD_LETTER_RE.match(part_num)
        if lettered:
            families.setdefault(lettered.group(1), []).append(p)
    for stem, members in families.items():
        if len(members) > _MOLD_FAMILY_MAX:
            continue
        plain = part_ids.get(stem)
        if plain is not None:
            members = [plain, *members]
        for p in members[1:]:
            union(members[0], p)

    return [find(p) for p in range(len(parent))]


def build_index(db_path: str) -> SetMatchIndex:
    """Read every set's inventory from parts.db into the arrays matching uses.
    Seconds of work, most of it reading 1.5 million inventory lines."""
    started = time.monotonic()
    with closing(_connect(db_path)) as conn:
        version = _sync_version(conn)

        set_nums: list[str] = []
        set_names: list[str] = []
        set_years: list[int | None] = []
        set_img_urls: list[str | None] = []
        set_num_parts: list[int | None] = []
        for set_num, name, year, num_parts, img_url in conn.execute(
            "SELECT set_num, name, year, num_parts, img_url FROM rebrickable_sets ORDER BY set_num"
        ):
            set_nums.append(set_num)
            set_names.append(name)
            set_years.append(year)
            set_num_parts.append(num_parts)
            set_img_urls.append(img_url or None)
        set_count = len(set_nums)
        inventory_set = _first_inventories(conn, {set_num: s for s, set_num in enumerate(set_nums)})

        # Every non-spare line of those inventories, as it comes: the arrays
        # below sort and add them up, so nothing here needs an order.
        part_ids: dict[str, int] = {}
        raw_set = array("i")
        raw_part = array("i")
        raw_color = array("i")
        raw_qty = array("i")
        cursor = conn.execute(
            "SELECT inventory_id, part_num, color_id, quantity FROM rebrickable_inventory_parts WHERE is_spare = 0"
        )
        while True:
            batch = cursor.fetchmany(20000)
            if not batch:
                break
            for inventory_id, part_num, color_id, quantity in batch:
                s = inventory_set.get(inventory_id)
                if s is None or not isinstance(quantity, int) or quantity <= 0:
                    continue
                if not isinstance(color_id, int) or not -1 <= color_id < _COLOR_SPAN - 1:
                    continue
                p = part_ids.get(part_num)
                if p is None:
                    p = part_ids[part_num] = len(part_ids)
                raw_set.append(s)
                raw_part.append(p)
                raw_color.append(color_id)
                raw_qty.append(quantity)

        part_nums = list(part_ids)
        part_names = [""] * len(part_nums)
        part_required = np.ones(len(part_nums), dtype=bool)
        for part_num, name, category in conn.execute(
            "SELECT p.part_num, p.name, c.name FROM parts p LEFT JOIN categories c ON c.id = p.part_cat_id"
        ):
            p = part_ids.get(part_num)
            if p is not None:
                part_names[p] = name or ""
                part_required[p] = _required(part_num, name or "", category)

        part_canon = np.array(_mold_variants(conn, part_ids), dtype=np.int64)

        # What a lot calls a part: a BrickLink item number first (the sorter
        # speaks BrickLink), else Rebrickable's own number.
        part_lookup: dict[str, int] = {}
        for part_num, item_no in conn.execute(
            "SELECT part_num, item_no FROM part_bricklink_ids ORDER BY (part_num = item_no) DESC, is_primary DESC"
        ):
            p = part_ids.get(part_num)
            if p is not None:
                part_lookup.setdefault(item_no, int(part_canon[p]))
        for part_num, p in part_ids.items():
            part_lookup.setdefault(part_num, int(part_canon[p]))

        color_from_bricklink, color_to_bricklink, color_names = _load_colors(conn)

    line_set = np.frombuffer(raw_set, dtype=np.int32).astype(np.int64)
    line_part = np.frombuffer(raw_part, dtype=np.int32).astype(np.int64)
    line_color = np.frombuffer(raw_color, dtype=np.int32).astype(np.int64)
    line_qty = np.frombuffer(raw_qty, dtype=np.int32).astype(np.int64)
    del raw_set, raw_part, raw_color, raw_qty

    # One line per set, part (its mold variants as one) and color: sorted by
    # set, then by code, quantities added up.
    code = (part_canon[line_part] << _COLOR_BITS) | (line_color + 1)
    combined = (line_set << 40) | code
    _unique, first, inverse = np.unique(combined, return_index=True, return_inverse=True)
    line_qty = np.bincount(inverse, weights=line_qty, minlength=len(first)).astype(np.int32)
    line_set = line_set[first]
    line_part = line_part[first].astype(np.int32)
    code = code[first]
    line_required = part_required[line_part]
    del combined, inverse, first, line_color

    line_start = np.zeros(set_count + 1, dtype=np.int64)
    np.cumsum(np.bincount(line_set, minlength=set_count), out=line_start[1:])
    key_code, line_key = np.unique(code, return_inverse=True)
    line_key = line_key.astype(np.int32)

    # One box sold under several numbers is matched once, as the first number.
    hidden = np.zeros(set_count, dtype=bool)
    same_contents: dict[int, list[str]] = {}
    seen: dict[bytes, int] = {}
    for s in range(set_count):
        a, b = int(line_start[s]), int(line_start[s + 1])
        if a == b:
            hidden[s] = True
            continue
        digest = hashlib.blake2b(line_key[a:b].tobytes() + line_qty[a:b].tobytes(), digest_size=16).digest()
        twin = seen.setdefault(digest, s)
        if twin != s:
            hidden[s] = True
            same_contents.setdefault(twin, []).append(set_nums[s])

    # How many sets contain each part + color, across the sets as sold (each
    # distinct contents once, every line of them), and its rarity band: a
    # quarter of a doubling of that count each.
    shown_line = ~hidden[line_set]
    matched_sets = int((~hidden).sum())
    key_sets = np.bincount(line_key[shown_line], minlength=len(key_code)).astype(np.int32)
    key_band = np.floor(4 * np.log2(np.maximum(key_sets, 1))).astype(np.int32)

    total_pieces = np.bincount(line_set, weights=line_qty, minlength=set_count).astype(np.int32)
    need = np.bincount(line_set, weights=line_qty * line_required, minlength=set_count).astype(np.int32)
    need[hidden] = 0

    posted = np.flatnonzero(shown_line & line_required)
    posted = posted[np.argsort(line_key[posted], kind="stable")]
    post_key = line_key[posted]
    post_start = np.zeros(len(key_code) + 1, dtype=np.int64)
    np.cumsum(np.bincount(post_key, minlength=len(key_code)), out=post_start[1:])
    # The bands count the part + colors some set requires: the ones a lot can
    # be matched on (a sorter does not name the printed ones).
    band_keys = np.bincount(key_band[np.unique(post_key)], minlength=int(key_band.max(initial=0)) + 1)

    return SetMatchIndex(
        set_nums=set_nums,
        set_names=set_names,
        set_years=set_years,
        set_img_urls=set_img_urls,
        set_num_parts=set_num_parts,
        same_contents=same_contents,
        total_pieces=total_pieces,
        need=need,
        line_start=line_start,
        line_key=line_key,
        line_qty=line_qty,
        line_part=line_part,
        line_required=line_required,
        key_code=key_code,
        key_sets=key_sets,
        key_band=key_band,
        band_keys=band_keys,
        post_start=post_start,
        post_set=line_set[posted].astype(np.int32),
        post_need=line_qty[posted],
        post_key=post_key,
        part_nums=part_nums,
        part_names=part_names,
        part_canon=part_canon.astype(np.int32),
        part_lookup=part_lookup,
        color_from_bricklink=color_from_bricklink,
        color_to_bricklink=color_to_bricklink,
        color_names=color_names,
        matched_sets=matched_sets,
        built_in_s=round(time.monotonic() - started, 2),
        sync_version=version,
    )


# ---------------------------------------------------------------------------
# A lot


@dataclass
class Lot:
    """A lot's pieces as the index names them."""

    # Pieces by part + color code, sorted by code.
    codes: np.ndarray
    quantities: np.ndarray
    # Pieces of each part (its mold variants as one) in every color, and in
    # each color (Rebrickable's id, None when the lot does not say).
    part_pieces: dict[int, int]
    part_colors: dict[int, dict[int | None, int]]
    lines: int
    pieces: int
    # Pieces whose part no set has (or the catalog cannot place), and pieces
    # of a known part whose color it cannot place.
    unknown_part_pieces: int
    unknown_color_pieces: int


def _color_id(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def read_lot(index: SetMatchIndex, inventory: list[dict[str, Any]]) -> Lot:
    """A lot from ``{part_id, color_id, quantity}`` lines in BrickLink's ids."""
    exact: dict[int, int] = {}
    part_pieces: dict[int, int] = {}
    part_colors: dict[int, dict[int | None, int]] = {}
    pieces = unknown_part = unknown_color = 0
    for line in inventory:
        quantity = int(line.get("quantity") or 0)
        if quantity <= 0:
            continue
        pieces += quantity
        part = index.part_lookup.get(str(line.get("part_id") or "").strip())
        if part is None:
            unknown_part += quantity
            continue
        bricklink_color = _color_id(line.get("color_id"))
        color = index.color_from_bricklink.get(bricklink_color) if bricklink_color is not None else None
        part_pieces[part] = part_pieces.get(part, 0) + quantity
        colors = part_colors.setdefault(part, {})
        colors[color] = colors.get(color, 0) + quantity
        if color is None:
            unknown_color += quantity
            continue
        code = (part << _COLOR_BITS) | (color + 1)
        exact[code] = exact.get(code, 0) + quantity
    codes = np.fromiter(exact.keys(), dtype=np.int64, count=len(exact))
    quantities = np.fromiter(exact.values(), dtype=np.int64, count=len(exact))
    order = np.argsort(codes)
    return Lot(
        codes=codes[order],
        quantities=quantities[order],
        part_pieces=part_pieces,
        part_colors=part_colors,
        lines=len(inventory),
        pieces=pieces,
        unknown_part_pieces=unknown_part,
        unknown_color_pieces=unknown_color,
    )


# ---------------------------------------------------------------------------
# Matching


@dataclass
class Thresholds:
    min_set_pieces: int = DEFAULT_MIN_SET_PIECES
    min_distinctive_lines: int = DEFAULT_MIN_DISTINCTIVE_LINES
    min_evidence: float = DEFAULT_MIN_EVIDENCE
    min_distinctive_share: float = DEFAULT_MIN_DISTINCTIVE_SHARE
    min_share: float = DEFAULT_MIN_SHARE
    distinctive_chance: float = DEFAULT_DISTINCTIVE_CHANCE


@dataclass
class Scores:
    """Every set against a lot, by set index; ``surprise`` and
    ``is_distinctive`` by key."""

    surprise: np.ndarray
    is_distinctive: np.ndarray
    covered: np.ndarray
    share: np.ndarray
    evidence: np.ndarray
    distinctive_share: np.ndarray
    distinctive_lines: np.ndarray
    distinctive_pieces: np.ndarray
    distinctive_lines_present: np.ndarray
    distinctive_pieces_present: np.ndarray
    passes: np.ndarray
    score: np.ndarray


def _surprise(index: SetMatchIndex, lot_keys: np.ndarray) -> np.ndarray:
    """How surprising each part + color is to find in this lot: ``ln(1 /
    chance)``. The chance is measured on the lot: of the catalog's part +
    colors in the same rarity band (contained by about as many sets), the
    share the lot has, never less for a commoner band than for a rarer one."""
    required = index.post_start[lot_keys + 1] > index.post_start[lot_keys]
    held = np.bincount(index.key_band[lot_keys[required]], minlength=len(index.band_keys))
    # A band with no keys has no chance of its own and takes the one below.
    chance = np.where(index.band_keys > 0, (held + 1.0) / (index.band_keys + 2.0), 0.0)
    chance = np.clip(np.maximum.accumulate(chance), 1e-9, 1.0)
    return -np.log(chance)[index.key_band]


def score_sets(index: SetMatchIndex, lot: Lot, thresholds: Thresholds) -> Scores:
    """Score every set against the lot through the inverted index: each of
    the lot's part + colors gives its pieces to every set that needs it,
    capped at what the set needs."""
    sets = len(index.set_nums)

    at = np.searchsorted(index.key_code, lot.codes)
    at[at == len(index.key_code)] = 0
    known = index.key_code[at] == lot.codes if len(index.key_code) else np.zeros(len(at), dtype=bool)
    keys = at[known]
    quantities = lot.quantities[known]

    surprise = _surprise(index, keys)
    is_distinctive = surprise >= -np.log(thresholds.distinctive_chance)
    # Only a distinctive line is evidence. The small surprises of commoner
    # lines are not added up: a lot of plain bricks holds hundreds of them at
    # once, for every set of plain bricks.
    weight = surprise * is_distinctive

    # Every posting of every key the lot has, as one run of positions.
    starts = index.post_start[keys]
    lengths = index.post_start[keys + 1] - starts
    total = int(lengths.sum())
    offsets = np.cumsum(lengths) - lengths
    positions = np.repeat(starts - offsets, lengths) + np.arange(total, dtype=np.int64)
    post_set = index.post_set[positions]
    post_need = index.post_need[positions]
    have = np.minimum(np.repeat(quantities, lengths), post_need)
    found_distinctive = np.repeat(is_distinctive[keys], lengths)

    covered = np.bincount(post_set, weights=have, minlength=sets)
    # A line found in part counts in part: 1 of the 4 a set needs is a
    # quarter of that line's surprise.
    evidence = np.bincount(post_set, weights=np.repeat(weight[keys], lengths) * have / post_need, minlength=sets)
    distinctive_lines_present = np.bincount(post_set, weights=found_distinctive, minlength=sets)
    distinctive_pieces_present = np.bincount(post_set, weights=have * found_distinctive, minlength=sets)

    # What each set has in all, found or not.
    post_distinctive = is_distinctive[index.post_key]
    possible = np.bincount(index.post_set, weights=weight[index.post_key], minlength=sets)
    distinctive_lines = np.bincount(index.post_set, weights=post_distinctive, minlength=sets)
    distinctive_pieces = np.bincount(index.post_set, weights=post_distinctive * index.post_need, minlength=sets)

    share = covered / np.maximum(index.need, 1)
    distinctive_share = evidence / np.maximum(possible, 1e-9)
    t = thresholds
    passes = (
        (index.need >= t.min_set_pieces)
        & (distinctive_lines_present >= t.min_distinctive_lines)
        & (evidence >= t.min_evidence)
        & (distinctive_share >= t.min_distinctive_share)
        & (share >= t.min_share)
    )
    return Scores(
        surprise=surprise,
        is_distinctive=is_distinctive,
        covered=covered,
        share=share,
        evidence=evidence,
        distinctive_share=distinctive_share,
        distinctive_lines=distinctive_lines,
        distinctive_pieces=distinctive_pieces,
        distinctive_lines_present=distinctive_lines_present,
        distinctive_pieces_present=distinctive_pieces_present,
        passes=passes,
        # The evidence a set is in the lot, times how much of what is unusual
        # about it is there: what orders the answer.
        score=evidence * distinctive_share,
    )


@dataclass
class SetMatch:
    """One set against the pieces a lot has left, line by line."""

    s: int
    # The pieces each of the set's lines finds, and where in the lot.
    have: np.ndarray
    at: np.ndarray
    covered: int
    share: float
    evidence: float
    distinctive_share: float
    distinctive_lines: int
    distinctive_lines_present: int
    distinctive_pieces: int
    distinctive_pieces_present: int
    passes: bool

    @property
    def score(self) -> float:
        return self.evidence * self.distinctive_share


def _match_set(index: SetMatchIndex, lot: Lot, scores: Scores, s: int, thresholds: Thresholds) -> SetMatch:
    """What ``score_sets`` works out for every set at once, for one set
    against the lot as it is now: after sets before it took their pieces,
    the lot has less."""
    a, b = int(index.line_start[s]), int(index.line_start[s + 1])
    keys = index.line_key[a:b]
    codes = index.key_code[keys]
    need = index.line_qty[a:b]
    required = index.line_required[a:b]

    if len(lot.codes):
        at = np.searchsorted(lot.codes, codes)
        at[at == len(lot.codes)] = 0
        have = np.where(lot.codes[at] == codes, np.minimum(lot.quantities[at], need), 0)
    else:
        at = np.zeros(len(codes), dtype=np.int64)
        have = np.zeros(len(codes), dtype=np.int64)

    distinctive = scores.is_distinctive[keys] & required
    weight = scores.surprise[keys] * distinctive
    covered = int((have * required).sum())
    share = covered / max(int(index.need[s]), 1)
    evidence = float((weight * have / need).sum())
    distinctive_share = evidence / max(float(weight.sum()), 1e-9)
    distinctive_lines_present = int((distinctive & (have > 0)).sum())
    t = thresholds
    return SetMatch(
        s=s,
        have=have,
        at=at,
        covered=covered,
        share=share,
        evidence=evidence,
        distinctive_share=distinctive_share,
        distinctive_lines=int(distinctive.sum()),
        distinctive_lines_present=distinctive_lines_present,
        distinctive_pieces=int((need * distinctive).sum()),
        distinctive_pieces_present=int((have * distinctive).sum()),
        passes=bool(
            index.need[s] >= t.min_set_pieces
            and distinctive_lines_present >= t.min_distinctive_lines
            and evidence >= t.min_evidence
            and distinctive_share >= t.min_distinctive_share
            and share >= t.min_share
        ),
    )


def _take(index: SetMatchIndex, lot: Lot, match: SetMatch) -> None:
    """Take a set's pieces out of the lot."""
    a = int(index.line_start[match.s])
    found = np.flatnonzero(match.have)
    lot.quantities[match.at[found]] -= match.have[found]
    codes = index.key_code[index.line_key[a + found]]
    for code, n in zip(codes.tolist(), match.have[found].tolist()):
        part, color = code >> _COLOR_BITS, (code & (_COLOR_SPAN - 1)) - 1
        lot.part_pieces[part] -= n
        lot.part_colors[part][color] -= n


def _bricklink_color(index: SetMatchIndex, color: int | None) -> int | None:
    return index.color_to_bricklink.get(color) if color is not None else None


def _set_detail(index: SetMatchIndex, lot: Lot, scores: Scores, match: SetMatch, missing_limit: int) -> dict[str, Any]:
    s = match.s
    a, b = int(index.line_start[s]), int(index.line_start[s + 1])
    keys = index.line_key[a:b]
    codes = index.key_code[keys]
    quantities = index.line_qty[a:b]
    have = match.have
    short = np.where(index.line_required[a:b], quantities - have, 0)

    # A part's pieces in the lot that this set's own lines did not take are
    # what its short lines could use in another color.
    parts = (codes >> _COLOR_BITS).tolist()
    colors = ((codes & (_COLOR_SPAN - 1)) - 1).tolist()
    taken: dict[int, int] = {}
    short_by_part: dict[int, int] = {}
    for part, n, missing in zip(parts, have.tolist(), short.tolist()):
        if n:
            taken[part] = taken.get(part, 0) + n
        if missing:
            short_by_part[part] = short_by_part.get(part, 0) + missing
    spare_by_part = {part: max(lot.part_pieces.get(part, 0) - taken.get(part, 0), 0) for part in short_by_part}
    wrong_color = sum(min(short_by_part[part], spare) for part, spare in spare_by_part.items())

    missing_at = np.flatnonzero(short > 0)
    # The most unusual missing lines first: they are the hard ones to find.
    missing_at = missing_at[np.argsort(-scores.surprise[keys[missing_at]], kind="stable")]
    missing = []
    for i in missing_at[:missing_limit].tolist():
        part, color = parts[i], colors[i]
        p = int(index.line_part[a + i])
        spare = spare_by_part.get(part, 0)
        other_colors = [
            {
                "color_id": _bricklink_color(index, other),
                "color_name": index.color_names.get(other) if other is not None else None,
                "quantity": n,
            }
            for other, n in sorted(lot.part_colors.get(part, {}).items(), key=lambda item: -item[1])
            if other != color and n > 0
        ]
        missing.append(
            {
                "part_num": index.part_nums[p],
                "part_name": index.part_names[p],
                "color_id": _bricklink_color(index, color),
                "color_name": index.color_names.get(color),
                "needed": int(quantities[i]),
                "have": int(have[i]),
                "missing": int(short[i]),
                "in_other_colors": min(int(short[i]), spare),
                "other_colors": other_colors[:3] if spare else [],
                "sets_with_it": int(index.key_sets[keys[i]]),
                "distinctive": bool(scores.is_distinctive[keys[i]]),
            }
        )

    return {
        "set_num": index.set_nums[s],
        "name": index.set_names[s],
        "year": index.set_years[s],
        "image_url": index.set_img_urls[s],
        "num_parts": index.set_num_parts[s],
        "total_pieces": int(index.total_pieces[s]),
        "required_pieces": int(index.need[s]),
        "covered_pieces": match.covered,
        "share": round(match.share, 4),
        "distinctive_lines": match.distinctive_lines,
        "distinctive_lines_present": match.distinctive_lines_present,
        "distinctive_pieces": match.distinctive_pieces,
        "distinctive_pieces_present": match.distinctive_pieces_present,
        "distinctive_share": round(match.distinctive_share, 4),
        "evidence": round(match.evidence, 2),
        "wrong_color_pieces": int(wrong_color),
        "not_required_pieces": int(index.total_pieces[s] - index.need[s]),
        "score": round(match.score, 2),
        "same_contents": index.same_contents.get(s, []),
        "missing_lines": int(len(missing_at)),
        "missing": missing,
    }


def match_lot(
    index: SetMatchIndex, lot: Lot, thresholds: Thresholds, *, exclusive: bool, limit: int, missing_limit: int
) -> tuple[list[dict[str, Any]], int]:
    """The sets that pass, likeliest first (``limit`` of them in full), and
    how many passed. With ``exclusive`` it takes pieces out of ``lot``."""
    scores = score_sets(index, lot, thresholds)
    passing = np.flatnonzero(scores.passes)
    ranked = passing[np.argsort(-scores.score[passing], kind="stable")].tolist()
    if not exclusive:
        return [
            _set_detail(index, lot, scores, _match_set(index, lot, scores, s, thresholds), missing_limit)
            for s in ranked[:limit]
        ], len(ranked)

    # Taking pieces out only lowers a set's score, so its last score bounds
    # its next: the sets wait in a heap by their last score, and only the one
    # on top is matched again.
    sets: list[dict[str, Any]] = []
    matched = 0
    waiting = [(-float(scores.score[s]), order, s) for order, s in enumerate(ranked)]
    heapq.heapify(waiting)
    while waiting:
        _bound, order, s = heapq.heappop(waiting)
        match = _match_set(index, lot, scores, s, thresholds)
        if not match.passes:
            continue
        if waiting and match.score < -waiting[0][0]:
            heapq.heappush(waiting, (-match.score, order, s))
            continue
        matched += 1
        if len(sets) < limit:
            sets.append(_set_detail(index, lot, scores, match, missing_limit))
        _take(index, lot, match)
    return sets, matched


def match_sets(
    index: SetMatchIndex,
    inventory: list[dict[str, Any]],
    *,
    thresholds: Thresholds | None = None,
    exclusive: bool = True,
    limit: int = DEFAULT_LIMIT,
    missing_limit: int = DEFAULT_MISSING_LIMIT,
) -> dict[str, Any]:
    """The sets a lot plausibly holds, likeliest first; none when no set
    passes the thresholds.

    ``exclusive``: each piece counts for one set. The sets that pass against
    the whole lot are taken likeliest first, each one's pieces out of the lot
    before the next is matched again, and a set that no longer passes is
    dropped. Sets of one theme and year share their unusual parts, so one of
    them in a lot would otherwise bring its siblings along. Without it, every
    set is matched against the whole lot.
    """
    started = time.monotonic()
    thresholds = thresholds or Thresholds()
    lot = read_lot(index, inventory)
    inventory_summary = {
        "lines": lot.lines,
        "pieces": lot.pieces,
        "unknown_part_pieces": lot.unknown_part_pieces,
        "unknown_color_pieces": lot.unknown_color_pieces,
    }
    sets, matched = match_lot(
        index, lot, thresholds, exclusive=exclusive, limit=limit, missing_limit=missing_limit
    )
    return {
        "sets": sets,
        "matched_sets": matched,
        "exclusive": exclusive,
        "inventory": inventory_summary,
        "thresholds": asdict(thresholds),
        "catalog": {"sets": index.matched_sets, "synced": dict(index.sync_version)},
        "took_ms": round((time.monotonic() - started) * 1000, 1),
    }


# ---------------------------------------------------------------------------
# The index, kept


class SetMatchService:
    """Keeps the index for this process: built on a thread when first asked
    for, and again when a catalog sync has changed parts.db (looked at once a
    minute). The index in use stays in use until its replacement is whole."""

    CHECK_INTERVAL_S = 60.0
    RETRY_AFTER_FAILURE_S = 30.0

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._index: SetMatchIndex | None = None
        self._building = False
        self._checked_at = 0.0
        self._not_before = 0.0

    def index(self, wait_s: float) -> SetMatchIndex | None:
        """The index, waiting up to ``wait_s`` for the first one to be built;
        None when it is not there yet."""
        self._refresh()
        if self._index is None:
            self._ready.wait(wait_s)
        return self._index

    def _refresh(self) -> None:
        now = time.monotonic()
        with self._lock:
            if self._building or now < self._not_before:
                return
            if self._index is not None:
                if now - self._checked_at < self.CHECK_INTERVAL_S:
                    return
                self._checked_at = now
                try:
                    with closing(_connect(self._db_path)) as conn:
                        if _sync_version(conn) == self._index.sync_version:
                            return
                except (OSError, sqlite3.Error):
                    logger.exception("set match: could not read the catalog's sync times")
                    return
            self._building = True
        threading.Thread(target=self._build, name="set-match-index", daemon=True).start()

    def _build(self) -> None:
        try:
            index = build_index(self._db_path)
            self._index = index
            self._checked_at = time.monotonic()
            self._ready.set()
            logger.info(
                "set match: indexed %d sets, %d lines, %d part + colors in %.1fs",
                index.matched_sets,
                len(index.line_key),
                len(index.key_code),
                index.built_in_s,
            )
        except Exception:
            self._not_before = time.monotonic() + self.RETRY_AFTER_FAILURE_S
            logger.exception("set match: building the index failed; the next request after a pause tries again")
        finally:
            with self._lock:
                self._building = False


_service: SetMatchService | None = None
_service_lock = threading.Lock()


def get_set_match_service() -> SetMatchService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                from app.config import settings

                _service = SetMatchService(os.path.expanduser(settings.SORTING_PROFILE_PARTS_DB_PATH))
    return _service
