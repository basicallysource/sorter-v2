from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, NamedTuple
from uuid import UUID, uuid4

from sqlalchemy import Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.machine_profile_assignment import MachineProfileAssignment
from app.models.machine_set_progress import MachineSetProgress
from app.models.set_instance import SetInstance, SetInstanceProgress


def upsert_progress_snapshot(
    db: Session,
    table: Table,
    rows: list[dict[str, Any]],
    *,
    conflict_columns: tuple[str, ...],
) -> None:
    """Chunked INSERT ... ON CONFLICT DO UPDATE for progress rows, no-op when nothing changed.

    Every row must carry quantity_needed, quantity_found and updated_at; ids
    are minted here. The WHERE keeps a re-reported identical snapshot from
    touching updated_at or leaving dead tuples behind; the chunking keeps a
    full-set snapshot (~8.5k rows x 9 columns) under both postgres's and
    sqlite's bind-parameter caps.
    """
    insert_fn = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    for start in range(0, len(rows), 1000):
        stmt = insert_fn(table).values([{"id": uuid4(), **row} for row in rows[start : start + 1000]])
        stmt = stmt.on_conflict_do_update(
            index_elements=list(conflict_columns),
            set_={
                "quantity_needed": stmt.excluded.quantity_needed,
                "quantity_found": stmt.excluded.quantity_found,
                "updated_at": stmt.excluded.updated_at,
            },
            where=(
                (table.c.quantity_needed != stmt.excluded.quantity_needed)
                | (table.c.quantity_found != stmt.excluded.quantity_found)
            ),
        )
        db.execute(stmt)


class ProgressRow(NamedTuple):
    set_num: str
    part_num: str
    color_id: int
    quantity_needed: int
    quantity_found: int
    updated_at: datetime | None


def instance_bound_sets(compiled_artifact: dict[str, Any] | None) -> dict[str, UUID]:
    """set_num -> set_instance_id for every set rule in the artifact that names an instance."""
    bound: dict[str, UUID] = {}
    stack = list(compiled_artifact.get("rules") or []) if isinstance(compiled_artifact, dict) else []
    while stack:
        rule = stack.pop()
        if not isinstance(rule, dict):
            continue
        stack.extend(rule.get("children") or [])
        if rule.get("rule_type") != "set" or not rule.get("set_num") or not rule.get("set_instance_id"):
            continue
        try:
            bound[str(rule["set_num"])] = UUID(str(rule["set_instance_id"]))
        except ValueError:
            continue
    return bound


