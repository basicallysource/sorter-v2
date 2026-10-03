"""The fields a sorting rule can test, what each one reads off a catalog part,
and how each is named to a person.

A condition is {"field", "op", "value"}. Every field has one type, and a
condition's value is coerced to that type before it is compared: a BrickLink
ID typed as the number 3001 still matches the part whose ID is the text
"3001". Comparing the raw JSON value is how such a rule used to match nothing.

Most fields are looked up in the catalog by the part's identity. A few
(`piece`) are what the machine observes about one piece as it sorts it: how
sure recognition was, whether it named a part at all, what that part costs in
that color. Those cannot be known when a profile is compiled, so the sorter
tests them itself (compiler.py, `when`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

STR = "str"
INT = "int"
FLOAT = "float"
# A part can carry several BrickLink IDs (a mold and its aliases); a condition
# on one matches when any of them does.
STR_LIST = "str_list"
# A yes or no. A condition's value is true or false (1 or 0, "yes" or "no"
# are read the same) and is stored as 1 or 0.
BOOL = "bool"

TEXT_OPS = ("contains", "regex", "eq", "neq", "in", "not_in")
ID_OPS = ("eq", "neq", "in", "not_in")
NUMBER_OPS = ("eq", "neq", "gte", "lte")
YES_NO_OPS = ("eq", "neq")
# What the machine observes is a measurement, not an ID: compared by threshold.
PIECE_NUMBER_OPS = ("gte", "lte")

# What each type of field can be compared by. A field's own `ops` are the ones
# worth offering; a saved condition may use any its type allows.
TYPE_OPS = {
    "str": ("eq", "neq", "in", "not_in", "contains", "regex"),
    "str_list": ("eq", "neq", "in", "not_in", "contains", "regex"),
    "int": ("eq", "neq", "in", "not_in", "gte", "lte"),
    "float": ("eq", "neq", "in", "not_in", "gte", "lte"),
    "bool": ("eq", "neq"),
}

OP_LABELS = {
    "eq": "is",
    "neq": "is not",
    "in": "is one of",
    "not_in": "is not one of",
    "contains": "contains",
    "regex": "matches",
    "gte": "is at least",
    "lte": "is at most",
}


@dataclass(frozen=True)
class FieldSpec:
    key: str
    type: str
    label: str
    group: str
    ops: tuple[str, ...]
    # What the value is a reference to, so it can be shown by name:
    # "rb_category", "bl_category", "color", "part", "bl_part"; None for plain values.
    ref: str | None = None
    unit: str | None = None
    # What the field reads, when its label does not say it all.
    description: str | None = None
    # An older name for another field: evaluated, not offered.
    alias_of: str | None = None
    # Observed by the machine for each piece, not read from the catalog.
    piece: bool = False


_USED_PRICE = (
    "From BrickLink's price guide for the part's most traded color: used sales of the last six months, "
    "or used pieces for sale now when none sold. The fields named for a section read that section only."
)

FIELDS: dict[str, FieldSpec] = {
    spec.key: spec
    for spec in (
        FieldSpec(
            "name",
            STR,
            "Name",
            "Part",
            TEXT_OPS,
            description=(
                "The part's Rebrickable name, like 'Plate Round 1 x 1 with Solid Stud'. contains ignores case; "
                "matches is a Python regular expression, ignoring case."
            ),
        ),
        FieldSpec("part_num", STR, "Rebrickable part", "Part", ID_OPS, ref="part"),
        FieldSpec("bricklink_id", STR_LIST, "BrickLink ID", "Part", ID_OPS, ref="bl_part"),
        FieldSpec("bl_catalog_name", STR, "BrickLink name", "Part", TEXT_OPS, description="The part's name in BrickLink's catalog."),
        FieldSpec("bricklink_primary_item_no", STR, "BrickLink primary item", "Part", TEXT_OPS),
        FieldSpec("bricklink_item_count", INT, "BrickLink items for the part", "Part", NUMBER_OPS),
        FieldSpec("color_id", INT, "Color", "Color", ID_OPS, ref="color"),
        FieldSpec("bl_category_id", INT, "BrickLink category", "Category", ID_OPS, ref="bl_category"),
        FieldSpec("bl_catalog_category_id", INT, "BrickLink category", "Category", ID_OPS, ref="bl_category", alias_of="bl_category_id"),
        FieldSpec("bl_category_name", STR, "BrickLink category name", "Category", TEXT_OPS),
        FieldSpec("category_id", INT, "Rebrickable category", "Category", ID_OPS, ref="rb_category"),
        FieldSpec("category_name", STR, "Rebrickable category name", "Category", TEXT_OPS),
        FieldSpec("year_from", INT, "First made", "Year", NUMBER_OPS),
        FieldSpec("year_to", INT, "Last made", "Year", NUMBER_OPS),
        FieldSpec("bl_catalog_year_released", INT, "Released (BrickLink)", "Year", NUMBER_OPS),
        FieldSpec("bl_catalog_is_obsolete", BOOL, "Obsolete", "Part", YES_NO_OPS, description="Whether BrickLink lists the part as obsolete."),
        FieldSpec("bl_catalog_weight", FLOAT, "Weight", "Size", NUMBER_OPS, unit="g"),
        FieldSpec("bl_catalog_dim_x", FLOAT, "Length", "Size", NUMBER_OPS, unit="studs"),
        FieldSpec("bl_catalog_dim_y", FLOAT, "Width", "Size", NUMBER_OPS, unit="studs"),
        FieldSpec("bl_catalog_dim_z", FLOAT, "Height", "Size", NUMBER_OPS, unit="studs"),
        FieldSpec("bl_price_avg", FLOAT, "Average price, used", "Price", NUMBER_OPS, unit="$", description=_USED_PRICE),
        FieldSpec("bl_price_min", FLOAT, "Lowest price, used", "Price", NUMBER_OPS, unit="$", description=_USED_PRICE),
        FieldSpec("bl_price_max", FLOAT, "Highest price, used", "Price", NUMBER_OPS, unit="$", description=_USED_PRICE),
        FieldSpec("bl_price_qty_avg", FLOAT, "Average price per lot, used", "Price", NUMBER_OPS, unit="$", description=_USED_PRICE),
        FieldSpec("bl_price_lots", FLOAT, "Lots, used", "Price", NUMBER_OPS, description=_USED_PRICE),
        FieldSpec("bl_price_qty", FLOAT, "Pieces, used", "Price", NUMBER_OPS, description=_USED_PRICE),
        FieldSpec(
            "identified",
            BOOL,
            "Identified",
            "Piece",
            YES_NO_OPS,
            piece=True,
            description=(
                "Whether recognition named a part for this piece. One it could not identify (no match, the request "
                "failed, two pieces at once) has no part and no color, so only rules that test nothing about the part "
                "can take it; without one it goes to the default bin."
            ),
        ),
        FieldSpec(
            "confidence",
            FLOAT,
            "Recognition confidence",
            "Piece",
            PIECE_NUMBER_OPS,
            unit="%",
            piece=True,
            description="How sure recognition was of the part, 0 to 100. A piece it could not identify counts as 0.",
        ),
        FieldSpec(
            "color_confidence",
            FLOAT,
            "Color confidence",
            "Piece",
            PIECE_NUMBER_OPS,
            unit="%",
            piece=True,
            description="How sure recognition was of the color, 0 to 100. Unknown never matches.",
        ),
        FieldSpec(
            "piece_price",
            FLOAT,
            "Price of this piece",
            "Piece",
            PIECE_NUMBER_OPS,
            unit="$",
            piece=True,
            description=(
                "BrickLink's average price for this part in this piece's color, as the machine looks it up while it "
                "sorts (the catalog's price fields read the part's most traded color). Unknown never matches."
            ),
        ),
    )
}

PRICE_SECTIONS = ("inv_new", "inv_used", "ord_new", "ord_used")
PRICE_METRICS = ("min", "max", "avg", "wavg", "lots", "qty")
_SECTION_WORDS = {
    "inv_new": "new, for sale now",
    "inv_used": "used, for sale now",
    "ord_new": "new, last 6 months",
    "ord_used": "used, last 6 months",
}
_METRIC_WORDS = {
    "min": ("Lowest price", "$"),
    "max": ("Highest price", "$"),
    "avg": ("Average price", "$"),
    "wavg": ("Average price per lot", "$"),
    "lots": ("Lots", None),
    "qty": ("Pieces", None),
}
for _section in PRICE_SECTIONS:
    for _metric in PRICE_METRICS:
        _words, _unit = _METRIC_WORDS[_metric]
        _key = f"bl_price_{_section}_{_metric}"
        FIELDS[_key] = FieldSpec(_key, FLOAT, f"{_words} ({_SECTION_WORDS[_section]})", "Price", NUMBER_OPS, unit=_unit)

# Old names for two of the price fields, still accepted in saved profiles.
FIELD_ALIASES = {
    "bl_price_unit_quantity": "bl_price_lots",
    "bl_price_total_quantity": "bl_price_qty",
}


PIECE_FIELDS = frozenset(key for key, spec in FIELDS.items() if spec.piece)


def is_piece_field(field: str) -> bool:
    return canonical_field(field) in PIECE_FIELDS


def field_spec(field: str) -> FieldSpec | None:
    return FIELDS.get(FIELD_ALIASES.get(field, field))


def canonical_field(field: str) -> str:
    return FIELD_ALIASES.get(field, field)


class ConditionError(ValueError):
    """A condition that cannot be evaluated: unknown field, an operator the
    field does not take, or a value that is not of the field's type."""


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, str) and "," in value:
        return [item.strip() for item in value.split(",") if item.strip()]
    return [value]


