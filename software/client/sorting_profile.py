from abc import ABC, abstractmethod
import json

from global_config import GlobalConfig

MISC_CATEGORY = "misc"


class SortingProfile(ABC):
    @abstractmethod
    def get_category_id_for_part(self, part_id: str, color_id: str = "any_color") -> str:
        pass


class JsonSortingProfile(SortingProfile):
    def __init__(self, gc: GlobalConfig):
        self._sorting_profile_path = gc.sorting_profile_path
        self.part_to_category: dict[str, str] = {}
        self.default_category_id = MISC_CATEGORY
        self._load_data()

    def _load_data(self) -> None:
        with open(self._sorting_profile_path, "r") as f:
            data = json.load(f)
        if "part_to_category" not in data:
            raise ValueError("sorting profile json missing part_to_category")
        self._load_runtime_sorting_profile(data)

    def _load_runtime_sorting_profile(self, data: dict) -> None:
        self.default_category_id = str(data.get("default_category_id", MISC_CATEGORY))
        part_to_category = data.get("part_to_category", {})
        for part_id, category_id in part_to_category.items():
            self.part_to_category[str(part_id)] = str(category_id)

    def get_category_id_for_part(self, part_id: str, color_id: str = "any_color") -> str:
        color_key = f"{color_id}-{part_id}"
        if color_key in self.part_to_category:
            return self.part_to_category[color_key]
        any_key = f"any_color-{part_id}"
        return self.part_to_category.get(any_key, self.default_category_id)


def make_sorting_profile(gc: GlobalConfig) -> SortingProfile:
    return JsonSortingProfile(gc)