def load_assignment_progress_rows(
    db: Session,
    assignment: MachineProfileAssignment,
    compiled_artifact: dict[str, Any] | None,
) -> list[Any]:
    """Progress rows for an assignment: the legacy assignment-keyed ones, then the rows of every
    set instance the artifact binds (owned by the machine's owner), which win on overlap."""
    rows: list[Any] = list(db.scalars(select(MachineSetProgress).where(MachineSetProgress.assignment_id == assignment.id)))
    for set_num, instance_id in instance_bound_sets(compiled_artifact).items():
        instance = db.get(SetInstance, instance_id)
        if instance is None or instance.user_id != assignment.machine.owner_id:
            continue
        rows.extend(
            ProgressRow(set_num, row.part_num, row.color_id, row.quantity_needed, row.quantity_found, row.updated_at)
            for row in db.scalars(select(SetInstanceProgress).where(SetInstanceProgress.set_instance_id == instance.id))
        )
    return rows


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _iter_set_inventory_groups(compiled_artifact: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(compiled_artifact, dict):
        return []
    raw_inventories = compiled_artifact.get("set_inventories")
    if not isinstance(raw_inventories, dict):
        return []

    groups: list[dict[str, Any]] = []
    for raw_key, raw_value in raw_inventories.items():
        if isinstance(raw_value, dict):
            raw_parts = raw_value.get("parts")
            parts = raw_parts if isinstance(raw_parts, list) else []
            set_num = str(raw_value.get("set_num") or raw_key).removeprefix("set_")
            name = str(raw_value.get("name") or set_num)
            groups.append({"set_num": set_num, "name": name, "parts": parts})
            continue

        if isinstance(raw_value, list):
            set_num = str(raw_key).removeprefix("set_")
            groups.append({"set_num": set_num, "name": set_num, "parts": raw_value})

    return groups


def build_set_progress_inventory_index(
    compiled_artifact: dict[str, Any] | None,
) -> dict[tuple[str, str, int], dict[str, Any]]:
    part_items: dict[tuple[str, str, int], dict[str, Any]] = {}

    for group in _iter_set_inventory_groups(compiled_artifact):
        set_num = group["set_num"]
        set_name = group["name"]
        for raw_part in group["parts"]:
            if not isinstance(raw_part, dict):
                continue
            part_num = str(raw_part.get("part_num") or "")
            color_id = _safe_int(raw_part.get("color_id"))
            quantity = _safe_int(raw_part.get("quantity")) or 0
            if not part_num or color_id is None or quantity <= 0:
                continue

            key = (set_num, part_num, color_id)
            item = part_items.setdefault(
                key,
                {
                    "set_num": set_num,
                    "set_name": set_name,
                    "part_num": part_num,
                    "color_id": color_id,
                    "part_name": raw_part.get("part_name"),
                    "color_name": raw_part.get("color_name"),
                    "quantity_needed": 0,
                },
            )
            item["quantity_needed"] += quantity

    return part_items


def summarize_machine_set_progress(
    compiled_artifact: dict[str, Any] | None,
    rows: Iterable[Any],
    *,
    include_unknown_rows: bool = False,
) -> dict[str, Any]:
    base_items = build_set_progress_inventory_index(compiled_artifact)
    part_items: dict[tuple[str, str, int], dict[str, Any]] = {
        key: {
            **value,
            "quantity_found": 0,
            "updated_at": None,
        }
        for key, value in base_items.items()
    }

    latest_updated_at: datetime | None = None
    for row in rows:
        set_num = str(getattr(row, "set_num", "") or "")
        part_num = str(getattr(row, "part_num", "") or "")
        color_id = _safe_int(getattr(row, "color_id", None))
        quantity_needed = _safe_int(getattr(row, "quantity_needed", None)) or 0
        quantity_found = _safe_int(getattr(row, "quantity_found", None)) or 0
        updated_at = getattr(row, "updated_at", None)
        if not set_num or not part_num or color_id is None:
            continue

        key = (set_num, part_num, color_id)
        item = part_items.get(key)
        if item is None:
            if not include_unknown_rows:
                continue
            item = {
                "set_num": set_num,
                "set_name": set_num,
                "part_num": part_num,
                "color_id": color_id,
                "part_name": None,
                "color_name": None,
                "quantity_needed": max(0, quantity_needed),
                "quantity_found": 0,
                "updated_at": None,
            }
            part_items[key] = item

        item["quantity_found"] = max(0, min(quantity_found, item["quantity_needed"]))
        item["updated_at"] = updated_at

        if isinstance(updated_at, datetime):
            latest_updated_at = updated_at if latest_updated_at is None else max(latest_updated_at, updated_at)

    progress = sorted(
        part_items.values(),
        key=lambda item: (item["set_num"], item["part_num"], item["color_id"]),
    )

    set_summaries: dict[str, dict[str, Any]] = {}
    overall_needed = 0
    overall_found = 0
    for item in progress:
        overall_needed += item["quantity_needed"]
        overall_found += item["quantity_found"]
        summary = set_summaries.setdefault(
            item["set_num"],
            {
                "set_num": item["set_num"],
                "name": item["set_name"],
                "total_needed": 0,
                "total_found": 0,
                "updated_at": None,
            },
        )
        summary["total_needed"] += item["quantity_needed"]
        summary["total_found"] += item["quantity_found"]
        item_updated_at = item["updated_at"]
        if isinstance(item_updated_at, datetime):
            current_updated_at = summary["updated_at"]
            summary["updated_at"] = item_updated_at if current_updated_at is None else max(current_updated_at, item_updated_at)

    sets = []
    for summary in sorted(set_summaries.values(), key=lambda item: item["set_num"]):
        needed = summary["total_needed"]
        found = summary["total_found"]
        pct = (found / needed * 100) if needed > 0 else 0.0
        sets.append(
            {
                **summary,
                "pct": round(pct, 1),
            }
        )

    overall_pct = (overall_found / overall_needed * 100) if overall_needed > 0 else 0.0
    return {
        "progress": progress,
        "sets": sets,
        "overall_needed": overall_needed,
        "overall_found": overall_found,
        "overall_pct": round(overall_pct, 1),
        "updated_at": latest_updated_at,
    }