def _coerce_one(field: FieldSpec, value: Any) -> Any:
    if field.type in (STR, STR_LIST):
        if value is None:
            raise ConditionError(f"{field.label}: a value is required")
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        text = str(value).strip()
        if not text:
            raise ConditionError(f"{field.label}: a value is required")
        return text
    if field.type == BOOL:
        word = str(value).strip().lower()
        if word in ("1", "1.0", "true", "yes"):
            return 1
        if word in ("0", "0.0", "false", "no"):
            return 0
        raise ConditionError(f"{field.label}: {value!r} is not true or false")
    if field.type == INT:
        try:
            if isinstance(value, str):
                value = value.strip()
            number = float(value)
        except (TypeError, ValueError):
            raise ConditionError(f"{field.label}: {value!r} is not a whole number") from None
        if not number.is_integer():
            raise ConditionError(f"{field.label}: {value!r} is not a whole number")
        return int(number)
    try:
        if isinstance(value, str):
            value = value.strip().lstrip("$")
        return float(value)
    except (TypeError, ValueError):
        raise ConditionError(f"{field.label}: {value!r} is not a number") from None


def normalize_condition(condition: dict[str, Any]) -> dict[str, Any]:
    """The condition with its field's canonical name and its value coerced to
    the field's type ("in" and "not_in" take a list). Raises ConditionError."""
    field_name = canonical_field(str(condition.get("field") or ""))
    field = FIELDS.get(field_name)
    if field is None:
        raise ConditionError(f"Unknown field {condition.get('field')!r}")
    op = str(condition.get("op") or "")
    if op not in (field.ops if field.piece else TYPE_OPS[field.type]):
        raise ConditionError(f"{field.label} does not take {op!r}; use one of {', '.join(field.ops)}")
    raw = condition.get("value")
    if op in ("in", "not_in"):
        values = [_coerce_one(field, item) for item in _as_list(raw)]
        if not values:
            raise ConditionError(f"{field.label}: list at least one value")
        value: Any = values
    elif op in ("contains", "regex"):
        if raw is None or not str(raw).strip():
            raise ConditionError(f"{field.label}: a value is required")
        value = str(raw).strip()
        if op == "regex":
            try:
                re.compile(value)
            except re.error as exc:
                raise ConditionError(f"{field.label}: {value!r} is not a valid pattern ({exc})") from None
    else:
        value = _coerce_one(field, raw)
    return {**condition, "field": field_name, "op": op, "value": value}


