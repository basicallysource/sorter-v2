from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from types import SimpleNamespace
from typing import Any

from app.config import settings
from app.errors import APIError
from app.services.profile_builder_compat import (
    builder_db,
    builder_parts_cache,
    builder_rule_engine,
    builder_sorting_profile,
)
from app.services.set_inventory import get_cached_inventory, get_cached_set, fetch_set_inventory, search_sets as _search_sets

CUSTOM_SET_ANY_COLOR_ID = -1
PROFILE_CATALOG_SYNC_TYPES = ("categories", "colors", "parts", "brickstore", "prices")
PROFILE_CATALOG_AUTO_SYNC_TYPES = ("categories", "colors", "parts")
PROFILE_CATALOG_LAST_SYNC_META_PREFIX = "profile_catalog.last_sync."


def _ensure_parent_dir(path: str) -> None:
    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


@dataclass
class CatalogConfig:
    rebrickable_api_key: str
    bl_affiliate_api_key: str
    db_path: str
    brickstore_db_path: str


class ProfileCatalogService:
    def __init__(self) -> None:
        db_path = os.path.expanduser(settings.SORTING_PROFILE_PARTS_DB_PATH)
        _ensure_parent_dir(db_path)
        self._config = CatalogConfig(
            rebrickable_api_key=settings.REBRICKABLE_API_KEY,
            bl_affiliate_api_key=settings.BL_AFFILIATE_API_KEY,
            db_path=db_path,
            brickstore_db_path=os.path.expanduser(settings.SORTING_PROFILE_BRICKSTORE_DB_PATH),
        )
        self._lock = Lock()
        self._conn = builder_db.initDb(self._config.db_path)
        self._parts_data = builder_db.PartsData()
        builder_db.reloadPartsData(self._conn, self._parts_data)
        self._sync = builder_parts_cache.SyncManager()
        self._auto_sync_state_lock = Lock()
        self._auto_sync_stop_event = Event()
        self._auto_sync_loop_thread: Thread | None = None
        self._auto_sync_job_thread: Thread | None = None
        self._auto_sync_running = False
        self._auto_sync_plan: list[str] = []
        self._auto_sync_last_checked_at: str | None = None
        self._auto_sync_last_started_at: str | None = None

    @property
    def parts_data(self):
        return self._parts_data

    @property
    def auto_sync_enabled(self) -> bool:
        return bool(settings.PROFILE_CATALOG_AUTO_SYNC_ENABLED and self._config.rebrickable_api_key)

    def status(self) -> dict[str, Any]:
        status = self._sync.getStatus(self._parts_data)
        with self._auto_sync_state_lock:
            status["auto_sync_enabled"] = self.auto_sync_enabled
            status["auto_sync_running"] = self._auto_sync_running
            status["auto_sync_loop_running"] = bool(self._auto_sync_loop_thread and self._auto_sync_loop_thread.is_alive())
            status["auto_sync_plan"] = list(self._auto_sync_plan)
            status["auto_sync_last_checked_at"] = self._auto_sync_last_checked_at
            status["auto_sync_last_started_at"] = self._auto_sync_last_started_at
        status["last_synced_at"] = self.get_last_synced_at_map()
        return status

    def start_sync(self, sync_type: str) -> bool:
        with self._lock:
            if sync_type == "categories":
                return self._sync.startCategoriesSync(
                    self._config,
                    self._conn,
                    self._parts_data,
                    on_complete=lambda: self._mark_sync_completed(sync_type),
                )
            if sync_type == "colors":
                return self._sync.startColorsSync(
                    self._config,
                    self._conn,
                    self._parts_data,
                    on_complete=lambda: self._mark_sync_completed(sync_type),
                )
            if sync_type == "parts":
                return self._sync.startPartsSync(
                    self._config,
                    self._conn,
                    self._parts_data,
                    on_complete=lambda: self._mark_sync_completed(sync_type),
                )
            if sync_type == "brickstore":
                return self._sync.startBrickstoreImport(
                    self._config,
                    self._conn,
                    self._parts_data,
                    on_complete=lambda: self._mark_sync_completed(sync_type),
                )
            if sync_type == "prices":
                return self._sync.startPriceSync(
                    self._config,
                    self._conn,
                    self._parts_data,
                    on_complete=lambda: self._mark_sync_completed(sync_type),
                )
        raise ValueError(f"Unsupported sync_type '{sync_type}'")

    def stop_sync(self) -> None:
        self._sync.requestStop()

    def start_auto_sync_loop(self) -> bool:
        if not self.auto_sync_enabled:
            return False
        with self._auto_sync_state_lock:
            if self._auto_sync_loop_thread and self._auto_sync_loop_thread.is_alive():
                return False
            self._auto_sync_stop_event.clear()
            self._auto_sync_loop_thread = Thread(target=self._auto_sync_loop, daemon=True)
            self._auto_sync_loop_thread.start()
            return True

    def stop_auto_sync_loop(self) -> None:
        self._auto_sync_stop_event.set()
        with self._auto_sync_state_lock:
            loop_thread = self._auto_sync_loop_thread
            job_thread = self._auto_sync_job_thread
        if loop_thread and loop_thread.is_alive():
            loop_thread.join(timeout=1.0)
        if job_thread and job_thread.is_alive():
            self._sync.requestStop()
            job_thread.join(timeout=1.0)

    def start_auto_sync_if_needed(self) -> bool:
        plan = self.get_auto_sync_plan()
        if not plan:
            return False
        with self._auto_sync_state_lock:
            if self._auto_sync_running:
                return False
            self._auto_sync_running = True
            self._auto_sync_plan = list(plan)
            self._auto_sync_last_started_at = datetime.now(timezone.utc).isoformat()
            self._auto_sync_job_thread = Thread(target=self._run_auto_sync_plan, args=(plan,), daemon=True)
            self._auto_sync_job_thread.start()
            return True

    def get_auto_sync_plan(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(timezone.utc)
        with self._auto_sync_state_lock:
            self._auto_sync_last_checked_at = now.isoformat()
            if self._auto_sync_running:
                return []
        if not self.auto_sync_enabled:
            return []
        sync_status = self._sync.getStatus(self._parts_data)
        if sync_status.get("running"):
            return []

        plan: list[str] = []
        counts = {
            "categories": len(self._parts_data.categories),
            "colors": len(self._parts_data.colors),
            "parts": len(self._parts_data.parts),
        }
        max_age_hours = {
            "categories": settings.PROFILE_CATALOG_AUTO_SYNC_CATEGORIES_MAX_AGE_HOURS,
            "colors": settings.PROFILE_CATALOG_AUTO_SYNC_COLORS_MAX_AGE_HOURS,
            "parts": settings.PROFILE_CATALOG_AUTO_SYNC_PARTS_MAX_AGE_HOURS,
        }

        for sync_type in PROFILE_CATALOG_AUTO_SYNC_TYPES:
            if counts[sync_type] <= 0:
                plan.append(sync_type)
                continue
            if self._is_sync_stale(sync_type, max_age_hours[sync_type], now):
                plan.append(sync_type)
        return plan

    def get_last_synced_at(self, sync_type: str) -> str | None:
        if sync_type not in PROFILE_CATALOG_SYNC_TYPES:
            raise ValueError(f"Unsupported sync_type '{sync_type}'")
        raw = builder_db.getMeta(self._conn, self._sync_meta_key(sync_type))
        return str(raw) if raw else None

    def get_last_synced_at_map(self) -> dict[str, str | None]:
        return {sync_type: self.get_last_synced_at(sync_type) for sync_type in PROFILE_CATALOG_SYNC_TYPES}

    def _auto_sync_loop(self) -> None:
        check_interval = max(1, int(settings.PROFILE_CATALOG_AUTO_SYNC_CHECK_INTERVAL_MINUTES)) * 60
        try:
            while not self._auto_sync_stop_event.is_set():
                self.start_auto_sync_if_needed()
                self._auto_sync_stop_event.wait(check_interval)
        finally:
            with self._auto_sync_state_lock:
                self._auto_sync_loop_thread = None

    def _run_auto_sync_plan(self, plan: list[str]) -> None:
        try:
            for index, sync_type in enumerate(plan):
                if self._auto_sync_stop_event.is_set():
                    break
                with self._auto_sync_state_lock:
                    self._auto_sync_plan = list(plan[index:])
                started = self.start_sync(sync_type)
                if not started:
                    break
                if not self._wait_for_current_sync():
                    break
        finally:
            with self._auto_sync_state_lock:
                self._auto_sync_running = False
                self._auto_sync_plan = []
                self._auto_sync_job_thread = None

    def _wait_for_current_sync(self) -> bool:
        while not self._auto_sync_stop_event.is_set():
            status = self._sync.getStatus(self._parts_data)
            if not status.get("running"):
                return not bool(status.get("error"))
            self._auto_sync_stop_event.wait(0.5)
        return False

    def _mark_sync_completed(self, sync_type: str) -> None:
        builder_db.setMeta(
            self._conn,
            self._sync_meta_key(sync_type),
            datetime.now(timezone.utc).isoformat(),
        )

    def _is_sync_stale(self, sync_type: str, max_age_hours: int, now: datetime) -> bool:
        if max_age_hours <= 0:
            return False
        last_synced_at = self.get_last_synced_at(sync_type)
        if not last_synced_at:
            return True
        parsed = self._parse_timestamp(last_synced_at)
        if parsed is None:
            return True
        return now - parsed >= timedelta(hours=max_age_hours)

    def _parse_timestamp(self, value: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _sync_meta_key(self, sync_type: str) -> str:
        return f"{PROFILE_CATALOG_LAST_SYNC_META_PREFIX}{sync_type}"

    def search_parts(self, query: str = "", cat_id: int | None = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        if not query and cat_id is None:
            return {"results": [], "total": 0, "offset": offset, "limit": limit}
        results, total = builder_db.searchParts(self._conn, query, cat_filter=cat_id, limit=limit, offset=offset)
        return {"results": results, "total": total, "offset": offset, "limit": limit}

    def list_colors(self) -> list[dict[str, Any]]:
        colors = []
        for color_id, color in sorted(self._parts_data.colors.items()):
            colors.append(
                {
                    "id": color_id,
                    "name": color.get("name") or str(color_id),
                    "rgb": color.get("rgb"),
                    "is_trans": bool(color.get("is_trans", False)),
                }
            )
        return colors

    def import_bricklink_csv(self, csv_content: str, filename: str | None = None) -> dict[str, Any]:
        if not isinstance(csv_content, str) or not csv_content.strip():
            raise APIError(400, "CSV content is required", "PROFILE_CATALOG_CSV_EMPTY")

        reader = csv.DictReader(io.StringIO(csv_content.lstrip("\ufeff")))
        if not reader.fieldnames:
            raise APIError(400, "CSV file has no header row", "PROFILE_CATALOG_CSV_HEADER_MISSING")

        normalized_headers = {str(name).strip(): name for name in reader.fieldnames if isinstance(name, str)}
        required_headers = {"BLItemNo", "BLColorId", "Qty"}
        missing = sorted(required_headers - set(normalized_headers))
        if missing:
            raise APIError(
                400,
                f"BrickLink CSV is missing required columns: {', '.join(missing)}",
                "PROFILE_CATALOG_CSV_HEADER_INVALID",
            )

        bricklink_parts = self._build_bricklink_part_lookup()
        bricklink_colors = self._build_bricklink_color_lookup()

        merged: dict[tuple[str, int], dict[str, Any]] = {}
        warnings: list[str] = []
        imported_rows = 0

        for row_index, row in enumerate(reader, start=2):
            if not isinstance(row, dict):
                continue
            if not any(str(value or "").strip() for value in row.values()):
                continue

            bl_item_no = str(row.get(normalized_headers["BLItemNo"], "") or "").strip()
            raw_bl_color_id = str(row.get(normalized_headers["BLColorId"], "") or "").strip()
            raw_qty = str(row.get(normalized_headers["Qty"], "") or "").strip()
            part_name = str(row.get(normalized_headers.get("PartName", ""), "") or "").strip() or None
            color_name = str(row.get(normalized_headers.get("ColorName", ""), "") or "").strip() or None

            if not bl_item_no or not raw_bl_color_id or not raw_qty:
                warnings.append(f"Row {row_index}: missing BLItemNo, BLColorId, or Qty")
                continue

            try:
                bl_color_id = int(raw_bl_color_id)
            except ValueError:
                warnings.append(f"Row {row_index}: invalid BLColorId '{raw_bl_color_id}'")
                continue

            try:
                quantity = int(float(raw_qty))
            except ValueError:
                warnings.append(f"Row {row_index}: invalid Qty '{raw_qty}'")
                continue
            if quantity <= 0:
                warnings.append(f"Row {row_index}: Qty must be greater than 0")
                continue

            rb_part_num = bricklink_parts.get(bl_item_no)
            rb_color_id = bricklink_colors.get(bl_color_id)

            if rb_part_num and rb_color_id is not None:
                part_source = "rebrickable"
                stored_part_num = rb_part_num
                stored_color_id = rb_color_id
                part_data = self._parts_data.parts.get(rb_part_num) or {}
                color_data = self._parts_data.colors.get(rb_color_id) or {}
                resolved_part_name = part_data.get("name") or part_name or bl_item_no
                resolved_color_name = color_data.get("name") or color_name or str(bl_color_id)
                resolved_img_url = part_data.get("part_img_url")
            else:
                part_source = "bricklink"
                stored_part_num = bl_item_no
                stored_color_id = bl_color_id
                resolved_part_name = part_name or bl_item_no
                resolved_color_name = color_name or str(bl_color_id)
                resolved_img_url = None
                if not rb_part_num:
                    warnings.append(f"Row {row_index}: imported BrickLink item '{bl_item_no}' without local part mapping")
                if rb_color_id is None:
                    warnings.append(f"Row {row_index}: imported BrickLink color '{bl_color_id}' without local color mapping")

            key = (stored_part_num, stored_color_id)
            item = merged.setdefault(
                key,
                {
                    "part_num": stored_part_num,
                    "part_name": resolved_part_name,
                    "img_url": resolved_img_url,
                    "color_id": stored_color_id,
                    "color_name": resolved_color_name,
                    "part_source": part_source,
                    "quantity": 0,
                },
            )
            item["quantity"] += quantity
            imported_rows += 1

        parts = sorted(
            merged.values(),
            key=lambda item: (
                str(item.get("part_name") or "").lower(),
                str(item.get("color_name") or "").lower(),
                str(item.get("part_num") or ""),
            ),
        )
        if not parts:
            raise APIError(
                400,
                "No usable BrickLink rows could be imported. Check the CSV format and that the parts catalog is synced.",
                "PROFILE_CATALOG_CSV_IMPORT_EMPTY",
            )

        suggested_name = None
        if filename:
            base = os.path.basename(filename).strip()
            stem, _ext = os.path.splitext(base)
            suggested_name = stem.strip() or None

        return {
            "parts": parts,
            "imported_rows": imported_rows,
            "imported_unique_parts": len(parts),
            "warning_count": len(warnings),
            "warnings": warnings[:20],
            "suggested_name": suggested_name,
        }

    def compile_document(self, document: dict[str, Any]) -> dict[str, Any]:
        payload = normalize_profile_document(document)

        # Resolve set rules into BrickLink-keyed mappings and runtime inventories.
        set_mappings, set_inventories = self._resolve_set_rule_data(payload.rules)
        is_set_based = bool(set_inventories)

        result = builder_rule_engine.generateProfile(
            payload,
            self._parts_data.parts,
            self._parts_data.categories,
            self._parts_data.bricklink_categories,
            fallback_mode=payload.fallback_mode,
            parts_generation=self._parts_data.generation,
            rb_to_bl_color=self._parts_data.rb_to_bl_color,
            set_mappings=set_mappings or None,
        )
        categories = build_category_metadata(payload.rules, result["stats"], self._parts_data)
        artifact: dict[str, Any] = {
            "schema_version": 1,
            "id": str(document.get("id") or ""),
            "name": payload.name,
            "description": payload.description,
            "profile_type": "set" if is_set_based else "rule",
            "default_category_id": payload.default_category_id,
            "fallback_mode": payload.fallback_mode,
            "rules": payload.rules,
            "categories": categories,
            "part_to_category": result["part_to_category"],
            "stats": result["stats"],
        }
        if set_inventories:
            artifact["set_inventories"] = set_inventories
        artifact_hash = hashlib.sha256(json.dumps(artifact, sort_keys=True, default=str).encode()).hexdigest()
        artifact["artifact_hash"] = artifact_hash
        total_parts = int(result["stats"].get("total_parts") or 0)
        matched = int(result["stats"].get("matched") or 0)
        coverage_ratio = (matched / total_parts) if total_parts else None
        return {
            "artifact": artifact,
            "stats": result["stats"],
            "artifact_hash": artifact_hash,
            "compiled_part_count": len(result["part_to_category"]),
            "coverage_ratio": coverage_ratio,
        }

    def preview_document(self, document: dict[str, Any]) -> dict[str, Any]:
        return self.compile_document(document)["stats"]

    def preview_rule(
        self,
        *,
        rule: dict[str, Any],
        rules: list[dict[str, Any]] | None = None,
        rule_id: str | None = None,
        q: str = "",
        offset: int = 0,
        limit: int = 50,
        standalone: bool = False,
    ) -> dict[str, Any]:
        payload_rule = copy.deepcopy(rule)
        payload_rules = copy.deepcopy(rules or [])
        builder_sorting_profile._migrateRules([payload_rule])
        builder_sorting_profile._migrateRules(payload_rules)
        ancestor_checks = []
        if not standalone and rule_id:
            fake_profile = SimpleNamespace(rules=payload_rules)
            ancestor_checks = builder_sorting_profile.getAncestorChecks(fake_profile, rule_id)
        return builder_rule_engine.previewRule(
            payload_rule,
            self._parts_data.parts,
            categories=self._parts_data.categories,
            bricklink_categories=self._parts_data.bricklink_categories,
            limit=limit,
            offset=offset,
            q=q,
            ancestor_checks=ancestor_checks,
            parts_generation=self._parts_data.generation,
        )


    def _resolve_set_rule_data(
        self,
        rules: list[dict[str, Any]],
    ) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, Any]]]:
        """Resolve set rules into compile-time mappings and runtime inventories."""
        set_mappings: dict[str, dict[str, str]] = {}
        set_inventories: dict[str, dict[str, Any]] = {}
        for rule in rules:
            if rule.get("disabled"):
                continue
            if rule.get("rule_type") != "set":
                continue
            rule_id = str(rule["id"])
            set_source = str(rule.get("set_source") or ("custom" if rule.get("custom_parts") else "rebrickable"))
            if set_source == "custom":
                mapping, inventory = self._compile_custom_set_rule(rule)
            else:
                mapping, inventory = self._compile_rebrickable_set_rule(rule)
            if not inventory:
                continue
            set_mappings[rule_id] = mapping
            set_inventories[rule_id] = inventory
        return set_mappings, set_inventories

    def _compile_rebrickable_set_rule(self, rule: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any] | None]:
        set_num = str(rule.get("set_num") or "").strip()
        if not set_num:
            return {}, None

        rule_id = str(rule["id"])
        include_spares = bool(rule.get("include_spares", False))

        cached = get_cached_set(self._conn, set_num)
        if cached is None:
            fetch_set_inventory(self._conn, self._config.rebrickable_api_key, set_num)

        inventory = get_cached_inventory(self._conn, set_num)
        mapping: dict[str, str] = {}
        set_info = get_cached_set(self._conn, set_num) or {}
        set_meta = rule.get("set_meta") if isinstance(rule.get("set_meta"), dict) else {}
        parts: list[dict[str, Any]] = []

        for inv_part in inventory:
            if not include_spares and inv_part.get("is_spare"):
                continue
            compiled_part = self._compile_inventory_part(
                part_num=inv_part.get("part_num"),
                color_id=inv_part.get("color_id"),
                quantity=inv_part.get("quantity"),
                part_name=inv_part.get("part_name"),
                color_name=inv_part.get("color_name"),
                img_url=inv_part.get("part_img_url"),
                element_id=inv_part.get("element_id"),
                is_spare=bool(inv_part.get("is_spare", False)),
                require_known_part=False,
                require_known_color=False,
            )
            if compiled_part is None:
                continue
            bl_key = self._inventory_part_to_bl_key(compiled_part)
            if bl_key not in mapping:
                mapping[bl_key] = rule_id
            parts.append(compiled_part)

        return mapping, {
            "rule_id": rule_id,
            "set_num": set_num,
            "name": str(rule.get("name") or set_meta.get("name") or set_info.get("name") or set_num),
            "img_url": (
                set_meta.get("img_url")
                or set_meta.get("set_img_url")
                or set_info.get("set_img_url")
            ),
            "year": set_meta.get("year") or set_info.get("year"),
            "num_parts": set_meta.get("num_parts") or set_info.get("num_parts"),
            "include_spares": include_spares,
            "set_source": "rebrickable",
            "parts": parts,
        }

    def _compile_custom_set_rule(self, rule: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any] | None]:
        rule_id = str(rule["id"])
        set_num = self._custom_set_num(rule)
        set_meta = rule.get("set_meta") if isinstance(rule.get("set_meta"), dict) else {}
        raw_parts = rule.get("custom_parts")
        if not isinstance(raw_parts, list):
            raw_parts = []

        mapping: dict[str, str] = {}
        parts: list[dict[str, Any]] = []
        total_quantity = 0
        for raw_part in raw_parts:
            if not isinstance(raw_part, dict):
                continue
            identifier_source = str(raw_part.get("part_source") or "rebrickable")
            compiled_part = self._compile_inventory_part(
                part_num=raw_part.get("part_num"),
                color_id=raw_part.get("color_id", CUSTOM_SET_ANY_COLOR_ID),
                quantity=raw_part.get("quantity"),
                part_name=raw_part.get("part_name"),
                color_name=raw_part.get("color_name"),
                img_url=raw_part.get("img_url"),
                allow_any_color=True,
                require_known_part=identifier_source != "bricklink",
                require_known_color=identifier_source != "bricklink",
                identifier_source=identifier_source,
            )
            if compiled_part is None:
                continue
            bl_key = self._inventory_part_to_bl_key(compiled_part)
            if bl_key not in mapping:
                mapping[bl_key] = rule_id
            total_quantity += int(compiled_part["quantity"])
            parts.append(compiled_part)

        return mapping, {
            "rule_id": rule_id,
            "set_num": set_num,
            "name": str(rule.get("name") or set_meta.get("name") or "Custom Set"),
            "img_url": None,
            "year": None,
            "num_parts": total_quantity,
            "include_spares": False,
            "set_source": "custom",
            "parts": parts,
        }

    def _compile_inventory_part(
        self,
        *,
        part_num: Any,
        color_id: Any,
        quantity: Any,
        part_name: Any = None,
        color_name: Any = None,
        img_url: Any = None,
        element_id: Any = None,
        is_spare: bool = False,
        allow_any_color: bool = False,
        require_known_part: bool = True,
        require_known_color: bool = True,
        identifier_source: str = "rebrickable",
    ) -> dict[str, Any] | None:
        raw_part_num = str(part_num or "").strip()
        if not raw_part_num:
            return None

        try:
            quantity_value = int(quantity)
        except (TypeError, ValueError) as exc:
            raise APIError(400, f"Invalid quantity for custom set part '{raw_part_num}'", "PROFILE_CUSTOM_SET_QUANTITY_INVALID") from exc
        if quantity_value <= 0:
            raise APIError(400, f"Quantity must be positive for custom set part '{raw_part_num}'", "PROFILE_CUSTOM_SET_QUANTITY_INVALID")

        normalized_color_id = self._normalize_custom_color_id(color_id, allow_any_color=allow_any_color)

        if identifier_source == "bricklink":
            resolved_part_name = str(part_name or raw_part_num)
            if normalized_color_id == CUSTOM_SET_ANY_COLOR_ID:
                bl_color: int | str = "any_color"
                resolved_color_name = "Any color"
            else:
                bl_color = normalized_color_id
                resolved_color_name = str(color_name or normalized_color_id)
            return {
                "part_num": raw_part_num,
                "color_id": CUSTOM_SET_ANY_COLOR_ID if normalized_color_id == CUSTOM_SET_ANY_COLOR_ID else bl_color,
                "quantity": quantity_value,
                "is_spare": is_spare,
                "element_id": element_id,
                "rb_part_num": None,
                "rb_color_id": None if normalized_color_id == CUSTOM_SET_ANY_COLOR_ID else normalized_color_id,
                "part_name": resolved_part_name,
                "color_name": resolved_color_name,
                "img_url": img_url,
            }

        rb_part_num = raw_part_num
        rb_part = self._parts_data.parts.get(rb_part_num)
        if rb_part is None and require_known_part:
            raise APIError(400, f"Unknown part '{rb_part_num}' in custom set", "PROFILE_CUSTOM_SET_PART_UNKNOWN")
        if normalized_color_id == CUSTOM_SET_ANY_COLOR_ID:
            bl_color: int | str = "any_color"
            resolved_color_name = "Any color"
        else:
            color = self._parts_data.colors.get(normalized_color_id)
            if color is None and require_known_color:
                raise APIError(400, f"Unknown color '{normalized_color_id}' in custom set", "PROFILE_CUSTOM_SET_COLOR_UNKNOWN")
            bl_color = self._parts_data.rb_to_bl_color.get(normalized_color_id, normalized_color_id)
            resolved_color_name = str(color_name or (color.get("name") if color else normalized_color_id))

        bl_ids = rb_part.get("external_ids", {}).get("BrickLink", []) if rb_part else []
        bl_part_id = bl_ids[0] if bl_ids else rb_part_num
        resolved_part_name = str(part_name or (rb_part.get("name") if rb_part else rb_part_num) or rb_part_num)

        return {
            "part_num": bl_part_id,
            "color_id": CUSTOM_SET_ANY_COLOR_ID if normalized_color_id == CUSTOM_SET_ANY_COLOR_ID else bl_color,
            "quantity": quantity_value,
            "is_spare": is_spare,
            "element_id": element_id,
            "rb_part_num": rb_part_num,
            "rb_color_id": None if normalized_color_id == CUSTOM_SET_ANY_COLOR_ID else normalized_color_id,
            "part_name": resolved_part_name,
            "color_name": resolved_color_name,
            "img_url": img_url or (rb_part.get("part_img_url") if rb_part else None),
        }

    def _normalize_custom_color_id(self, color_id: Any, *, allow_any_color: bool) -> int:
        if allow_any_color and color_id in (None, "", "any", "any_color"):
            return CUSTOM_SET_ANY_COLOR_ID
        try:
            normalized = int(color_id)
        except (TypeError, ValueError) as exc:
            raise APIError(400, f"Invalid color '{color_id}' in custom set", "PROFILE_CUSTOM_SET_COLOR_INVALID") from exc
        if allow_any_color and normalized == CUSTOM_SET_ANY_COLOR_ID:
            return CUSTOM_SET_ANY_COLOR_ID
        return normalized

    def _inventory_part_to_bl_key(self, part: dict[str, Any]) -> str:
        color_id = part.get("color_id")
        color_key = "any_color" if color_id == CUSTOM_SET_ANY_COLOR_ID else color_id
        return f"{color_key}-{part['part_num']}"

    def _custom_set_num(self, rule: dict[str, Any]) -> str:
        current = str(rule.get("set_num") or "").strip()
        if current:
            return current
        return f"custom:{rule['id']}"

    def _build_bricklink_part_lookup(self) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for rb_part_num, part in self._parts_data.parts.items():
            external_ids = part.get("external_ids", {})
            bricklink_ids = external_ids.get("BrickLink", [])
            if isinstance(bricklink_ids, dict):
                bricklink_ids = bricklink_ids.get("ext_ids", [])
            if not isinstance(bricklink_ids, list):
                continue
            for bricklink_id in bricklink_ids:
                item_no = str(bricklink_id or "").strip()
                if item_no and item_no not in lookup:
                    lookup[item_no] = rb_part_num
        return lookup

    def _build_bricklink_color_lookup(self) -> dict[int, int]:
        lookup: dict[int, int] = {}
        for rb_color_id, color in self._parts_data.colors.items():
            external_ids = color.get("external_ids", {})
            bricklink = external_ids.get("BrickLink", {})
            ext_ids = bricklink.get("ext_ids", []) if isinstance(bricklink, dict) else []
            if not isinstance(ext_ids, list):
                continue
            for bricklink_color_id in ext_ids:
                try:
                    numeric = int(bricklink_color_id)
                except (TypeError, ValueError):
                    continue
                lookup.setdefault(numeric, rb_color_id)
        return lookup

    def search_sets(
        self,
        query: str,
        limit: int = 20,
        min_year: int | None = None,
        max_year: int | None = None,
    ) -> list[dict]:
        results = _search_sets(
            self._config.rebrickable_api_key,
            query,
            min_year=min_year,
            max_year=max_year,
        )
        return [
            {
                "set_num": s["set_num"],
                "name": s["name"],
                "year": s.get("year"),
                "num_parts": s.get("num_parts"),
                "img_url": s.get("set_img_url"),
            }
            for s in results[:limit]
        ]

    def get_set_inventory(self, set_num: str) -> dict[str, Any]:
        normalized_set_num = str(set_num or "").strip()
        if not normalized_set_num:
            raise APIError(400, "set_num is required", "SET_NUM_REQUIRED")

        cached = get_cached_set(self._conn, normalized_set_num)
        if cached is None:
            fetch_set_inventory(self._conn, self._config.rebrickable_api_key, normalized_set_num)
            cached = get_cached_set(self._conn, normalized_set_num)
        if cached is None:
            raise APIError(404, "Set not found", "SET_NOT_FOUND")

        inventory = get_cached_inventory(self._conn, normalized_set_num)
        inventory.sort(
            key=lambda part: (
                str(part.get("part_name") or "").lower(),
                str(part.get("color_name") or "").lower(),
                str(part.get("part_num") or ""),
            )
        )

        return {
            "set": {
                "set_num": cached.get("set_num"),
                "name": cached.get("name"),
                "year": cached.get("year"),
                "num_parts": cached.get("num_parts"),
                "img_url": cached.get("set_img_url"),
            },
            "inventory": inventory,
        }


