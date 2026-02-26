from abc import ABC, abstractmethod
from typing import Optional
import json

from global_config import GlobalConfig

MISC_CATEGORY = "misc"


class SortingProfile(ABC):
    @abstractmethod
    def getCategoryIdForPart(self, part_id: str) -> str:
        pass

    @abstractmethod
    def getMetadata(self) -> dict:
        pass

    @abstractmethod
    def getCategoryName(self, category_id: str) -> Optional[str]:
        pass


class JsonSortingProfile(SortingProfile):
    def __init__(self, gc: GlobalConfig):
        self._sorting_profile_path = gc.sorting_profile_path
        self.part_to_category: dict[str, str] = {}
        self.default_category_id = MISC_CATEGORY
        self.profile_id: Optional[str] = None
        self.profile_name: Optional[str] = None
        self.categories: dict[str, str] = {}
        self._loadData()

    def _loadData(self) -> None:
        with open(self._sorting_profile_path, "r") as f:
            data = json.load(f)
        if "part_to_category" not in data:
            raise ValueError("sorting profile json missing part_to_category")
        self._loadRuntimeSortingProfile(data)

    def _loadRuntimeSortingProfile(self, data: dict) -> None:
        self.default_category_id = str(data.get("default_category_id", MISC_CATEGORY))
        self.profile_id = data.get("id")
        self.profile_name = data.get("name")
        raw_categories = data.get("categories", {})
        self.categories = {str(k): v["name"] for k, v in raw_categories.items()}
        part_to_category = data.get("part_to_category", {})
        for part_id, category_id in part_to_category.items():
            self.part_to_category[str(part_id)] = str(category_id)

    def getCategoryIdForPart(self, part_id: str) -> str:
        key = f"any_color-{part_id}"
        return self.part_to_category.get(key, self.default_category_id)

    def getMetadata(self) -> dict:
        return {
            "id": self.profile_id,
            "name": self.profile_name,
            "default_category_id": self.default_category_id,
            "categories": self.categories,
        }

    def getCategoryName(self, category_id: str) -> Optional[str]:
        return self.categories.get(category_id)


def mkSortingProfile(gc: GlobalConfig) -> SortingProfile:
    return JsonSortingProfile(gc)