# --- Reading a field off a catalog part -------------------------------------
# Parts come from the catalog as Rebrickable records with the BrickLink catalog
# entry and price guide folded in (profile_engine.db.loadPartsDict).


def _bricklink_primary_item(part: dict[str, Any]) -> dict[str, Any] | None:
    bricklink_data = part.get("bricklink_data")
    if not isinstance(bricklink_data, dict):
        return None
    items = bricklink_data.get("items")
    if not isinstance(items, dict) or not items:
        return None
    primary = bricklink_data.get("primary_item_no")
    if primary and primary in items:
        return items[primary]
    return next(iter(items.values()))


def _nested(obj: Any, *path: str) -> Any:
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def price_section(part: dict[str, Any], section: str) -> dict[str, Any] | None:
    item = _bricklink_primary_item(part)
    guide = item.get("price_guide") if item else None
    return guide.get(section) if isinstance(guide, dict) else None


def bricklink_ids(part: dict[str, Any]) -> list[str]:
    ids = part.get("external_ids", {}).get("BrickLink", [])
    if isinstance(ids, dict):
        ids = ids.get("ext_ids", [])
    return [str(item) for item in ids if str(item).strip()] if isinstance(ids, list) else []


def bricklink_category_id(part: dict[str, Any]) -> int | None:
    value = _nested(_bricklink_primary_item(part), "catalog", "data", "category_id")
    return int(value) if value is not None else None


