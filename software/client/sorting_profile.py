from abc import ABC, abstractmethod
import json
import os

MISC_CATEGORY = "misc"


class SortingProfile(ABC):
    @abstractmethod
    def getCategoryIdForPart(self, part_id: str) -> str:
        pass


class BrickLinkCategories(SortingProfile):
    def __init__(self):
        self.part_to_category: dict[str, str] = {}
        self._loadData()

    def _loadData(self) -> None:
        path = os.path.join(os.path.dirname(__file__), "parts_with_categories.json")
        with open(path, "r") as f:
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
