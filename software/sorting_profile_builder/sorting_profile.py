import json
import os
import uuid
from datetime import datetime, timezone


class InternalCategory:
    name: str

    def __init__(self, name: str):
        self.name = name


class SortingProfileMeta:
    id: str
    name: str
    description: str
    created_at: str
    updated_at: str
    file_path: str
    part_count: int
    category_count: int

    def __init__(self):
        pass


class SortingProfile:
    id: str
    name: str
    description: str
    created_at: str
    updated_at: str
    default_category_id: str
    categories: dict[str, InternalCategory]
    part_to_category: dict[str, str]

    def __init__(self):
        self.categories = {}
        self.part_to_category = {}
        self.default_category_id = "misc"


def mkSortingProfile(name: str, description: str = "") -> SortingProfile:
    sp = SortingProfile()
    sp.id = str(uuid.uuid4())
    sp.name = name
    sp.description = description
    now = datetime.now(timezone.utc).isoformat()
    sp.created_at = now
    sp.updated_at = now
    return sp


def loadSortingProfile(file_path: str) -> SortingProfile:
    with open(file_path, "r") as f:
        data = json.load(f)
    sp = SortingProfile()
    sp.id = data["id"]
    sp.name = data["name"]
    sp.description = data.get("description", "")
    sp.created_at = data["created_at"]
    sp.updated_at = data["updated_at"]
    sp.default_category_id = data.get("default_category_id", "misc")
    for cat_id, cat_data in data.get("categories", {}).items():
        sp.categories[cat_id] = InternalCategory(name=cat_data["name"])
    sp.part_to_category = data.get("part_to_category", {})
    return sp


def saveSortingProfile(profiles_dir: str, sp: SortingProfile) -> str:
    sp.updated_at = datetime.now(timezone.utc).isoformat()
    out = {
        "id": sp.id,
        "name": sp.name,
        "description": sp.description,
        "created_at": sp.created_at,
        "updated_at": sp.updated_at,
        "default_category_id": sp.default_category_id,
        "categories": {cid: {"name": c.name} for cid, c in sp.categories.items()},
        "part_to_category": sp.part_to_category,
    }
    os.makedirs(profiles_dir, exist_ok=True)
    file_path = os.path.join(profiles_dir, f"{sp.id}.json")
    with open(file_path, "w") as f:
        json.dump(out, f, indent=2)
    return file_path


def listSortingProfiles(profiles_dir: str) -> list[SortingProfileMeta]:
    metas = []
    if not os.path.isdir(profiles_dir):
        return metas
    for fname in os.listdir(profiles_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(profiles_dir, fname)
        try:
            with open(fpath, "r") as f:
                data = json.load(f)
            meta = SortingProfileMeta()
            meta.id = data["id"]
            meta.name = data["name"]
            meta.description = data.get("description", "")
            meta.created_at = data["created_at"]
            meta.updated_at = data["updated_at"]
            meta.file_path = os.path.abspath(fpath)
            meta.part_count = len(data.get("part_to_category", {}))
            meta.category_count = len(data.get("categories", {}))
            metas.append(meta)
        except (json.JSONDecodeError, KeyError):
            continue
    metas.sort(key=lambda m: m.updated_at, reverse=True)
    return metas


def deleteSortingProfile(profiles_dir: str, profile_id: str) -> bool:
    fpath = os.path.join(profiles_dir, f"{profile_id}.json")
    if os.path.exists(fpath):
        os.remove(fpath)
        return True
    return False


def addCategory(sp: SortingProfile, name: str) -> str:
    cat_id = str(uuid.uuid4())
    sp.categories[cat_id] = InternalCategory(name=name)
    return cat_id


def removeCategory(sp: SortingProfile, cat_id: str) -> None:
    sp.categories.pop(cat_id, None)
    to_remove = [k for k, v in sp.part_to_category.items() if v == cat_id]
    for k in to_remove:
        del sp.part_to_category[k]


def assignPart(sp: SortingProfile, part_key: str, cat_id: str) -> None:
    sp.part_to_category[part_key] = cat_id


def unassignPart(sp: SortingProfile, part_key: str) -> None:
    sp.part_to_category.pop(part_key, None)


def assignBulkByRebrickableCategory(
    sp: SortingProfile, parts: dict[str, dict], rebrickable_cat_id: int, internal_cat_id: str
) -> int:
    count = 0
    for pnum, part_data in parts.items():
        if part_data.get("part_cat_id") == rebrickable_cat_id:
            bl_ids = part_data.get("external_ids", {}).get("BrickLink", [])
            part_key = f"any_color-{bl_ids[0]}" if bl_ids else f"any_color-{pnum}"
            sp.part_to_category[part_key] = internal_cat_id
            count += 1
    return count
