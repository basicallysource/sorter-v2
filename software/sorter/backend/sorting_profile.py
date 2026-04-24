from abc import ABC, abstractmethod
import json
import os
from pathlib import Path
from typing import Any

from global_config import GlobalConfig

MISC_CATEGORY = "misc"


def load_sorting_profile_dict(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read a sorting-profile JSON file and return its raw dict body.

    Single source of truth for the on-disk sorting-profile shape; any
    caller that needs the whole document (metadata, set inventories,
    fallback flags) should go through here instead of re-implementing
    ``open()`` + ``json.load()``.
    """
    with Path(path).open("r") as fp:
        data = json.load(fp)
    if not isinstance(data, dict):
        raise ValueError(f"sorting profile {path} is not a JSON object")
    return data


class SortingProfile(ABC):
    @abstractmethod
    def getCategoryIdForPart(self, part_id: str, color_id: str = "any_color") -> str:
        pass


class JsonSortingProfile(SortingProfile):
    def __init__(self, gc: GlobalConfig):
        self._sorting_profile_path = gc.sorting_profile_path
        self.part_to_category: dict[str, str] = {}
        self.default_category_id = MISC_CATEGORY
        self.set_inventories: dict[str, dict[str, Any]] | None = None
        self.artifact_hash: str = ""
        self.is_set_based: bool = False
        self.reload()

    def _loadData(self) -> None:
        data = load_sorting_profile_dict(self._sorting_profile_path)
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

    def reload(self) -> None:
        self._loadData()

    def getCategoryIdForPart(self, part_id: str, color_id: str = "any_color") -> str:
        color_key = f"{color_id}-{part_id}"
        if color_key in self.part_to_category:
            return self.part_to_category[color_key]
        any_key = f"any_color-{part_id}"
        return self.part_to_category.get(any_key, self.default_category_id)


def mkSortingProfile(gc: GlobalConfig) -> SortingProfile:
    return JsonSortingProfile(gc)
