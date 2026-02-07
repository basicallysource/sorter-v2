from abc import ABC, abstractmethod
import json

from global_config import GlobalConfig

MISC_CATEGORY = "misc"


class SortingProfile(ABC):
    @abstractmethod
    def getCategoryIdForPart(self, part_id: str) -> str:
        pass


class BrickLinkCategories(SortingProfile):
    def __init__(self, gc: GlobalConfig):
        self._parts_with_categories_file_path = gc.parts_with_categories_file_path
        self.part_to_category: dict[str, str] = {}
        self._loadData()

    def _loadData(self) -> None:
        with open(self._parts_with_categories_file_path, "r") as f:
            data = json.load(f)
        for part in data["pieces"]:
            part_id = part["id"]
            category_id = part.get("category_id")
            if category_id is None:
                continue
            self.part_to_category[part_id] = str(category_id)

    def getCategoryIdForPart(self, part_id: str) -> str:
        out = self.part_to_category.get(part_id, MISC_CATEGORY)
        return out
