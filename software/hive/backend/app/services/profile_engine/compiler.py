"""Compiles a sorting profile into what a sorter runs, and answers questions
about one: which parts a rule takes, where a given piece would go.

A profile document is an ordered list of rules. A rule is either a tree of
conditions over a part's catalog fields and its color, or a kit (parts in
colors, with quantities). A piece goes to the first rule that takes it.

The compiled form, the *program*, keeps that shape: an ordered list of
(parts, colors) matches, where either side may be "any". A rule that only
tests color stays one entry instead of one entry per part and color, so a
profile that took 45 MB as a flat part-color map is a few hundred KB here,
and a sorter parses it without stalling. Sorters from before the program
existed still get the flat map (`expand_legacy`), built from the program on
request, so both route every piece the same way.

Colors in conditions are Rebrickable color IDs (what the catalog lists); the
program speaks BrickLink IDs for parts and colors, because that is what a
sorter's classifier reports.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

import numpy as np

from app.services.profile_engine.fields import (
    BOOL,
    FIELDS,
    FLOAT,
    INT,
    OP_LABELS,
    STR,
    STR_LIST,
    ConditionError,
    bricklink_category_id,
    bricklink_ids,
    field_spec,
    normalize_condition,
    read_field,
)

ANY_COLOR = "any_color"
PROGRAM_FORMAT = 1
ARTIFACT_SCHEMA_VERSION = 2
# A sorter that cannot run a profile's program is not offered the profile:
# it names what it can run when it asks for its library.
FEATURE_PROGRAM = "program"
FEATURE_COLOR_FALLBACK = "color_fallback"
FEATURE_KIT_CASCADE = "kit_cascade"
SAMPLE_LIMIT = 6
KIT_ANY_COLOR_ID = -1


# --- The catalog, laid out for rules -----------------------------------------


class CatalogIndex:
    """One row per catalog part; a field's column is read on first use and kept
    for this catalog generation, so a compile evaluates each condition over
    arrays instead of walking 80,000 part records per rule."""

    def __init__(self, parts_data: Any) -> None:
        self.generation = getattr(parts_data, "generation", 0)
        self.categories: dict[int, dict] = getattr(parts_data, "categories", None) or {}
        self.bricklink_categories: dict[int, dict] = getattr(parts_data, "bricklink_categories", None) or {}
        self.colors: dict[int, dict] = getattr(parts_data, "colors", None) or {}
        self.rb_to_bl_color: dict[int, int] = getattr(parts_data, "rb_to_bl_color", None) or {}
        self._parts = getattr(parts_data, "parts", None) or {}
        self.part_nums: list[str] = list(self._parts.keys())
        self.size = len(self.part_nums)
        self.row_of: dict[str, int] = {num: row for row, num in enumerate(self.part_nums)}
        # The IDs a sorter reports a piece by: the part's BrickLink IDs, or its
        # Rebrickable number when it has none.
        self.keys: list[list[str]] = []
        self.rows_by_key: dict[str, list[int]] = {}
        self.rows_by_bricklink_id: dict[str, list[int]] = {}
        for row, num in enumerate(self.part_nums):
            ids = bricklink_ids(self._parts[num])
            for item in ids:
                self.rows_by_bricklink_id.setdefault(item, []).append(row)
            keys = ids or [num]
            self.keys.append(keys)
            for key in keys:
                self.rows_by_key.setdefault(key, []).append(row)
        self.bl_colors: dict[str, dict] = {}
        for rb_id, color in self.colors.items():
            bl_id = self.bl_color(rb_id)
            self.bl_colors.setdefault(
                bl_id,
                {
                    # id is BrickLink's (what a sorter reports); conditions take rebrickable_id.
                    "id": bl_id,
                    "bricklink_id": bl_id,
                    "rb_id": rb_id,
                    "rebrickable_id": rb_id,
                    "name": color.get("name"),
                    "rgb": color.get("rgb"),
                },
            )
        self._columns: dict[str, Any] = {}
        self._masks: OrderedDict[str, np.ndarray] = OrderedDict()
        self._lock = threading.Lock()
        self._popularity: np.ndarray | None = None
        # Which colors each part is known to come in (BrickLink's catalog), by
        # BrickLink color ID: rows per color. None until loaded; empty when the
        # catalog has none, and then color-limited bins count every part.
        self.known_color_rows: dict[str, np.ndarray] | None = None
        self._known_color_masks: dict[tuple[str, ...], np.ndarray] = {}

    def set_known_colors(self, pairs: Iterable[tuple[str, Any]]) -> None:
        rows_by_color: dict[str, list[int]] = {}
        for item_no, color in pairs:
            for row in self.rows_by_bricklink_id.get(str(item_no), ()):
                rows_by_color.setdefault(str(color), []).append(row)
        self.known_color_rows = {color: np.array(sorted(set(rows)), dtype=np.int64) for color, rows in rows_by_color.items()}

    def known_in(self, colors: list[str]) -> np.ndarray | None:
        """Parts known to come in any of these colors, or None when the
        catalog does not say which colors parts come in."""
        if not self.known_color_rows:
            return None
        key = tuple(sorted(colors))
        with self._lock:
            cached = self._known_color_masks.get(key)
        if cached is not None:
            return cached
        mask = np.zeros(self.size, dtype=bool)
        for color in colors:
            rows = self.known_color_rows.get(color)
            if rows is not None:
                mask[rows] = True
        with self._lock:
            if len(self._known_color_masks) > 256:
                self._known_color_masks.clear()
            self._known_color_masks[key] = mask
        return mask

    def part(self, row: int) -> dict:
        return self._parts[self.part_nums[row]]

    def bl_color(self, rb_color_id: int) -> str:
        return str(self.rb_to_bl_color.get(rb_color_id, rb_color_id))

    def rows_for(self, part: str) -> list[int]:
        """Rows for a part given by BrickLink ID or Rebrickable number."""
        part = str(part).strip()
        rows = self.rows_by_key.get(part)
        if rows:
            return rows
        row = self.row_of.get(part)
        return [row] if row is not None else []

    def column(self, field: str) -> Any:
        with self._lock:
            cached = self._columns.get(field)
        if cached is not None:
            return cached
        spec = FIELDS[field]
        raw = [read_field(field, self._parts[num], self.categories, self.bricklink_categories) for num in self.part_nums]
        if spec.type in (INT, FLOAT, BOOL):
            column: Any = np.array([_number_or_nan(value) for value in raw], dtype=np.float64)
        elif spec.type == STR:
            column = ["" if value is None else str(value) for value in raw]
        else:
            column = raw
        with self._lock:
            self._columns[field] = column
        return column

    def popularity(self) -> np.ndarray:
        """Pieces sold in the last six months, to put a rule's best known parts
        first when it is shown by a few examples."""
        if self._popularity is None:
            sold = np.nan_to_num(self.column("bl_price_qty"), nan=0.0)
            has_image = np.array([bool(self.part(row).get("part_img_url")) for row in range(self.size)], dtype=bool)
            self._popularity = sold + has_image * 1e9
        return self._popularity

    def part_mask(self, condition: dict[str, Any]) -> np.ndarray:
        key = json.dumps([condition["field"], condition["op"], condition["value"]], sort_keys=True, default=str)
        with self._lock:
            cached = self._masks.get(key)
            if cached is not None:
                self._masks.move_to_end(key)
                return cached
        mask = self._evaluate(condition)
        mask.setflags(write=False)
        with self._lock:
            self._masks[key] = mask
            while len(self._masks) > 1024:
                self._masks.popitem(last=False)
        return mask

    def _evaluate(self, condition: dict[str, Any]) -> np.ndarray:
        field, op, value = condition["field"], condition["op"], condition["value"]
        spec = FIELDS[field]
        negate = op in ("neq", "not_in")
        wanted = value if op in ("in", "not_in") else [value]
        if field in ("part_num", "bricklink_id") and op in ("eq", "neq", "in", "not_in"):
            index = self.row_of if field == "part_num" else None
            mask = np.zeros(self.size, dtype=bool)
            for item in wanted:
                if index is not None:
                    row = index.get(item)
                    if row is not None:
                        mask[row] = True
                else:
                    for row in self.rows_by_bricklink_id.get(item, ()):
                        mask[row] = True
            return ~mask if negate else mask
        column = self.column(field)
        if spec.type in (INT, FLOAT, BOOL):
            if op == "gte":
                with np.errstate(invalid="ignore"):
                    return column >= value
            if op == "lte":
                with np.errstate(invalid="ignore"):
                    return column <= value
            mask = np.isin(column, np.array(wanted, dtype=np.float64))
            return ~mask if negate else mask
        if spec.type == STR_LIST:
            if op == "contains":
                needle = value.lower()
                return np.fromiter((any(needle in item.lower() for item in items) for items in column), dtype=bool, count=self.size)
            if op == "regex":
                pattern = _compile_regex(value, spec.label)
                return np.fromiter((any(pattern.search(item) for item in items) for items in column), dtype=bool, count=self.size)
            wanted_set = set(wanted)
            mask = np.fromiter((any(item in wanted_set for item in items) for items in column), dtype=bool, count=self.size)
            return ~mask if negate else mask
        if op == "contains":
            needle = value.lower()
            return np.fromiter((needle in text.lower() for text in column), dtype=bool, count=self.size)
        if op == "regex":
            pattern = _compile_regex(value, spec.label)
            return np.fromiter((bool(pattern.search(text)) for text in column), dtype=bool, count=self.size)
        wanted_set = set(wanted)
        mask = np.fromiter((text in wanted_set for text in column), dtype=bool, count=self.size)
        return ~mask if negate else mask


def _compile_regex(value: str, label: str) -> re.Pattern:
    try:
        return re.compile(value, re.IGNORECASE)
    except re.error as exc:
        raise ConditionError(f"{label}: {exc}") from None


def _number_or_nan(value: Any) -> float:
    if value is None or value == "":
        return np.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


_index_lock = threading.Lock()
_index: CatalogIndex | None = None


def catalog_index(parts_data: Any) -> CatalogIndex:
    """The index for this catalog generation, built once and shared."""
    global _index
    generation = getattr(parts_data, "generation", 0)
    with _index_lock:
        if _index is not None and _index.generation == generation and _index._parts is (getattr(parts_data, "parts", None) or {}):
            return _index
        _index = CatalogIndex(parts_data)
        return _index


# --- Documents ---------------------------------------------------------------


@dataclass
class Problem:
    rule_id: str | None
    message: str
    condition_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"rule_id": self.rule_id, "condition_id": self.condition_id, "message": self.message}


def normalize_fallback(raw: Any) -> str | None:
    """The one fallback a document asks for: "bl_category", "rb_category",
    "color" or None. BrickLink categories win over Rebrickable ones, and either
    over color, which is how the three switches were read before they were one
    choice."""
    flags = raw if isinstance(raw, dict) else {}
    if flags.get("bricklink_categories"):
        return "bl_category"
    if flags.get("rebrickable_categories"):
        return "rb_category"
    if flags.get("by_color"):
        return "color"
    return None


def fallback_flags(by: str | None) -> dict[str, bool]:
    return {
        "rebrickable_categories": by == "rb_category",
        "bricklink_categories": by == "bl_category",
        "by_color": by == "color",
    }


def _migrate_rule(rule: dict[str, Any], problems: list[Problem]) -> dict[str, Any]:
    rule = dict(rule)
    rule.pop("priority", None)
    rule["id"] = str(rule.get("id") or uuid.uuid4())
    rule_type = str(rule.get("rule_type") or "filter")
    rule["rule_type"] = rule_type
    rule["name"] = str(rule.get("name") or "").strip() or "Untitled"
    rule["disabled"] = bool(rule.get("disabled", False))
    if rule_type == "filter":
        rule["match_mode"] = "any" if rule.get("match_mode") == "any" else "all"
        conditions = rule.get("conditions")
        if isinstance(conditions, dict):
            conditions = _flatten_condition_tree(conditions)
        normalized = []
        for raw in conditions if isinstance(conditions, list) else []:
            if not isinstance(raw, dict):
                continue
            condition = {**raw, "id": str(raw.get("id") or uuid.uuid4())}
            try:
                normalized.append(normalize_condition(condition))
            except ConditionError as exc:
                problems.append(Problem(rule["id"], str(exc), condition["id"]))
                normalized.append({**condition, "invalid": True})
        rule["conditions"] = normalized
        rule["children"] = [_migrate_rule(child, problems) for child in rule.get("children") or [] if isinstance(child, dict)]
    return rule


def _flatten_condition_tree(tree: dict[str, Any]) -> list[dict[str, Any]]:
    if tree.get("type") == "predicate":
        return [{"id": tree.get("id") or str(uuid.uuid4()), "field": tree.get("field"), "op": tree.get("op"), "value": tree.get("value")}]
    out: list[dict[str, Any]] = []
    for child in tree.get("children", []):
        out.extend(_flatten_condition_tree(child))
    return out


def normalize_document(document: dict[str, Any]) -> tuple[dict[str, Any], list[Problem]]:
    """The document with every rule and condition in its current form (old
    shapes migrated, values coerced to their field's type), and the problems
    that keep a condition from being evaluated."""
    problems: list[Problem] = []
    rules = [_migrate_rule(rule, problems) for rule in document.get("rules") or [] if isinstance(rule, dict)]
    by = normalize_fallback(document.get("fallback_mode"))
    normalized = {
        "id": str(document.get("id") or ""),
        "name": str(document.get("name") or "").strip() or "Untitled Profile",
        "description": str(document.get("description") or ""),
        "default_category_id": str(document.get("default_category_id") or "misc").strip() or "misc",
        "fallback_mode": fallback_flags(by),
        "rules": rules,
    }
    return normalized, problems


def walk_rules(rules: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for rule in rules:
        yield rule
        yield from walk_rules(rule.get("children") or [])


def find_rule(rules: Iterable[dict[str, Any]], rule_id: str) -> dict[str, Any] | None:
    return next((rule for rule in walk_rules(rules) if rule.get("id") == rule_id), None)


def ancestors_of(rules: list[dict[str, Any]], rule_id: str) -> list[dict[str, Any]] | None:
    for rule in rules:
        if rule.get("id") == rule_id:
            return []
        found = ancestors_of(rule.get("children") or [], rule_id)
        if found is not None:
            return [rule, *found]
    return None


# --- Evaluating a rule ---------------------------------------------------------


def _and(results: list[Any], size: int) -> Any:
    masks = []
    for result in results:
        if result is False:
            return False
        if result is not True:
            masks.append(result)
    if not masks:
        return True
    return np.logical_and.reduce(masks) if len(masks) > 1 else masks[0]


def _or(results: list[Any], size: int) -> Any:
    masks = []
    for result in results:
        if result is True:
            return True
        if result is not False:
            masks.append(result)
    if not masks:
        return False
    return np.logical_or.reduce(masks) if len(masks) > 1 else masks[0]


def _enabled_conditions(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield from node.get("conditions") or []
    for child in node.get("children") or []:
        if not child.get("disabled"):
            yield from _enabled_conditions(child)


def has_conditions(rule: dict[str, Any]) -> bool:
    return any(not condition.get("invalid") for condition in _enabled_conditions(rule))


def _color_matches(condition: dict[str, Any], rb_color_id: int) -> bool:
    op, value = condition["op"], condition["value"]
    if op == "eq":
        return rb_color_id == value
    if op == "neq":
        return rb_color_id != value
    if op == "in":
        return rb_color_id in value
    return rb_color_id not in value


class _Evaluator:
    def __init__(self, index: CatalogIndex) -> None:
        self.index = index

    def evaluate(self, node: dict[str, Any], color_truth: dict[int, bool]) -> Any:
        results: list[Any] = []
        for condition in node.get("conditions") or []:
            if condition.get("invalid"):
                # Half-made conditions take nothing, whatever they are combined with.
                return False
            if condition["field"] == "color_id":
                results.append(color_truth[id(condition)])
            else:
                results.append(self.index.part_mask(condition))
        for child in node.get("children") or []:
            if child.get("disabled"):
                continue
            results.append(self.evaluate(child, color_truth))
        if not results:
            return True
        if node.get("match_mode") == "any":
            return _or(results, self.index.size)
        return _and(results, self.index.size)

    def groups(self, rules: list[dict[str, Any]]) -> list[tuple[Any, list[str] | None]]:
        """What a chain of rules (a rule's ancestors, then the rule) takes, as
        (parts, colors) pairs: parts True (every part) or a mask, colors a list
        of BrickLink color IDs or None for every color."""
        color_conditions = [
            condition
            for rule in rules
            for condition in _enabled_conditions(rule)
            if condition["field"] == "color_id" and not condition.get("invalid")
        ]

        def combined(color_truth: dict[int, bool]) -> Any:
            return _and([self.evaluate(rule, color_truth) for rule in rules], self.index.size)

        if not color_conditions:
            result = combined({})
            return [] if result is False else [(result, None)]
        by_signature: dict[tuple[bool, ...], list[int]] = {}
        for rb_color_id in self.index.colors:
            signature = tuple(_color_matches(condition, rb_color_id) for condition in color_conditions)
            by_signature.setdefault(signature, []).append(rb_color_id)
        out: list[tuple[Any, list[str] | None]] = []
        for signature, rb_color_ids in by_signature.items():
            result = combined({id(condition): truth for condition, truth in zip(color_conditions, signature)})
            if result is False:
                continue
            if len(by_signature) == 1:
                out.append((result, None))
            else:
                out.append((result, sorted({self.index.bl_color(rb) for rb in rb_color_ids}, key=_color_sort_key)))
        return out


def _color_sort_key(color: str) -> tuple[int, str]:
    return (int(color), color) if color.lstrip("-").isdigit() else (1 << 30, color)


# --- Describing a rule to a person ----------------------------------------------


def _value_label(spec_ref: str | None, value: Any, index: CatalogIndex) -> dict[str, Any]:
    out: dict[str, Any] = {"value": value, "label": str(value)}
    if spec_ref == "rb_category":
        category = index.categories.get(value)
        if category:
            out["label"] = category.get("name") or str(value)
    elif spec_ref == "bl_category":
        category = index.bricklink_categories.get(value)
        if isinstance(category, dict):
            out["label"] = category.get("category_name") or str(value)
    elif spec_ref == "color":
        color = index.colors.get(value)
        if color:
            out["label"] = color.get("name") or str(value)
            out["rgb"] = color.get("rgb")
            out["bricklink_id"] = index.bl_color(value)
    elif spec_ref in ("part", "bl_part"):
        rows = index.rows_for(value) if spec_ref == "bl_part" else ([index.row_of[value]] if value in index.row_of else [])
        if rows:
            part = index.part(rows[0])
            out["label"] = part.get("name") or str(value)
            out["img_url"] = part.get("part_img_url")
            out["part_num"] = part.get("part_num")
            out["bricklink_id"] = index.keys[rows[0]][0]
    return out


def _format_number(value: Any, unit: str | None) -> str:
    text = f"{value:g}" if isinstance(value, float) else str(value)
    if unit == "$":
        return f"${value:,.2f}" if isinstance(value, (int, float)) else f"${text}"
    return f"{text} {unit}" if unit else text


def describe_condition(condition: dict[str, Any], index: CatalogIndex) -> dict[str, Any]:
    spec = field_spec(str(condition.get("field") or ""))
    op = str(condition.get("op") or "")
    out: dict[str, Any] = {
        "id": condition.get("id"),
        "field": condition.get("field"),
        "field_label": spec.label if spec else str(condition.get("field")),
        "op": op,
        "op_label": OP_LABELS.get(op, op),
        "values": [],
        "invalid": bool(condition.get("invalid")),
    }
    if spec is None or condition.get("invalid"):
        # Shown as typed, and nothing when nothing was typed yet.
        raw = condition.get("value")
        values = raw if isinstance(raw, list) else [] if raw in (None, "") else [raw]
        out["values"] = [{"value": value, "label": str(value)} for value in values if value not in (None, "")]
        return out
    raw = condition.get("value")
    values = raw if isinstance(raw, list) else [raw]
    labelled = []
    for value in values:
        entry = _value_label(spec.ref, value, index)
        if spec.type == BOOL:
            entry["label"] = "Yes" if value else "No"
        elif spec.ref is None and spec.type in (INT, FLOAT):
            entry["label"] = _format_number(value, spec.unit)
        labelled.append(entry)
    out["values"] = labelled
    return out


def describe_conditions(rule: dict[str, Any], index: CatalogIndex) -> dict[str, Any]:
    return {
        "mode": rule.get("match_mode", "all"),
        "items": [describe_condition(condition, index) for condition in rule.get("conditions") or []],
        "groups": [
            {"id": child.get("id"), "name": child.get("name"), **describe_conditions(child, index)}
            for child in rule.get("children") or []
            if not child.get("disabled")
        ],
    }


def _sample_rows(mask: np.ndarray, index: CatalogIndex, limit: int = SAMPLE_LIMIT) -> list[int]:
    rows = np.flatnonzero(mask)
    if rows.size == 0:
        return []
    if rows.size > limit:
        popularity = index.popularity()[rows]
        top = np.argpartition(-popularity, limit - 1)[:limit]
        rows = rows[top[np.argsort(-popularity[top])]]
    return [int(row) for row in rows[:limit]]


def part_preview(row: int, index: CatalogIndex) -> dict[str, Any]:
    part = index.part(row)
    rb_category = index.categories.get(part.get("part_cat_id"))
    bl_category_id = bricklink_category_id(part)
    bl_category = index.bricklink_categories.get(bl_category_id) if bl_category_id is not None else None
    return {
        "part_num": part.get("part_num"),
        "bricklink_id": index.keys[row][0] if bricklink_ids(part) else None,
        "bricklink_ids": bricklink_ids(part),
        "name": part.get("name") or "",
        "img_url": part.get("part_img_url"),
        "rb_category": {"id": part.get("part_cat_id"), "name": rb_category.get("name")} if rb_category else None,
        "bl_category": (
            {"id": bl_category_id, "name": bl_category.get("category_name")}
            if isinstance(bl_category, dict)
            else None
        ),
        "year_from": part.get("year_from"),
        "year_to": part.get("year_to"),
    }


# Rebrickable renders a part in any color at this address (from its LDraw
# model); the catalog's own picture of a part is one photo in one color. A
# printed part may have no render: pages fall back to the photo.
COLOR_RENDER = "https://cdn.rebrickable.com/media/parts/ldraw/{color}/{part}.png"


def colored_picture(rb_part_num: str | None, rb_color_id: Any) -> str | None:
    if not rb_part_num or rb_color_id in (None, "", -1, "-1"):
        return None
    return COLOR_RENDER.format(color=rb_color_id, part=rb_part_num)


def _sample(row: int, index: CatalogIndex, bl_color: str | None = None) -> dict[str, Any]:
    """One example part; in a bin's color, when the bin takes only some."""
    part = index.part(row)
    photo = part.get("part_img_url")
    color = index.bl_colors.get(bl_color) if bl_color is not None else None
    picture = colored_picture(part.get("part_num"), color.get("rb_id")) if color else None
    sample = {
        "part_num": index.keys[row][0],
        "rb_part_num": part.get("part_num"),
        "name": part.get("name") or "",
        "img_url": picture or photo,
        "fallback_img_url": photo if picture else None,
        # the shape old Hive and sorter pages read samples in
        "part_img_url": photo,
    }
    if color:
        sample["color_name"] = color.get("name")
    return sample


def _sample_color(row: int, preferred: list[str], index: CatalogIndex) -> str | None:
    """The first of a rule's colors the part is known to come in, or its first."""
    if not preferred:
        return None
    if index.known_color_rows:
        for color in preferred:
            rows = index.known_color_rows.get(color)
            if rows is not None and np.searchsorted(rows, row) < rows.size and rows[np.searchsorted(rows, row)] == row:
                return color
    return preferred[0]


def _rule_colors_in_order(rule: dict[str, Any], index: CatalogIndex) -> list[str]:
    """The BrickLink colors a rule names in its eq and in conditions, in the
    order the person gave them (a bin shows its parts in the first)."""
    out: list[str] = []
    for condition in _enabled_conditions(rule):
        if condition.get("invalid") or condition.get("field") != "color_id" or condition.get("op") not in ("eq", "in"):
            continue
        values = condition["value"] if isinstance(condition["value"], list) else [condition["value"]]
        for value in values:
            color = index.bl_color(value)
            if color not in out:
                out.append(color)
    return out


# --- Compiling ------------------------------------------------------------------


@dataclass
class Compiled:
    artifact: dict[str, Any]
    problems: list[Problem] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def artifact_hash(self) -> str:
        return self.artifact["artifact_hash"]

    @property
    def stats(self) -> dict[str, Any]:
        return self.artifact["stats"]

    @property
    def requires(self) -> list[str]:
        return self.artifact.get("requires", [])


def _keys_for_rows(rows: np.ndarray, index: CatalogIndex) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in index.keys[int(row)]:
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out


def _kit_items(inventory: dict[str, Any], index: CatalogIndex) -> tuple[dict[str, list[str | None]], int]:
    """A kit's parts as {BrickLink part: [BrickLink colors, None for any]}, with
    every ID the catalog knows the part by; and how many lines take any color."""
    items: dict[str, list[str | None]] = {}
    any_color_lines = 0
    for part in inventory.get("parts") or []:
        color = part.get("color_id")
        any_color = color in (None, KIT_ANY_COLOR_ID, str(KIT_ANY_COLOR_ID), ANY_COLOR)
        any_color_lines += int(any_color)
        color_key: str | None = None if any_color else str(color)
        rb_part = part.get("rb_part_num")
        keys = list(index.keys[index.row_of[rb_part]]) if rb_part in index.row_of else []
        primary = str(part.get("part_num") or "")
        if primary and primary not in keys:
            keys.insert(0, primary)
        for key in keys:
            colors = items.setdefault(key, [])
            if color_key not in colors:
                colors.append(color_key)
    return items, any_color_lines


def _kit_sample(part: dict[str, Any]) -> dict[str, Any]:
    photo = part.get("img_url")
    picture = colored_picture(part.get("rb_part_num"), part.get("rb_color_id"))
    return {
        "part_num": part.get("part_num"),
        "rb_part_num": part.get("rb_part_num"),
        "name": part.get("part_name") or part.get("part_num"),
        "img_url": picture or photo,
        "fallback_img_url": photo if picture else None,
        "part_img_url": photo,
        "color_name": part.get("color_name"),
        "quantity": part.get("quantity"),
    }


def _kit_image(rule: dict[str, Any], inventory: dict[str, Any]) -> tuple[str | None, str | None]:
    if rule.get("image_url"):
        return rule["image_url"], "rule"
    if inventory.get("img_url"):
        return inventory["img_url"], "kit"
    for part in inventory.get("parts") or []:
        if part.get("img_url"):
            return part["img_url"], "part"
    return None, None


def compile_document(
    document: dict[str, Any],
    index: CatalogIndex,
    inventories: dict[str, dict[str, Any]] | None = None,
) -> Compiled:
    """Compile a document. `inventories` holds each kit (and old-style set)
    rule's parts, resolved by the caller, keyed by rule ID."""
    doc, problems = normalize_document(document)
    inventories = inventories or {}
    evaluator = _Evaluator(index)
    size = index.size
    fully_claimed = np.zeros(size, dtype=bool)
    matched = np.zeros(size, dtype=bool)
    program_rules: list[dict[str, Any]] = []
    categories: dict[str, dict[str, Any]] = {}
    per_category: dict[str, dict[str, int]] = {}
    samples: dict[str, list[dict[str, Any]]] = {}
    set_inventories: dict[str, dict[str, Any]] = {}
    warnings: list[dict[str, Any]] = []
    filter_entries_so_far: list[tuple[str, Any, list[str] | None]] = []
    catch_all_rule: str | None = None

    for rule in doc["rules"]:
        rule_id = rule["id"]
        if rule["disabled"]:
            continue
        if catch_all_rule is not None:
            warnings.append({"rule_id": rule_id, "code": "unreachable", "message": f"Nothing reaches this rule: {categories[catch_all_rule]['name']} takes every piece first."})
        if rule["rule_type"] in ("kit", "set"):
            inventory = inventories.get(rule_id)
            display: dict[str, Any] = {
                "name": rule["name"],
                "kind": "kit",
                "part_count": 0,
                "samples": [],
                "image_url": rule.get("image_url"),
                "image_source": "rule" if rule.get("image_url") else None,
            }
            if not inventory or not inventory.get("parts"):
                categories[rule_id] = display
                warnings.append({"rule_id": rule_id, "code": "kit_empty", "message": "This kit has no parts yet."})
                continue
            items, any_color_lines = _kit_items(inventory, index)
            program_rules.append({"category": rule_id, "kit": items})
            set_inventories[rule_id] = inventory
            kit_rows = sorted({row for key in items for row in index.rows_by_key.get(key, [])})
            if kit_rows:
                matched[kit_rows] = True
            image_url, image_source = _kit_image(rule, inventory)
            total_quantity = sum(int(part.get("quantity") or 0) for part in inventory["parts"])
            display.update(
                {
                    "image_url": image_url,
                    "image_source": image_source,
                    "part_count": len(inventory["parts"]),
                    "samples": [_kit_sample(part) for part in inventory["parts"][:SAMPLE_LIMIT]],
                    "kit": {
                        "kit_id": rule.get("kit_id"),
                        "set_num": inventory.get("set_num"),
                        "line_count": len(inventory["parts"]),
                        "total_quantity": total_quantity,
                        "any_color_lines": any_color_lines,
                    },
                    # what pages written before kits read a set by
                    "set_source": inventory.get("set_source"),
                    "set_num": inventory.get("set_num"),
                }
            )
            if inventory.get("img_url"):
                display["set_img_url"] = inventory["img_url"]
            categories[rule_id] = display
            per_category[rule_id] = {"parts": len(inventory["parts"]), "colors": 0}
            samples[rule_id] = display["samples"]
            if any_color_lines:
                warnings.append(
                    {
                        "rule_id": rule_id,
                        "code": "kit_any_color",
                        "message": f"{any_color_lines} of this kit's lines have no color, so a piece of any color counts toward them.",
                    }
                )
            shadowed = _kit_lines_taken_earlier(items, filter_entries_so_far, index)
            if shadowed:
                warnings.append(
                    {
                        "rule_id": rule_id,
                        "code": "kit_parts_taken_above",
                        "message": f"{shadowed} of this kit's parts go to rules above it; move the kit up to collect them.",
                    }
                )
            continue

        display = {
            "name": rule["name"],
            "kind": "rule",
            "conditions": describe_conditions(rule, index),
            "part_count": 0,
            "samples": [],
            "image_url": rule.get("image_url"),
            "image_source": "rule" if rule.get("image_url") else None,
        }
        categories[rule_id] = display
        if any(condition.get("invalid") for condition in _enabled_conditions(rule)):
            warnings.append({"rule_id": rule_id, "code": "condition_incomplete", "message": "A condition here is incomplete, so this rule takes nothing until it is fixed."})
            continue
        if not has_conditions(rule):
            warnings.append({"rule_id": rule_id, "code": "no_conditions", "message": "This rule has no conditions yet, so it takes nothing."})
            continue
        received = np.zeros(size, dtype=bool)
        # What the bin is shown by: for a color-limited part of the rule, the
        # parts known to come in those colors (when the catalog knows).
        shown = np.zeros(size, dtype=bool)
        color_set: set[str] = set()
        any_color = False
        any_part = False
        # Whether the rule matches any part at all, before the rules above take theirs.
        matches_any = False
        for parts, colors in evaluator.groups([rule]):
            mask = np.ones(size, dtype=bool) if parts is True else parts
            matches_any = matches_any or parts is True or bool(mask.any())
            receives = mask & ~fully_claimed
            if parts is not True and not receives.any():
                continue
            program_rules.append(
                {
                    "category": rule_id,
                    "parts": None if parts is True else _keys_for_rows(np.flatnonzero(receives), index),
                    "colors": colors,
                }
            )
            filter_entries_so_far.append((rule_id, parts, colors))
            received |= receives
            any_part = any_part or parts is True
            if colors is None:
                any_color = True
                fully_claimed |= mask
                shown |= receives
                if parts is True:
                    catch_all_rule = rule_id
            else:
                color_set.update(colors)
                known = index.known_in(colors)
                shown |= receives if known is None else receives & known
        matched |= received
        part_count = int(shown.sum())
        display["part_count"] = part_count
        if any_part:
            # Takes any part in its colors, including parts the catalog lacks.
            display["any_part"] = True
        if not any_color:
            display["color_count"] = len(color_set)
            display["colors"] = [index.bl_colors.get(color, {"id": color, "name": color}) for color in sorted(color_set, key=_color_sort_key)[:24]]
        # Shown in the rule's own colors when it takes only some.
        preferred = [] if any_color else [color for color in _rule_colors_in_order(rule, index) if color in color_set] or sorted(color_set, key=_color_sort_key)
        display["samples"] = [_sample(row, index, _sample_color(row, preferred, index)) for row in _sample_rows(shown, index)]
        if not display["image_url"] and display["samples"]:
            display["image_url"] = display["samples"][0]["img_url"]
            display["image_fallback_url"] = display["samples"][0].get("fallback_img_url")
            display["image_source"] = "part" if display["image_url"] else None
        per_category[rule_id] = {"parts": part_count, "colors": 0 if any_color else len(color_set)}
        samples[rule_id] = display["samples"]
        if not received.any():
            if matches_any:
                warnings.append({"rule_id": rule_id, "code": "taken_above", "message": "Rules above this one already take every part it matches."})
            else:
                warnings.append({"rule_id": rule_id, "code": "matches_nothing", "message": "No part in the catalog matches this rule."})

    fallback_by = normalize_fallback(doc["fallback_mode"])
    default_category = doc["default_category_id"]
    requires: list[str] = []
    program_fallback: dict[str, Any] | None = None
    fallback_counts: dict[str, int] = {}
    fallback_rows: dict[str, list[int]] = {}
    rest = ~fully_claimed
    if fallback_by in ("bl_category", "rb_category"):
        fallback_map: dict[str, str] = {}
        column, prefix = (
            (index.column("bl_category_id"), "bl_")
            if fallback_by == "bl_category"
            else (index.column("category_id"), "rb_")
        )
        for row in np.flatnonzero(rest):
            if np.isnan(column[row]):
                continue
            category = f"{prefix}{int(column[row])}"
            if category == default_category:
                continue
            fallback_rows.setdefault(category, []).append(int(row))
            for key in index.keys[row]:
                fallback_map.setdefault(key, category)
        program_fallback = {"by": "category", "map": fallback_map}
        for category, rows in fallback_rows.items():
            fallback_counts[category] = len(rows)
            mask = np.zeros(size, dtype=bool)
            mask[rows] = True
            # A fallback can make hundreds of bins: each keeps its best known
            # part's picture, not a row of examples.
            best = _sample_rows(mask, index, limit=1)
            picture = index.part(best[0]).get("part_img_url") if best else None
            categories[category] = {
                "name": _fallback_category_name(category, index),
                "kind": "fallback",
                "part_count": len(rows),
                "samples": [],
                "image_url": picture,
                "image_source": "part" if picture else None,
            }
            per_category[category] = {"parts": len(rows), "colors": 0}
    elif fallback_by == "color":
        program_fallback = {"by": "color"}
        requires.append(FEATURE_COLOR_FALLBACK)
        for bl_id, color in sorted(index.bl_colors.items(), key=lambda item: _color_sort_key(item[0])):
            categories[f"color_{bl_id}"] = {
                "name": color.get("name") or f"Color {bl_id}",
                "kind": "fallback",
                "rgb": color.get("rgb"),
                # Which parts come in which color is up to the pile, not the catalog.
                "part_count": None,
                "samples": [],
            }

    unmatched_count = int((~matched).sum())
    default_rows = ~matched
    if fallback_by == "color":
        # Every piece left over goes to its color; only uncolored ones get here.
        default_rows = np.zeros(size, dtype=bool)
    elif fallback_rows:
        # Parts the fallback sends to their category are not left over.
        in_fallback = np.zeros(size, dtype=bool)
        for rows in fallback_rows.values():
            in_fallback[rows] = True
        default_rows = default_rows & ~in_fallback
    categories.setdefault(
        default_category,
        {
            "name": "Everything else" if default_category == "misc" else default_category,
            "kind": "default",
            "part_count": int(default_rows.sum()),
            "samples": [_sample(row, index) for row in _sample_rows(default_rows, index)],
        },
    )
    per_category[default_category] = {"parts": int(default_rows.sum()), "colors": 0}

    program = {
        "format": PROGRAM_FORMAT,
        "rules": program_rules,
        "fallback": program_fallback,
        "default": default_category,
    }
    stats = {
        "total_parts": size,
        "matched": int(matched.sum()),
        "unmatched": unmatched_count,
        # Parts that go to a bin of their own (a rule, a kit or a fallback
        # category) rather than the default bin.
        "sorted": size - int(default_rows.sum()),
        "per_category": per_category,
        "samples": samples,
    }
    category_order = [rule["id"] for rule in doc["rules"] if not rule["disabled"] and rule["id"] in categories]
    category_order += sorted(
        (category for category in fallback_counts),
        key=lambda category: -fallback_counts[category],
    )
    if default_category not in category_order:
        category_order.append(default_category)
    # The first bins in order, small enough to keep beside a version's stats
    # for lists that show a profile by its bins without loading the artifact.
    stats["bins"] = [
        {
            "id": category,
            "name": categories[category].get("name"),
            "kind": categories[category].get("kind"),
            "image_url": categories[category].get("image_url"),
            "rgb": categories[category].get("rgb"),
            "part_count": categories[category].get("part_count"),
        }
        for category in category_order[:12]
    ]
    artifact: dict[str, Any] = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "id": doc["id"],
        "name": doc["name"],
        "description": doc["description"],
        "profile_type": "set" if set_inventories else "rule",
        "default_category_id": default_category,
        "fallback_mode": doc["fallback_mode"],
        "rules": doc["rules"],
        "categories": categories,
        "category_order": category_order,
        "program": program,
        "stats": stats,
        "requires": requires,
    }
    if set_inventories:
        artifact["set_inventories"] = set_inventories
    artifact["artifact_hash"] = hashlib.sha256(json.dumps(artifact, sort_keys=True, default=str).encode()).hexdigest()
    return Compiled(artifact=artifact, problems=problems, warnings=warnings)


def _fallback_category_name(category: str, index: CatalogIndex) -> str:
    kind, _, raw = category.partition("_")
    try:
        number = int(raw)
    except ValueError:
        return category
    if kind == "bl":
        entry = index.bricklink_categories.get(number)
        return entry.get("category_name", category) if isinstance(entry, dict) else category
    if kind == "rb":
        entry = index.categories.get(number)
        return entry.get("name", category) if entry else category
    return category


def _kit_lines_taken_earlier(
    items: dict[str, list[str | None]],
    earlier: list[tuple[str, Any, list[str] | None]],
    index: CatalogIndex,
) -> int:
    """How many of a kit's parts an earlier rule takes in every color the kit
    wants them in, so the kit never sees them."""
    if not earlier:
        return 0
    taken = 0
    for key, colors in items.items():
        rows = index.rows_by_key.get(key)
        if not rows:
            continue
        row = rows[0]
        for _rule_id, parts, rule_colors in earlier:
            part_hit = parts is True or bool(parts[row])
            if not part_hit:
                continue
            if rule_colors is None or all(color is not None and color in rule_colors for color in colors):
                taken += 1
                break
    return taken


# --- The flat map, for sorters from before the program ---------------------


def expand_legacy(artifact: dict[str, Any], index: CatalogIndex) -> dict[str, Any]:
    """The artifact as a sorter without the program reads it: a flat map from
    "{color}-{part}" and "any_color-{part}" to a category, which it looks up
    exact color first. Built rule by rule, first claim wins, so it routes every
    piece the way the program does. Parts that end up in the default category
    are left out; a lookup that misses returns the default."""
    program = artifact.get("program")
    if not isinstance(program, dict):
        return artifact
    part_to_category: dict[str, str] = {}
    full: set[str] = set()
    every_key: list[str] | None = None
    for entry in program.get("rules") or []:
        category = entry["category"]
        kit = entry.get("kit")
        if kit is not None:
            for part, colors in kit.items():
                if part in full:
                    continue
                for color in colors:
                    if color is not None:
                        part_to_category.setdefault(f"{color}-{part}", category)
                if None in colors:
                    part_to_category.setdefault(f"{ANY_COLOR}-{part}", category)
                    full.add(part)
            continue
        parts = entry.get("parts")
        if parts is None:
            if every_key is None:
                every_key = [key for keys in index.keys for key in keys]
            parts = every_key
        colors = entry.get("colors")
        for part in parts:
            if part in full:
                continue
            if colors is None:
                part_to_category.setdefault(f"{ANY_COLOR}-{part}", category)
                full.add(part)
            else:
                for color in colors:
                    part_to_category.setdefault(f"{color}-{part}", category)
    fallback = program.get("fallback") or {}
    default = program.get("default")
    if fallback.get("by") == "category":
        for part, category in (fallback.get("map") or {}).items():
            if part not in full and category != default:
                part_to_category.setdefault(f"{ANY_COLOR}-{part}", category)
    legacy = {key: value for key, value in artifact.items() if key not in ("program", "category_order")}
    legacy["schema_version"] = 1
    legacy["part_to_category"] = part_to_category
    return legacy


# --- Asking a compiled profile where a piece goes ----------------------------


class Router:
    """The program as a sorter runs it: first rule that takes the piece; a kit
    that already has enough of it passes it on."""

    def __init__(self, program: dict[str, Any]) -> None:
        self.rules: list[tuple[str, str, Any, Any]] = []
        for entry in program.get("rules") or []:
            if entry.get("kit") is not None:
                self.rules.append(("kit", entry["category"], {part: set(colors) for part, colors in entry["kit"].items()}, None))
            else:
                parts = entry.get("parts")
                colors = entry.get("colors")
                self.rules.append(
                    ("rule", entry["category"], None if parts is None else set(parts), None if colors is None else set(colors))
                )
        fallback = program.get("fallback") or {}
        self.fallback_by = fallback.get("by")
        self.fallback_map: dict[str, str] = fallback.get("map") or {}
        self.default = program.get("default") or "misc"

    def route(
        self,
        part: str,
        color: str | None,
        kit_is_full: Callable[[str, str, str | None], bool] | None = None,
    ) -> tuple[str, str]:
        """(category, why): why is "rule", "kit", "fallback" or "default"."""
        for kind, category, parts, colors in self.rules:
            if kind == "kit":
                wanted = parts.get(part)
                if wanted is None or not (color in wanted or None in wanted):
                    continue
                if kit_is_full is not None and kit_is_full(category, part, color):
                    continue
                return category, "kit"
            if parts is not None and part not in parts:
                continue
            if colors is not None and color not in colors:
                continue
            return category, "rule"
        if self.fallback_by == "category" and part in self.fallback_map:
            return self.fallback_map[part], "fallback"
        if self.fallback_by == "color" and color not in (None, "", ANY_COLOR):
            return f"color_{color}", "fallback"
        return self.default, "default"


# --- One rule's matches, for the editor ----------------------------------------


def rule_matches(
    rules: list[dict[str, Any]],
    rule_id: str,
    index: CatalogIndex,
    *,
    q: str = "",
    offset: int = 0,
    limit: int = 50,
    standalone: bool = False,
) -> dict[str, Any]:
    """The parts a rule matches (inside its parent rules unless standalone),
    most sold first, with the colors it limits them to."""
    doc, problems = normalize_document({"rules": copy.deepcopy(rules)})
    rule = find_rule(doc["rules"], rule_id)
    if rule is None:
        raise KeyError(rule_id)
    chain = [rule] if standalone else [*(ancestors_of(doc["rules"], rule_id) or []), rule]
    rule_problems = [problem.as_dict() for problem in problems if problem.rule_id in {item["id"] for item in chain}]
    if not all(has_conditions(item) for item in chain):
        return {"total": 0, "items": [], "offset": offset, "limit": limit, "colors": None, "problems": rule_problems}
    evaluator = _Evaluator(index)
    mask = np.zeros(index.size, dtype=bool)
    colors: set[str] | None = set()
    for parts, group_colors in evaluator.groups(chain):
        group = np.ones(index.size, dtype=bool) if parts is True else parts
        if group_colors is None:
            colors = None
        else:
            # Counted like a bin: the parts known to come in those colors, when the catalog knows.
            known = index.known_in(group_colors)
            if known is not None:
                group = group & known
            if colors is not None:
                colors.update(group_colors)
        mask |= group
    needle = q.strip().lower()
    rows = np.flatnonzero(mask)
    if needle:
        names = index.column("name")
        rows = np.array(
            [row for row in rows if needle in names[row].lower() or needle in index.part_nums[row].lower() or any(needle in key.lower() for key in index.keys[row])],
            dtype=np.int64,
        )
    if rows.size:
        popularity = index.popularity()[rows]
        rows = rows[np.argsort(-popularity, kind="stable")]
    page = rows[offset : offset + limit] if limit else rows[offset:]
    return {
        "total": int(rows.size),
        "items": [part_preview(int(row), index) for row in page],
        "offset": offset,
        "limit": limit,
        "colors": None if colors is None else [index.bl_colors.get(color, {"id": color, "name": color}) for color in sorted(colors, key=_color_sort_key)],
        "problems": rule_problems,
    }
