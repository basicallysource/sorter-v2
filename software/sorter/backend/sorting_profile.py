from abc import ABC, abstractmethod
import json
from typing import Any, Optional

from global_config import GlobalConfig

MISC_CATEGORY = "misc"


class SortingProfile(ABC):
    @abstractmethod
    def getCategoryIdForPart(self, part_id: str, color_id: str = "any_color") -> str:
        pass

    # Optional price-based override: a profile may declare a high_value_routing
    # block that reroutes any piece whose Hive moving-average price clears a
    # threshold into a chosen category (and thus that category's bin). Returns
    # the override category id, or None when not applicable. Base impl = off.
    def highValueCategoryId(self, price: Optional[float]) -> Optional[str]:
        return None

    # Optional inventory-based override: a profile may declare an
    # inventory_routing block that reroutes any piece NOT present in the active
    # .bsx inventory into a chosen category (e.g. the "not in inventory" bin).
    # `in_inventory` is the live membership answer from bsx_inventory: True/False,
    # or None when undecidable (no active .bsx / no part id). Returns the override
    # category id, or None when not applicable. Base impl = off.
    def notInInventoryCategoryId(self, in_inventory: Optional[bool]) -> Optional[str]:
        return None


class JsonSortingProfile(SortingProfile):
    def __init__(self, gc: GlobalConfig):
        self._gc = gc
        self._sorting_profile_path = gc.sorting_profile_path
        self.part_to_category: dict[str, str] = {}
        self.default_category_id = MISC_CATEGORY
        self.set_inventories: dict[str, dict[str, Any]] | None = None
        self.artifact_hash: str = ""
        self.is_set_based: bool = False
        # Parsed high_value_routing block: {"enabled", "min_price", "category_id"}
        # or None. See highValueCategoryId.
        self.high_value_routing: Optional[dict[str, Any]] = None
        # Parsed inventory_routing block: {"enabled", "not_in_inventory_category_id"}
        # or None. See notInInventoryCategoryId.
        self.inventory_routing: Optional[dict[str, Any]] = None
        self.reload()

    def _loadData(self) -> None:
        try:
            with open(self._sorting_profile_path, "r") as f:
                content = f.read()
            if not content.strip():
                self._gc.logger.warn(
                    f"sorting profile file is empty: {self._sorting_profile_path}"
                )
                return
            data = json.loads(content)
        except FileNotFoundError:
            self._gc.logger.warn(
                f"sorting profile file not found: {self._sorting_profile_path}"
            )
            return
        except json.JSONDecodeError as e:
            self._gc.logger.warn(
                f"sorting profile file is corrupt ({e}): {self._sorting_profile_path}"
            )
            return
        if "part_to_category" not in data:
            raise ValueError("sorting profile json missing part_to_category")
        self._loadRuntimeSortingProfile(data)

    def _loadRuntimeSortingProfile(self, data: dict) -> None:
        self.default_category_id = str(data.get("default_category_id", MISC_CATEGORY))
        self.part_to_category = {}
        part_to_category = data.get("part_to_category", {})
        for part_id, category_id in part_to_category.items():
            self.part_to_category[str(part_id)] = str(category_id)
        raw_set_inventories = data.get("set_inventories")
        self.set_inventories = raw_set_inventories if isinstance(raw_set_inventories, dict) else None
        self.artifact_hash = data.get("artifact_hash", "")
        self.is_set_based = data.get("profile_type") == "set" or bool(self.set_inventories)
        raw_hvr = data.get("high_value_routing")
        self.high_value_routing = raw_hvr if isinstance(raw_hvr, dict) else None
        raw_inv = data.get("inventory_routing")
        self.inventory_routing = raw_inv if isinstance(raw_inv, dict) else None

    def reload(self) -> None:
        self._loadData()

    def getCategoryIdForPart(self, part_id: str, color_id: str = "any_color") -> str:
        color_key = f"{color_id}-{part_id}"
        if color_key in self.part_to_category:
            return self.part_to_category[color_key]
        any_key = f"any_color-{part_id}"
        return self.part_to_category.get(any_key, self.default_category_id)

    def highValueCategoryId(self, price: Optional[float]) -> Optional[str]:
        cfg = self.high_value_routing
        if not cfg or not cfg.get("enabled") or price is None:
            return None
        # Supports multiple price tiers: {"tiers": [{min_price, category_id}, ...]}.
        # Legacy single-tier shape ({min_price, category_id} at top level) is still
        # accepted. Tiers are evaluated highest-threshold-first so a $25 piece takes
        # the >$10 bin, a $4 piece the >$1 bin, etc.
        raw_tiers = cfg.get("tiers")
        if not isinstance(raw_tiers, list):
            raw_tiers = [{"min_price": cfg.get("min_price"), "category_id": cfg.get("category_id")}]
        tiers = [
            (t["min_price"], t["category_id"])
            for t in raw_tiers
            if isinstance(t, dict)
            and isinstance(t.get("min_price"), (int, float))
            and isinstance(t.get("category_id"), str)
        ]
        tiers.sort(key=lambda t: t[0], reverse=True)
        for min_price, category_id in tiers:
            if price > min_price:
                return category_id
        return None

    def notInInventoryCategoryId(self, in_inventory: Optional[bool]) -> Optional[str]:
        cfg = self.inventory_routing
        # Only fire on a definite "not in inventory" answer. None (undecidable:
        # no active .bsx or no part id) and True (in inventory) both pass through
        # to normal routing.
        if not cfg or not cfg.get("enabled") or in_inventory is not False:
            return None
        category_id = cfg.get("not_in_inventory_category_id")
        return category_id if isinstance(category_id, str) and category_id else None


def mkSortingProfile(gc: GlobalConfig) -> SortingProfile:
    return JsonSortingProfile(gc)
