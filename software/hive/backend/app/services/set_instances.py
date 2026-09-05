"""Set instances: one physical copy of a set and the parts found for it.

Progress rows are keyed by BrickLink part id and colour id, the same keys the
compiled profile artifact and the sorter's progress reports use, so a report
maps onto an instance without translation and the BrickLink wanted list is a
straight projection of the missing rows.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID
from xml.etree import ElementTree as ET

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.errors import APIError
from app.models.set_instance import SetInstance, SetInstanceProgress
from app.models.user import User
from app.services.machine_set_progress import upsert_progress_snapshot

ProgressKey = tuple[str, int]


def expand_set(catalog: Any, set_num: str, *, include_spares: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Set metadata plus BrickLink-keyed parts, or an APIError the client can act on."""
    try:
        set_info, parts = catalog.set_inventory_parts(set_num, include_spares=include_spares)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 502
        if status == 404:
            raise APIError(404, f"Set '{set_num}' not found on Rebrickable", "SET_NOT_FOUND") from exc
        raise APIError(502, "Rebrickable request failed", "SET_INVENTORY_UNAVAILABLE") from exc
    except requests.RequestException as exc:
        raise APIError(502, "Rebrickable request failed", "SET_INVENTORY_UNAVAILABLE") from exc
    if not set_info:
        raise APIError(404, f"Set '{set_num}' not found", "SET_NOT_FOUND")
    return set_info, parts


def _needed_by_key(parts: Iterable[dict[str, Any]]) -> dict[ProgressKey, int]:
    """Sum quantities per BrickLink key: several Rebrickable rows can map onto one BrickLink part."""
    needed: dict[ProgressKey, int] = {}
    for part in parts:
        key = (str(part["part_num"]), int(part["color_id"]))
        needed[key] = needed.get(key, 0) + int(part["quantity"])
    return needed


def create_instance(
    db: Session,
    user: User,
    catalog: Any,
    *,
    set_num: str,
    label: str | None,
    include_spares: bool,
    notes: str | None,
) -> SetInstance:
    set_info, parts = expand_set(catalog, set_num, include_spares=include_spares)
    instance = SetInstance(
        user_id=user.id,
        set_source="rebrickable",
        set_num=str(set_info.get("set_num") or set_num),
        label=(label or "").strip() or str(set_info.get("name") or set_num),
        include_spares=include_spares,
        notes=(notes or "").strip() or None,
    )
    instance.progress = [
        SetInstanceProgress(part_num=part_num, color_id=color_id, quantity_needed=quantity, quantity_found=0)
        for (part_num, color_id), quantity in _needed_by_key(parts).items()
    ]
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return instance


def list_instances(db: Session, user: User, *, include_archived: bool) -> list[SetInstance]:
    stmt = select(SetInstance).where(SetInstance.user_id == user.id).options(selectinload(SetInstance.progress))
    if not include_archived:
        stmt = stmt.where(SetInstance.status != "archived")
    return list(db.scalars(stmt.order_by(SetInstance.created_at.desc())))


def get_owned_instance(db: Session, user: User, instance_id: UUID) -> SetInstance:
    instance = db.get(SetInstance, instance_id)
    if instance is None or instance.user_id != user.id:
        raise APIError(404, "Set instance not found", "SET_INSTANCE_NOT_FOUND")
    return instance


def update_instance(db: Session, instance: SetInstance, *, label: str | None, notes: str | None, status: str | None) -> SetInstance:
    if label is not None:
        cleaned = label.strip()
        if not cleaned:
            raise APIError(400, "Label must not be empty", "SET_INSTANCE_LABEL_EMPTY")
        instance.label = cleaned
    if notes is not None:
        instance.notes = notes.strip() or None
    if status is not None:
        instance.status = status
    db.commit()
    db.refresh(instance)
    return instance


def archive_instance(db: Session, instance: SetInstance) -> SetInstance:
    instance.status = "archived"
    db.commit()
    db.refresh(instance)
    return instance


def _as_utc(value: datetime | None) -> datetime | None:
    # sqlite hands back naive timestamps; a row touched in this session holds an aware one.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def progress_totals(rows: Iterable[SetInstanceProgress]) -> dict[str, Any]:
    needed = found = 0
    updated_at: datetime | None = None
    count = 0
    for row in rows:
        count += 1
        needed += row.quantity_needed
        found += row.quantity_found
        row_updated_at = _as_utc(row.updated_at)
        if row_updated_at is not None and (updated_at is None or row_updated_at > updated_at):
            updated_at = row_updated_at
    return {
        "part_count": count,
        "total_needed": needed,
        "total_found": found,
        "pct": round(found / needed * 100, 1) if needed else 0.0,
        "updated_at": updated_at,
    }


