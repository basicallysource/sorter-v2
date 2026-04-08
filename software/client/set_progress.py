import time
from typing import Any

from local_state import get_set_progress_state, set_set_progress_state
AUTO_SAVE_INTERVAL_SEC = 5.0
ANY_COLOR_ID = "-1"


class SetProgressTracker:
    def __init__(self, set_inventories: dict[str, dict[str, Any]], artifact_hash: str):
        self._artifact_hash = artifact_hash
        self._dirty = False
        self._last_saved_at = 0.0
        self._state_token = 0
        # Build lookup: key = "{color_id}-{part_num}" -> list of entries for matching sets.
        self._part_lookup: dict[str, list[dict[str, Any]]] = {}
        self._set_info: dict[str, dict[str, Any]] = {}
        self._set_parts: dict[str, list[dict[str, Any]]] = {}

        for raw_category_id, inventory_data in set_inventories.items():
            category_id, set_info, parts = self._normalize_inventory(raw_category_id, inventory_data)
            total_needed = 0
            merged_entries: dict[tuple[str, str], dict[str, Any]] = {}
            for part in parts:
                entry = self._merge_part_entry(
                    merged_entries,
                    category_id=category_id,
                    set_info=set_info,
                    part=part,
                )
                total_needed += int(part["quantity"])

            for entry in merged_entries.values():
                key = f"{entry['color_id']}-{entry['part_num']}"
                self._part_lookup.setdefault(key, []).append(entry)
                self._set_parts.setdefault(category_id, []).append(entry)
            self._set_info[category_id] = {
                **set_info,
                "total_needed": total_needed,
                "total_found": 0,
            }

        self._load()

    def _normalize_inventory(
        self,
        raw_category_id: str,
        inventory_data: dict[str, Any] | list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        # Legacy artifacts stored inventories by set number while categories used "set_{set_num}".
        if isinstance(inventory_data, list):
            category_id = raw_category_id if raw_category_id.startswith("set_") else f"set_{raw_category_id}"
            return (
                category_id,
                {
                    "set_num": raw_category_id.removeprefix("set_"),
                    "name": raw_category_id.removeprefix("set_"),
                    "img_url": None,
                    "year": None,
                    "num_parts": None,
                },
                inventory_data,
            )

        parts = inventory_data.get("parts")
        if not isinstance(parts, list):
            parts = []
        return (
            raw_category_id,
            {
                "set_num": str(inventory_data.get("set_num") or raw_category_id),
                "name": str(inventory_data.get("name") or inventory_data.get("set_num") or raw_category_id),
                "img_url": inventory_data.get("img_url"),
                "year": inventory_data.get("year"),
                "num_parts": inventory_data.get("num_parts"),
            },
            parts,
        )

    def _merge_part_entry(
        self,
        entries: dict[tuple[str, str], dict[str, Any]],
        *,
        category_id: str,
        set_info: dict[str, Any],
        part: dict[str, Any],
    ) -> dict[str, Any]:
        part_num = str(part["part_num"])
        color_id = str(part["color_id"])
        key = (part_num, color_id)
        entry = entries.get(key)
        if entry is None:
            entry = {
                "category_id": category_id,
                "set_num": set_info["set_num"],
                "name": set_info["name"],
                "img_url": set_info["img_url"],
                "year": set_info["year"],
                "num_parts": set_info["num_parts"],
                "part_num": part_num,
                "color_id": color_id,
                "part_name": part.get("part_name"),
                "color_name": part.get("color_name"),
                "quantity_needed": 0,
                "quantity_found": 0,
            }
            entries[key] = entry
        else:
            if not entry.get("part_name") and part.get("part_name"):
                entry["part_name"] = part.get("part_name")
            if not entry.get("color_name") and part.get("color_name"):
                entry["color_name"] = part.get("color_name")

        entry["quantity_needed"] += int(part["quantity"])
        return entry

    def record(self, part_id: str, color_id: str, category_id: str) -> None:
        """Record a sorted piece when it belongs to one of the tracked set rules."""
        if category_id not in self._set_info:
            return
        exact_key = f"{str(color_id)}-{str(part_id)}"
        wildcard_key = f"{ANY_COLOR_ID}-{str(part_id)}"
        entries = [*self._part_lookup.get(exact_key, [])]
        if wildcard_key != exact_key:
            entries.extend(self._part_lookup.get(wildcard_key, []))
        for entry in entries:
            if entry["category_id"] == category_id and entry["quantity_found"] < entry["quantity_needed"]:
                entry["quantity_found"] += 1
                self._set_info[category_id]["total_found"] += 1
                self._dirty = True
                self._state_token += 1
                self._maybe_save()
                return

    def get_progress(self) -> dict[str, Any]:
        """Get per-set progress summary."""
        sets = []
        overall_needed = 0
        overall_found = 0
        for category_id, info in self._set_info.items():
            needed = info["total_needed"]
            found = info["total_found"]
            overall_needed += needed
            overall_found += found
            pct = (found / needed * 100) if needed > 0 else 0
            sets.append({
                "id": category_id,
                "set_num": info["set_num"],
                "name": info["name"],
                "img_url": info["img_url"],
                "year": info["year"],
                "num_parts": info["num_parts"],
                "total_needed": needed,
                "total_found": found,
                "pct": round(pct, 1),
                "parts": [
                    {
                        "part_num": entry["part_num"],
                        "color_id": entry["color_id"],
                        "part_name": entry.get("part_name"),
                        "color_name": entry.get("color_name"),
                        "quantity_needed": entry["quantity_needed"],
                        "quantity_found": entry["quantity_found"],
                    }
                    for entry in self._set_parts.get(category_id, [])
                ],
            })
        overall_pct = (overall_found / overall_needed * 100) if overall_needed > 0 else 0
        return {
            "overall_needed": overall_needed,
            "overall_found": overall_found,
            "overall_pct": round(overall_pct, 1),
            "sets": sets,
        }

    def get_snapshot(self) -> dict[str, Any]:
        """Serializable snapshot for WebSocket broadcast and SortHive reporting."""
        return {
            "artifact_hash": self._artifact_hash,
            "updated_at": time.time(),
            **self.get_progress(),
        }

    def get_report_items(self) -> list[dict[str, Any]]:
        """Get flat list of items for SortHive progress reporting."""
        items = []
        for category_id, entries in self._set_parts.items():
            for entry in entries:
                items.append({
                    "category_id": category_id,
                    "set_num": entry["set_num"],
                    "name": entry["name"],
                    "part_num": entry["part_num"],
                    "color_id": entry["color_id"],
                    "part_name": entry.get("part_name"),
                    "color_name": entry.get("color_name"),
                    "quantity_needed": entry["quantity_needed"],
                    "quantity_found": entry["quantity_found"],
                })
        return items

    def get_sync_payload(self) -> dict[str, Any]:
        return {
            "artifact_hash": self._artifact_hash,
            "items": self.get_report_items(),
            "state_token": self._state_token,
        }

    def save(self) -> None:
        """Persist progress to local SQLite state."""
        if not self._dirty and get_set_progress_state() is not None:
            return
        progress_data: dict[str, dict[str, int]] = {}
        for category_id, entries in self._set_parts.items():
            for entry in entries:
                part_key = f"{entry['color_id']}-{entry['part_num']}"
                progress_data.setdefault(category_id, {})[part_key] = entry["quantity_found"]

        data = {
            "artifact_hash": self._artifact_hash,
            "updated_at": time.time(),
            "progress": progress_data,
        }
        set_set_progress_state(data)
        self._dirty = False
        self._last_saved_at = time.time()

    def _maybe_save(self) -> None:
        if not self._dirty:
            return
        if self._last_saved_at == 0.0 or (time.time() - self._last_saved_at) >= AUTO_SAVE_INTERVAL_SEC:
            self.save()

    def _load(self) -> None:
        """Load progress from local SQLite state if artifact hash matches."""
        data = get_set_progress_state()
        if not isinstance(data, dict):
            return
        if data.get("artifact_hash") != self._artifact_hash:
            return  # Profile changed, start fresh
        progress = data.get("progress", {})
        restored_any = False
        for category_id, parts in progress.items():
            if category_id not in self._set_info:
                continue
            restored_found = 0
            for entry in self._set_parts.get(category_id, []):
                part_key = f"{entry['color_id']}-{entry['part_num']}"
                found = parts.get(part_key, 0)
                entry["quantity_found"] = min(found, entry["quantity_needed"])
                restored_found += entry["quantity_found"]
            self._set_info[category_id]["total_found"] = restored_found
            if restored_found > 0:
                restored_any = True
        self._last_saved_at = float(data.get("updated_at") or 0.0)
        if restored_any:
            self._state_token = 1
