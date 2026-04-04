import json
import time
from pathlib import Path
from typing import Any

from blob_manager import BLOB_DIR


PROGRESS_FILE = BLOB_DIR / "set_progress.json"


class SetProgressTracker:
    def __init__(self, set_inventories: dict[str, list[dict]], artifact_hash: str):
        self._artifact_hash = artifact_hash
        self._dirty = False
        # Build lookup: key = "{color_id}-{part_num}" -> list of {set_num, quantity_needed, quantity_found}
        self._part_lookup: dict[str, list[dict[str, Any]]] = {}
        self._set_info: dict[str, dict[str, Any]] = {}

        for set_num, parts in set_inventories.items():
            total_needed = 0
            for part in parts:
                key = f"{part['color_id']}-{part['part_num']}"
                entry = {
                    "set_num": set_num,
                    "part_num": part["part_num"],
                    "color_id": part["color_id"],
                    "quantity_needed": part["quantity"],
                    "quantity_found": 0,
                }
                if key not in self._part_lookup:
                    self._part_lookup[key] = []
                self._part_lookup[key].append(entry)
                total_needed += part["quantity"]
            self._set_info[set_num] = {"total_needed": total_needed, "total_found": 0}

        self._load()

    def record(self, part_id: str, color_id: str, category_id: str) -> None:
        """Record a sorted piece. Only counts if category_id starts with 'set_'."""
        if not category_id.startswith("set_"):
            return
        key = f"{color_id}-{part_id}"
        entries = self._part_lookup.get(key, [])
        target_set = category_id[4:]  # strip "set_" prefix
        for entry in entries:
            if entry["set_num"] == target_set and entry["quantity_found"] < entry["quantity_needed"]:
                entry["quantity_found"] += 1
                self._set_info[target_set]["total_found"] += 1
                self._dirty = True
                return

    def get_progress(self) -> dict[str, Any]:
        """Get per-set progress summary."""
        sets = []
        overall_needed = 0
        overall_found = 0
        for set_num, info in self._set_info.items():
            needed = info["total_needed"]
            found = info["total_found"]
            overall_needed += needed
            overall_found += found
            pct = (found / needed * 100) if needed > 0 else 0
            # Collect per-part details
            parts = []
            for entries in self._part_lookup.values():
                for entry in entries:
                    if entry["set_num"] == set_num:
                        parts.append({
                            "part_num": entry["part_num"],
                            "color_id": entry["color_id"],
                            "quantity_needed": entry["quantity_needed"],
                            "quantity_found": entry["quantity_found"],
                        })
            sets.append({
                "set_num": set_num,
                "total_needed": needed,
                "total_found": found,
                "pct": round(pct, 1),
                "parts": parts,
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
        for entries in self._part_lookup.values():
            for entry in entries:
                items.append({
                    "set_num": entry["set_num"],
                    "part_num": entry["part_num"],
                    "color_id": entry["color_id"],
                    "quantity_needed": entry["quantity_needed"],
                    "quantity_found": entry["quantity_found"],
                })
        return items

    def save(self) -> None:
        """Persist progress to local file."""
        if not self._dirty and PROGRESS_FILE.exists():
            return
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        progress_data: dict[str, dict[str, int]] = {}
        for entries in self._part_lookup.values():
            for entry in entries:
                set_key = entry["set_num"]
                part_key = f"{entry['color_id']}-{entry['part_num']}"
                if set_key not in progress_data:
                    progress_data[set_key] = {}
                progress_data[set_key][part_key] = entry["quantity_found"]

        data = {
            "artifact_hash": self._artifact_hash,
            "updated_at": time.time(),
            "progress": progress_data,
        }
        with open(PROGRESS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        self._dirty = False

    def _load(self) -> None:
        """Load progress from local file if artifact hash matches."""
        if not PROGRESS_FILE.exists():
            return
        try:
            with open(PROGRESS_FILE, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        if data.get("artifact_hash") != self._artifact_hash:
            return  # Profile changed, start fresh
        progress = data.get("progress", {})
        for set_num, parts in progress.items():
            if set_num not in self._set_info:
                continue
            restored_found = 0
            for entries in self._part_lookup.values():
                for entry in entries:
                    if entry["set_num"] == set_num:
                        part_key = f"{entry['color_id']}-{entry['part_num']}"
                        found = parts.get(part_key, 0)
                        entry["quantity_found"] = min(found, entry["quantity_needed"])
                        restored_found += entry["quantity_found"]
            self._set_info[set_num]["total_found"] = restored_found
