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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import APIError
from app.models.set_instance import SetInstance, SetInstanceMachineCount, SetInstanceProgress
from app.models.user import User

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
        if not catalog.rebrickable_configured:
            raise APIError(503, "Rebrickable is not configured on this server (REBRICKABLE_API_KEY)", "REBRICKABLE_NOT_CONFIGURED")
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


def list_instances(db: Session, user: User, *, include_archived: bool) -> list[tuple[SetInstance, dict[str, Any]]]:
    """Instances with their progress totals, aggregated in SQL: one row per instance, not per part."""
    totals = (
        select(
            SetInstanceProgress.set_instance_id.label("instance_id"),
            func.count().label("part_count"),
            func.sum(SetInstanceProgress.quantity_needed).label("total_needed"),
            func.sum(SetInstanceProgress.quantity_found).label("total_found"),
            func.max(SetInstanceProgress.updated_at).label("updated_at"),
        )
        .group_by(SetInstanceProgress.set_instance_id)
        .subquery()
    )
    stmt = (
        select(SetInstance, totals.c.part_count, totals.c.total_needed, totals.c.total_found, totals.c.updated_at)
        .outerjoin(totals, totals.c.instance_id == SetInstance.id)
        .where(SetInstance.user_id == user.id)
        .order_by(SetInstance.created_at.desc())
    )
    if not include_archived:
        stmt = stmt.where(SetInstance.status != "archived")
    return [
        (instance, _totals(part_count or 0, needed or 0, found or 0, _as_utc(updated_at)))
        for instance, part_count, needed, found, updated_at in db.execute(stmt)
    ]


def get_owned_instance(db: Session, user: User, instance_id: UUID) -> SetInstance:
    instance = db.get(SetInstance, instance_id)
    if instance is None or instance.user_id != user.id:
        raise APIError(404, "Set instance not found", "SET_INSTANCE_NOT_FOUND")
    return instance


def update_instance(db: Session, instance: SetInstance, *, label: str | None, notes: str | None) -> SetInstance:
    """Label and notes only; open/complete follow the counts and archived has its own endpoints."""
    if label is not None:
        cleaned = label.strip()
        if not cleaned:
            raise APIError(400, "Label must not be empty", "SET_INSTANCE_LABEL_EMPTY")
        instance.label = cleaned
    if notes is not None:
        instance.notes = notes.strip() or None
    db.commit()
    db.refresh(instance)
    return instance


def archive_instance(db: Session, instance: SetInstance) -> SetInstance:
    instance.status = "archived"
    db.commit()
    db.refresh(instance)
    return instance


def restore_instance(db: Session, instance: SetInstance) -> SetInstance:
    """Back from archived to whatever the counts say."""
    instance.status = "open"
    _refresh_status(instance)
    db.commit()
    db.refresh(instance)
    return instance


def _as_utc(value: datetime | None) -> datetime | None:
    # sqlite hands back naive timestamps; a row touched in this session holds an aware one.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _totals(part_count: int, needed: int, found: int, updated_at: datetime | None) -> dict[str, Any]:
    return {
        "part_count": part_count,
        "total_needed": needed,
        "total_found": found,
        "pct": round(found / needed * 100, 1) if needed else 0.0,
        "updated_at": updated_at,
    }


def progress_totals(rows: Iterable[SetInstanceProgress]) -> dict[str, Any]:
    """Totals over already loaded rows (detail views); list_instances aggregates in SQL instead."""
    needed = found = count = 0
    updated_at: datetime | None = None
    for row in rows:
        count += 1
        needed += row.quantity_needed
        found += row.quantity_found
        row_updated_at = _as_utc(row.updated_at)
        if row_updated_at is not None and (updated_at is None or row_updated_at > updated_at):
            updated_at = row_updated_at
    return _totals(count, needed, found, updated_at)


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
    machine_id: UUID,
    items: Iterable[dict[str, Any]],
    *,
    now: datetime,
) -> int:
    """Merge a machine's report into the instance; unknown parts are rejected.

    A sorter counts from zero per tracker session (it starts over after a
    profile edit or a reset) and reports absolute counts. The instance keeps
    the count each machine last reported per part and adds only the difference,
    so manual adjustments, other machines' contributions and a machine that
    restarted at zero all survive. A count below the previous one means the
    machine restarted: the whole new count is its contribution. The caller
    owns the transaction (the sync endpoint writes several instances and the
    legacy table in one commit).
    """
    rows_by_key = {(row.part_num, row.color_id): row for row in instance.progress}
    counts_by_key = {
        (count.part_num, count.color_id): count
        for count in db.scalars(
            select(SetInstanceMachineCount).where(
                SetInstanceMachineCount.set_instance_id == instance.id,
                SetInstanceMachineCount.machine_id == machine_id,
            )
        )
    }
    applied = 0
    for item in items:
        key = (item["part_num"], item["color_id"])
        row = rows_by_key.get(key)
        if row is None:
            raise APIError(
                400,
                f"Progress item {item['part_num']}/{item['color_id']} is not part of set instance {instance.id}",
                "SET_PROGRESS_ITEM_UNKNOWN",
            )
        reported = max(0, int(item["quantity_found"]))
        count = counts_by_key.get(key)
        previous = count.quantity_reported if count is not None else 0
        delta = reported - previous if reported >= previous else reported
        if delta:
            row.quantity_found = max(0, min(row.quantity_found + delta, row.quantity_needed))
            row.updated_at = now
        if count is None:
            db.add(
                SetInstanceMachineCount(
                    set_instance_id=instance.id,
                    machine_id=machine_id,
                    part_num=row.part_num,
                    color_id=row.color_id,
                    quantity_reported=reported,
                    updated_at=now,
                )
            )
        elif count.quantity_reported != reported:
            count.quantity_reported = reported
            count.updated_at = now
        applied += 1
    _refresh_status(instance)
    return applied


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