def normalize_profile_document(document: dict[str, Any]) -> SimpleNamespace:
    payload = SimpleNamespace(
        id=str(document.get("id") or ""),
        name=str(document.get("name") or "Untitled Profile"),
        description=str(document.get("description") or ""),
        default_category_id=str(document.get("default_category_id") or "misc"),
        rules=copy.deepcopy(document.get("rules") or []),
        fallback_mode=normalize_fallback_mode(document.get("fallback_mode")),
    )
    builder_sorting_profile._migrateRules(payload.rules)
    return payload


def normalize_fallback_mode(raw: Any) -> dict[str, bool]:
    raw_dict = raw if isinstance(raw, dict) else {}
    return {
        "rebrickable_categories": bool(raw_dict.get("rebrickable_categories", False)),
        "bricklink_categories": bool(raw_dict.get("bricklink_categories", False)),
        "by_color": bool(raw_dict.get("by_color", False)),
    }


def build_category_metadata(rules: list[dict[str, Any]], stats: dict[str, Any], parts_data: Any) -> dict[str, dict[str, str]]:
    categories: dict[str, dict[str, str]] = {}
    for rule in rules:
        rule_id = str(rule.get("id") or "")
        if not rule_id:
            continue
        if rule.get("rule_type") == "set":
            meta: dict[str, str] = {"name": str(rule.get("name") or rule_id)}
            set_meta = rule.get("set_meta")
            set_source = str(rule.get("set_source") or ("custom" if rule.get("custom_parts") else "rebrickable"))
            meta["set_source"] = set_source
            if isinstance(set_meta, dict):
                if set_meta.get("img_url"):
                    meta["set_img_url"] = str(set_meta["img_url"])
                elif set_meta.get("set_img_url"):
                    meta["set_img_url"] = str(set_meta["set_img_url"])
                if set_meta.get("year") is not None:
                    meta["year"] = str(set_meta["year"])
                if set_meta.get("num_parts") is not None:
                    meta["num_parts"] = str(set_meta["num_parts"])
            if rule.get("set_num"):
                meta["set_num"] = str(rule["set_num"])
            categories[rule_id] = meta
        else:
            categories[rule_id] = {"name": str(rule.get("name") or rule_id)}
    per_category = stats.get("per_category") if isinstance(stats, dict) else {}
    if isinstance(per_category, dict):
        for cat_id in per_category:
            cat_id_str = str(cat_id)
            if cat_id_str in categories:
                continue
            if cat_id_str.startswith("rb_"):
                rb_cat = parts_data.categories.get(int(cat_id_str[3:]))
                categories[cat_id_str] = {"name": rb_cat["name"] if rb_cat else cat_id_str}
            elif cat_id_str.startswith("bl_"):
                bl_cat = parts_data.bricklink_categories.get(int(cat_id_str[3:]))
                categories[cat_id_str] = {
                    "name": bl_cat.get("category_name", cat_id_str) if isinstance(bl_cat, dict) else cat_id_str
                }
            else:
                categories[cat_id_str] = {"name": cat_id_str}
    return categories


_catalog_service: ProfileCatalogService | None = None


def get_profile_catalog_service() -> ProfileCatalogService:
    global _catalog_service
    if _catalog_service is None:
        _catalog_service = ProfileCatalogService()
    return _catalog_service


def get_existing_profile_catalog_service() -> ProfileCatalogService | None:
    return _catalog_service