def _refresh_status(instance: SetInstance) -> None:
    """open <-> complete follows the counts; archived is the user's call and stays."""
    if instance.status == "archived":
        return
    totals = progress_totals(instance.progress)
    complete = totals["total_needed"] > 0 and totals["total_found"] >= totals["total_needed"]
    instance.status = "complete" if complete else "open"


def set_part_found(db: Session, instance: SetInstance, *, part_num: str, color_id: int, quantity_found: int) -> SetInstanceProgress:
    row = next((r for r in instance.progress if r.part_num == part_num and r.color_id == color_id), None)
    if row is None:
        raise APIError(404, "Part is not in this set instance", "SET_INSTANCE_PART_UNKNOWN")
    row.quantity_found = max(0, min(int(quantity_found), row.quantity_needed))
    row.updated_at = datetime.now(timezone.utc)
    _refresh_status(instance)
    db.commit()
    db.refresh(row)
    return row


def apply_machine_progress(
    db: Session,
    instance: SetInstance,
    items: Iterable[dict[str, Any]],
    *,
    now: datetime,
) -> int:
    """Absolute quantity_found values from a machine report; unknown parts are rejected.

    The caller owns the transaction (the sync endpoint writes several
    instances and the legacy table in one commit).
    """
    needed_by_key = {
        (row.part_num, row.color_id): row.quantity_needed
        for row in db.scalars(select(SetInstanceProgress).where(SetInstanceProgress.set_instance_id == instance.id))
    }
    rows: list[dict[str, Any]] = []
    for item in items:
        key = (item["part_num"], item["color_id"])
        needed = needed_by_key.get(key)
        if needed is None:
            raise APIError(
                400,
                f"Progress item {item['part_num']}/{item['color_id']} is not part of set instance {instance.id}",
                "SET_PROGRESS_ITEM_UNKNOWN",
            )
        rows.append(
            {
                "set_instance_id": instance.id,
                "part_num": item["part_num"],
                "color_id": item["color_id"],
                "quantity_needed": needed,
                "quantity_found": max(0, min(int(item["quantity_found"]), needed)),
                "updated_at": now,
            }
        )
    upsert_progress_snapshot(
        db,
        SetInstanceProgress.__table__,
        rows,
        conflict_columns=("set_instance_id", "part_num", "color_id"),
    )
    db.expire(instance, ["progress"])
    _refresh_status(instance)
    return len(rows)


def part_details(catalog: Any, instance: SetInstance) -> list[dict[str, Any]]:
    """Progress rows joined with catalog names/images; unresolvable parts keep bare ids."""
    try:
        _, parts = catalog.set_inventory_parts(instance.set_num, include_spares=instance.include_spares)
    except requests.RequestException:
        parts = []
    meta_by_key = {(str(p["part_num"]), int(p["color_id"])): p for p in parts}
    details = []
    for row in instance.progress:
        meta = meta_by_key.get((row.part_num, row.color_id), {})
        details.append(
            {
                "part_num": row.part_num,
                "color_id": row.color_id,
                "part_name": meta.get("part_name"),
                "color_name": meta.get("color_name"),
                "img_url": meta.get("img_url"),
                "quantity_needed": row.quantity_needed,
                "quantity_found": row.quantity_found,
                "quantity_missing": max(0, row.quantity_needed - row.quantity_found),
                "updated_at": row.updated_at,
            }
        )
    return details


def missing_parts(parts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [part for part in parts if part["quantity_missing"] > 0]


def wanted_list_xml(parts: Iterable[dict[str, Any]]) -> str:
    """BrickLink wanted-list upload format: one ITEM per missing part/colour."""
    inventory = ET.Element("INVENTORY")
    for part in parts:
        item = ET.SubElement(inventory, "ITEM")
        ET.SubElement(item, "ITEMTYPE").text = "P"
        ET.SubElement(item, "ITEMID").text = part["part_num"]
        ET.SubElement(item, "COLOR").text = str(part["color_id"])
        ET.SubElement(item, "MINQTY").text = str(part["quantity_missing"])
        ET.SubElement(item, "NOTIFY").text = "N"
    return ET.tostring(inventory, encoding="unicode", xml_declaration=False)