def read_field(field: str, part: dict[str, Any], categories: dict, bricklink_categories: dict) -> Any:
    """A part's value for a field (None when the catalog does not know it)."""
    if field == "name":
        return part.get("name") or ""
    if field == "part_num":
        return part.get("part_num") or ""
    if field == "category_id":
        return part.get("part_cat_id")
    if field == "category_name":
        category = categories.get(part.get("part_cat_id"))
        return category["name"] if category else ""
    if field == "year_from":
        return part.get("year_from")
    if field == "year_to":
        return part.get("year_to")
    if field == "bricklink_id":
        return bricklink_ids(part)
    bricklink_data = part.get("bricklink_data") if isinstance(part.get("bricklink_data"), dict) else None
    if field == "bricklink_item_count":
        items = bricklink_data.get("items") if bricklink_data else None
        return len(items) if isinstance(items, dict) else None
    if field == "bricklink_primary_item_no":
        return bricklink_data.get("primary_item_no") if bricklink_data else None

    # The unqualified price fields read the used sales of the last six months,
    # falling back to used stock for sale (what BrickStore shows).
    if field in ("bl_price_min", "bl_price_max", "bl_price_avg", "bl_price_qty_avg", "bl_price_lots", "bl_price_qty"):
        section = price_section(part, "ord_used") or price_section(part, "inv_used")
        if not section:
            return None
        metric = {
            "bl_price_min": "min",
            "bl_price_max": "max",
            "bl_price_avg": "avg",
            "bl_price_qty_avg": "wavg",
            "bl_price_lots": "lots",
            "bl_price_qty": "qty",
        }[field]
        return section.get(metric)
    for section_key in PRICE_SECTIONS:
        prefix = f"bl_price_{section_key}_"
        if field.startswith(prefix):
            section = price_section(part, section_key)
            return section.get(field[len(prefix):]) if section else None

    item = _bricklink_primary_item(part)
    if field == "bl_catalog_name":
        return _nested(item, "catalog", "data", "name")
    if field in ("bl_category_id", "bl_catalog_category_id"):
        return bricklink_category_id(part)
    if field == "bl_category_name":
        category = bricklink_categories.get(bricklink_category_id(part))
        return category.get("category_name", "") if isinstance(category, dict) else ""
    if field == "bl_catalog_year_released":
        return _nested(item, "catalog", "data", "year_released")
    if field == "bl_catalog_weight":
        return _to_float(_nested(item, "catalog", "data", "weight"))
    if field in ("bl_catalog_dim_x", "bl_catalog_dim_y", "bl_catalog_dim_z"):
        return _to_float(_nested(item, "catalog", "data", field.removeprefix("bl_catalog_")))
    if field == "bl_catalog_is_obsolete":
        value = _nested(item, "catalog", "data", "is_obsolete")
        return None if value is None else (1 if value else 0)
    return None
