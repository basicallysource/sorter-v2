from abc import ABC, abstractmethod
import json
import os
import threading
from typing import Any, Callable, Optional

from global_config import GlobalConfig

MISC_CATEGORY = "misc"

# A profile file carries the compiled part map and runs to tens of MB, and
# json.loads holds the GIL for 1 to 2 s on the Pi: every thread stops, the
# control loop included. Each version of a file is parsed once; everything but
# the part map is kept here for the API, and the runtime's own parse fills it.
_summaries: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
_summaries_lock = threading.Lock()


def _summarize(data: dict[str, Any]) -> dict[str, Any]:
    summary = {k: v for k, v in data.items() if k not in ("part_to_category", "program")}
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    summary["part_count"] = (
        int(stats.get("matched") or 0) if "program" in data else len(data.get("part_to_category") or {})
    )
    return summary


ANY_COLOR = "any_color"


class ProfileRouter:
    """A compiled program (Hive's format since the flat part map): an ordered
    list of rules, each taking some parts in some colors, first match wins.
    A kit rule takes a part only while its kit still needs it, so once a kit
    has enough of a part, further pieces go on to the next rule."""

    def __init__(self, program: dict[str, Any]) -> None:
        self.rules: list[tuple[str, str, Any, Any]] = []
        for entry in program.get("rules") or []:
            if not isinstance(entry, dict) or not entry.get("category"):
                continue
            category = str(entry["category"])
            kit = entry.get("kit")
            if isinstance(kit, dict):
                self.rules.append(
                    ("kit", category, {str(part): {None if c is None else str(c) for c in colors} for part, colors in kit.items()}, None)
                )
                continue
            parts = entry.get("parts")
            colors = entry.get("colors")
            self.rules.append(
                (
                    "rule",
                    category,
                    None if parts is None else {str(part) for part in parts},
                    None if colors is None else {str(color) for color in colors},
                )
            )
        fallback = program.get("fallback") if isinstance(program.get("fallback"), dict) else {}
        self.fallback_by = fallback.get("by")
        self.fallback_map: dict[str, str] = {str(k): str(v) for k, v in (fallback.get("map") or {}).items()}
        self.default = str(program.get("default") or MISC_CATEGORY)

    def route(
        self,
        part_id: str,
        color_id: Optional[str],
        kit_is_full: Optional[Callable[[str, str, str], bool]] = None,
    ) -> str:
        part = str(part_id)
        color = None if color_id in (None, "", ANY_COLOR) else str(color_id)
        for kind, category, parts, colors in self.rules:
            if kind == "kit":
                wanted = parts.get(part)
                if wanted is None or not (color in wanted or None in wanted):
                    continue
                if kit_is_full is not None and kit_is_full(category, part, color or ANY_COLOR):
                    continue
                return category
            if parts is not None and part not in parts:
                continue
            if colors is not None and color not in colors:
                continue
            return category
        if self.fallback_by == "category" and part in self.fallback_map:
            return self.fallback_map[part]
        if self.fallback_by == "color" and color is not None:
            return f"color_{color}"
        return self.default


def categoryResolver(data: dict[str, Any]) -> Callable[[str, str], str]:
    """Where a piece goes under a profile file's contents (program or flat
    map), with every kit taken as still collecting."""
    program = data.get("program")
    if isinstance(program, dict):
        router = ProfileRouter(program)
        return lambda part_id, color_id: router.route(part_id, color_id)
    part_to_category = data.get("part_to_category") or {}
    default = str(data.get("default_category_id", MISC_CATEGORY))

    def legacy(part_id: str, color_id: str) -> str:
        key = f"{color_id}-{part_id}"
        if key in part_to_category:
            return str(part_to_category[key])
        return str(part_to_category.get(f"{ANY_COLOR}-{part_id}", default))

    return legacy


def _fileVersion(path: str) -> tuple[int, int]:
    stat = os.stat(path)
    return stat.st_mtime_ns, stat.st_size


def profileSummary(path: str) -> dict[str, Any]:
    """Everything in a profile file except its part map, plus `part_count`.
    Raises OSError or ValueError when the file is missing or not a JSON object."""
    path = str(path)
    version = _fileVersion(path)
    with _summaries_lock:
        cached = _summaries.get(path)
        if cached is not None and cached[0] == version:
            return cached[1]
    with open(path, "r") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("sorting profile file is not a JSON object")
    summary = _summarize(data)
    with _summaries_lock:
        _summaries[path] = (version, summary)
    return summary


class SortingProfile(ABC):
    @abstractmethod
    def getCategoryIdForPart(self, part_id: str, color_id: str = "any_color") -> str:
        pass

    def setKitProgress(self, tracker: Any) -> None:
        """The kit tracker whose counts decide when a kit passes pieces on;
        a profile without kits ignores it."""
        return None

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
        # The program, when the file has one (else the flat part map is used),
        # and how to ask whether a kit already has enough of a part.
        self._router: Optional[ProfileRouter] = None
        self._kit_is_full: Optional[Callable[[str, str, str], bool]] = None
        self.reload()

    def _loadData(self) -> None:
        try:
            version = _fileVersion(self._sorting_profile_path)
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
        if "part_to_category" not in data and "program" not in data:
            raise ValueError("sorting profile json has neither a program nor part_to_category")
        with _summaries_lock:
            _summaries[str(self._sorting_profile_path)] = (version, _summarize(data))
        self._loadRuntimeSortingProfile(data)

    def _loadRuntimeSortingProfile(self, data: dict) -> None:
        self.default_category_id = str(data.get("default_category_id", MISC_CATEGORY))
        self.part_to_category = {}
        program = data.get("program")
        self._router = ProfileRouter(program) if isinstance(program, dict) else None
        if self._router is None:
            for part_id, category_id in (data.get("part_to_category") or {}).items():
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

    def setKitProgress(self, tracker: Any) -> None:
        """The kit tracker whose counts decide when a kit passes pieces on."""
        self._kit_is_full = tracker.isFull if tracker is not None else None

    def getCategoryIdForPart(self, part_id: str, color_id: str = "any_color") -> str:
        if self._router is not None:
            return self._router.route(part_id, color_id, self._kit_is_full)
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
