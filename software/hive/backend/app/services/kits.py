"""Kits: parts in colors with quantities, for a profile's kit rules to collect.

A kit's lines are stored in the catalog's own terms (Rebrickable part and
color IDs) whenever the catalog knows the part, so they read the same however
they came in: typed by a person, sent by an assistant with BrickLink IDs,
imported from a LEGO set or a BrickLink wanted list.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.errors import APIError
from app.models.kit import Kit
from app.models.sorting_profile import SortingProfile
from app.models.sorting_profile_version import SortingProfileVersion
from app.models.user import User
from app.services.profile_catalog import CUSTOM_SET_ANY_COLOR_ID, ProfileCatalogService
from app.services.profile_engine.compiler import colored_picture
from app.services.profile_engine.fields import bricklink_ids

VISIBILITIES = ("private", "unlisted", "public")


def normalize_visibility(value: str | None) -> str:
    normalized = (value or "private").strip().lower()
    if normalized not in VISIBILITIES:
        raise APIError(400, "Visibility must be private, unlisted, or public", "KIT_VISIBILITY_INVALID")
    return normalized


def resolve_lines(catalog: ProfileCatalogService, lines: list[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Kit lines as stored, from what a request gave: each part and color looked
    up in the catalog, repeated lines merged. Raises one APIError naming every
    line the catalog does not know."""
    index = catalog.index()
    merged: dict[tuple[str, int], dict[str, Any]] = {}
    errors: list[str] = []
    for number, line in enumerate(lines, start=1):
        raw_part = str(line.part).strip()
        summary = catalog.part_summary(raw_part)
        if summary is None:
            errors.append(f"Line {number}: no part {raw_part!r} in the catalog (search /api/profile-catalog/search-parts)")
            continue
        part_num = summary["part_num"]
        if line.color_id is not None and line.bricklink_color_id is not None:
            errors.append(f"Line {number}: give color_id or bricklink_color_id, not both")
            continue
        color_id = CUSTOM_SET_ANY_COLOR_ID
        if line.color_id is not None:
            if line.color_id not in index.colors:
                errors.append(f"Line {number}: no Rebrickable color {line.color_id} (list them at /api/profile-catalog/colors)")
                continue
            color_id = line.color_id
        elif line.bricklink_color_id is not None:
            color = index.bl_colors.get(str(line.bricklink_color_id))
            if color is None:
                errors.append(f"Line {number}: no BrickLink color {line.bricklink_color_id} (list them at /api/profile-catalog/colors)")
                continue
            color_id = int(color["rb_id"])
        key = (part_num, color_id)
        entry = merged.get(key)
        if entry is None:
            color = index.colors.get(color_id) if color_id != CUSTOM_SET_ANY_COLOR_ID else None
            entry = {
                "part_num": part_num,
                "part_source": "rebrickable",
                "color_id": color_id,
                "quantity": 0,
                "part_name": summary.get("name"),
                "color_name": color.get("name") if color else "Any color",
                "img_url": summary.get("part_img_url"),
            }
            merged[key] = entry
        entry["quantity"] += int(line.quantity)
    if errors:
        raise APIError(400, f"{len(errors)} kit line(s) could not be read", "KIT_LINES_INVALID", details=errors)
    parts = list(merged.values())
    return parts, line_warnings(parts)


def line_warnings(parts: list[dict[str, Any]]) -> list[str]:
    any_color = sum(1 for part in parts if part.get("color_id") in (None, CUSTOM_SET_ANY_COLOR_ID))
    warnings = []
    if any_color:
        warnings.append(
            f"{any_color} line(s) have no color, so a piece of any color counts toward them. Give each a color to collect exact pieces."
        )
    unknown = sum(1 for part in parts if part.get("part_source") == "bricklink")
    if unknown:
        warnings.append(f"{unknown} line(s) are BrickLink parts the catalog does not know; they are collected by their BrickLink ID.")
    return warnings


def lines_from_set(catalog: ProfileCatalogService, set_num: str, include_spares: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A LEGO set's inventory as kit lines, and the set's own details."""
    result = catalog.get_set_inventory(set_num)
    merged: dict[tuple[str, int], dict[str, Any]] = {}
    for item in result["inventory"]:
        if item.get("is_spare") and not include_spares:
            continue
        part_num = str(item.get("part_num") or "").strip()
        if not part_num:
            continue
        color_id = int(item.get("color_id")) if item.get("color_id") is not None else CUSTOM_SET_ANY_COLOR_ID
        key = (part_num, color_id)
        entry = merged.setdefault(
            key,
            {
                "part_num": part_num,
                "part_source": "rebrickable",
                "color_id": color_id,
                "quantity": 0,
                "part_name": item.get("part_name"),
                "color_name": item.get("color_name"),
                "img_url": item.get("part_img_url"),
            },
        )
        entry["quantity"] += int(item.get("quantity") or 0)
    return result["set"], [entry for entry in merged.values() if entry["quantity"] > 0]


def kit_as_dict(kit: Kit) -> dict[str, Any]:
    return {
        "id": str(kit.id),
        "name": kit.name,
        "image_url": kit.image_url,
        "set_num": kit.set_num,
        "set_meta": kit.set_meta,
        "include_spares": kit.include_spares,
        "parts": kit.parts or [],
    }


def can_use(kit: Kit, user_id: UUID) -> bool:
    return kit.owner_id == user_id or kit.visibility in ("public", "unlisted")


def kits_for_rules(db: Session, owner_id: UUID, rules: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The kits a document's kit rules name that its owner may use, by ID."""
    wanted: set[UUID] = set()
    for rule in rules:
        if isinstance(rule, dict) and rule.get("rule_type") == "kit" and rule.get("kit_id"):
            try:
                wanted.add(UUID(str(rule["kit_id"])))
            except ValueError:
                continue
    if not wanted:
        return {}
    kits = db.query(Kit).filter(Kit.id.in_(wanted)).all()
    return {str(kit.id): kit_as_dict(kit) for kit in kits if can_use(kit, owner_id)}


def missing_kits(rules: list[dict[str, Any]], kits: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"rule_id": rule.get("id"), "message": f"Kit {rule.get('kit_id')!r} does not exist or is not yours to use."}
        for rule in rules
        if isinstance(rule, dict) and rule.get("rule_type") == "kit" and not rule.get("disabled") and str(rule.get("kit_id")) not in kits
    ]


