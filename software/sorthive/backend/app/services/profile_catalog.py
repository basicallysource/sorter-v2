from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from typing import Any

from app.config import settings
from app.services.profile_builder_compat import (
    builder_db,
    builder_parts_cache,
    builder_rule_engine,
    builder_sorting_profile,
)
from app.services.set_inventory import get_cached_inventory, get_cached_set, fetch_set_inventory


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

    @property
    def parts_data(self):
        return self._parts_data

    def status(self) -> dict[str, Any]:
        return self._sync.getStatus(self._parts_data)

    def start_sync(self, sync_type: str) -> bool:
        with self._lock:
            if sync_type == "categories":
                return self._sync.startCategoriesSync(self._config, self._conn, self._parts_data)
            if sync_type == "colors":
                return self._sync.startColorsSync(self._config, self._conn, self._parts_data)
            if sync_type == "parts":
                return self._sync.startPartsSync(self._config, self._conn, self._parts_data)
            if sync_type == "brickstore":
                return self._sync.startBrickstoreImport(self._config, self._conn, self._parts_data)
            if sync_type == "prices":
                return self._sync.startPriceSync(self._config, self._conn, self._parts_data)
        raise ValueError(f"Unsupported sync_type '{sync_type}'")

    def stop_sync(self) -> None:
        self._sync.requestStop()

    def search_parts(self, query: str = "", cat_id: int | None = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        if not query and cat_id is None:
            return {"results": [], "total": 0, "offset": offset, "limit": limit}
        results, total = builder_db.searchParts(self._conn, query, cat_filter=cat_id, limit=limit, offset=offset)
        return {"results": results, "total": total, "offset": offset, "limit": limit}

    def compile_document(self, document: dict[str, Any]) -> dict[str, Any]:
        payload = normalize_profile_document(document)
        result = builder_rule_engine.generateProfile(
            payload,
            self._parts_data.parts,
            self._parts_data.categories,
            self._parts_data.bricklink_categories,
            fallback_mode=payload.fallback_mode,
            parts_generation=self._parts_data.generation,
            rb_to_bl_color=self._parts_data.rb_to_bl_color,
        )
        categories = build_category_metadata(payload.rules, result["stats"], self._parts_data)
        artifact: dict[str, Any] = {
            "schema_version": 1,
            "id": str(document.get("id") or ""),
            "name": payload.name,
            "description": payload.description,
            "default_category_id": payload.default_category_id,
            "fallback_mode": payload.fallback_mode,
            "rules": payload.rules,
            "categories": categories,
            "part_to_category": result["part_to_category"],
            "stats": result["stats"],
        }
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


    def compile_set_profile(
        self,
        set_config: dict[str, Any],
        profile_id: str,
        name: str,
        description: str = "",
    ) -> dict[str, Any]:
        set_nums = set_config.get("sets", [])
        include_spares = bool(set_config.get("include_spares", False))

        # Ensure all set inventories are cached
        for set_num in set_nums:
            cached = get_cached_set(self._conn, set_num)
            if cached is None:
                fetch_set_inventory(self._conn, self._config.rebrickable_api_key, set_num)

        # Build part_to_category mapping and categories metadata
        part_to_category: dict[str, str] = {}
        categories: dict[str, dict[str, Any]] = {}
        set_inventories: dict[str, list[dict[str, Any]]] = {}

        for set_num in set_nums:
            set_info = get_cached_set(self._conn, set_num)
            inventory = get_cached_inventory(self._conn, set_num)
            category_id = f"set_{set_num}"

            categories[category_id] = {
                "name": set_info["name"] if set_info else set_num,
                "set_num": set_num,
                "set_img_url": set_info.get("set_img_url", "") if set_info else "",
                "num_parts": str(set_info.get("num_parts", "")) if set_info else "",
                "year": str(set_info.get("year", "")) if set_info else "",
            }

            inv_list = []
            for part in inventory:
                if not include_spares and part.get("is_spare"):
                    continue
                key = f"{part['color_id']}-{part['part_num']}"
                # First set in list wins conflicts
                if key not in part_to_category:
                    part_to_category[key] = category_id
                inv_list.append({
                    "part_num": part["part_num"],
                    "color_id": part["color_id"],
                    "quantity": part["quantity"],
                    "is_spare": part.get("is_spare", False),
                    "element_id": part.get("element_id"),
                })
            set_inventories[set_num] = inv_list

        # Add misc category for unclaimed parts
        categories["misc"] = {"name": "Miscellaneous"}

        artifact: dict[str, Any] = {
            "schema_version": 1,
            "id": profile_id,
            "name": name,
            "description": description,
            "default_category_id": "misc",
            "profile_type": "set",
            "categories": categories,
            "part_to_category": part_to_category,
            "set_inventories": set_inventories,
            "set_config": {
                "sets": set_nums,
                "include_spares": include_spares,
            },
            "stats": {
                "total_parts": len(part_to_category),
                "matched": len(part_to_category),
                "per_category": {
                    cat_id: sum(1 for v in part_to_category.values() if v == cat_id)
                    for cat_id in categories
                    if cat_id != "misc"
                },
            },
        }
        artifact_hash = hashlib.sha256(
            json.dumps(artifact, sort_keys=True, default=str).encode()
        ).hexdigest()
        artifact["artifact_hash"] = artifact_hash

        return {
            "artifact": artifact,
            "stats": artifact["stats"],
            "artifact_hash": artifact_hash,
            "compiled_part_count": len(part_to_category),
            "coverage_ratio": 1.0,
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
        if rule_id:
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