def kits_from_set_rules(
    db: Session,
    catalog: ProfileCatalogService,
    owner: User,
    rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rules with each set rule from before kits (a set or a custom parts list
    held inside the rule) made into a kit of its own and a kit rule naming it.
    The rule keeps its ID, so bins assigned to it stay assigned."""
    out = []
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("rule_type") != "set":
            out.append(rule)
            continue
        custom = str(rule.get("set_source") or ("custom" if rule.get("custom_parts") else "rebrickable")) == "custom"
        set_meta = rule.get("set_meta") if isinstance(rule.get("set_meta"), dict) else None
        if custom:
            parts = [
                {
                    "part_num": str(part.get("part_num") or ""),
                    "part_source": str(part.get("part_source") or "rebrickable"),
                    "color_id": part.get("color_id", CUSTOM_SET_ANY_COLOR_ID),
                    "quantity": int(part.get("quantity") or 1),
                    "part_name": part.get("part_name"),
                    "color_name": part.get("color_name"),
                    "img_url": part.get("img_url"),
                }
                for part in rule.get("custom_parts") or []
                if isinstance(part, dict) and part.get("part_num")
            ]
            source, set_num = "custom", None
        else:
            set_num = str(rule.get("set_num") or "").strip()
            if not set_num:
                out.append(rule)
                continue
            details, parts = lines_from_set(catalog, set_num, bool(rule.get("include_spares")))
            set_meta = {**details, **(set_meta or {})}
            source = "set"
        kit = Kit(
            id=uuid.uuid4(),
            owner_id=owner.id,
            name=str(rule.get("name") or (set_meta or {}).get("name") or "Kit"),
            source=source,
            set_num=set_num,
            set_meta=set_meta,
            include_spares=bool(rule.get("include_spares")),
            image_url=(set_meta or {}).get("img_url"),
            visibility="private",
            parts=parts,
        )
        db.add(kit)
        db.flush()
        out.append(
            {
                "id": rule.get("id"),
                "rule_type": "kit",
                "kit_id": str(kit.id),
                "name": kit.name,
                "disabled": bool(rule.get("disabled")),
                "image_url": rule.get("image_url"),
            }
        )
    return out


def describe_lines(catalog: ProfileCatalogService, parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index = catalog.index()
    out = []
    for part in parts:
        color_id = part.get("color_id")
        any_color = color_id in (None, CUSTOM_SET_ANY_COLOR_ID)
        bricklink_source = part.get("part_source") == "bricklink"
        color = None if any_color or bricklink_source else index.colors.get(int(color_id))
        row = index.row_of.get(str(part.get("part_num"))) if not bricklink_source else None
        catalog_part = index.part(row) if row is not None else None
        out.append(
            {
                "part_num": str(part.get("part_num")),
                "part_source": part.get("part_source") or "rebrickable",
                "bricklink_id": (bricklink_ids(catalog_part) or [None])[0] if catalog_part else (str(part.get("part_num")) if bricklink_source else None),
                "part_name": part.get("part_name") or (catalog_part or {}).get("name"),
                # The part in the line's color when Rebrickable renders it, else its photo.
                "img_url": (
                    None if any_color or bricklink_source else colored_picture(str(part.get("part_num")), int(color_id))
                )
                or part.get("img_url")
                or (catalog_part or {}).get("part_img_url"),
                "fallback_img_url": (
                    part.get("img_url") or (catalog_part or {}).get("part_img_url")
                    if not (any_color or bricklink_source)
                    else None
                ),
                "color_id": None if any_color or bricklink_source else int(color_id),
                "bricklink_color_id": (
                    None
                    if any_color
                    else int(color_id)
                    if bricklink_source
                    else int(index.bl_color(int(color_id)))
                    if index.bl_color(int(color_id)).lstrip("-").isdigit()
                    else None
                ),
                "color_name": "Any color" if any_color else (color or {}).get("name") or part.get("color_name"),
                "rgb": (color or {}).get("rgb"),
                "quantity": int(part.get("quantity") or 0),
            }
        )
    return out


def profiles_using(db: Session, kit: Kit) -> list[dict[str, Any]]:
    """The kit owner's profiles whose latest version has a kit rule for it.
    Reads only the rules of each latest version, never a compiled artifact."""
    rows = (
        db.query(SortingProfile.id, SortingProfile.name, SortingProfileVersion.version_number, SortingProfileVersion.rules_json)
        .join(SortingProfileVersion, SortingProfileVersion.profile_id == SortingProfile.id)
        .filter(
            SortingProfile.owner_id == kit.owner_id,
            SortingProfileVersion.version_number == SortingProfile.latest_version_number,
        )
        .all()
    )
    needle = str(kit.id)
    return [
        {"profile_id": str(profile_id), "name": name, "version_number": version_number}
        for profile_id, name, version_number, rules in rows
        if any(isinstance(rule, dict) and str(rule.get("kit_id")) == needle for rule in rules or [])
    ]
