import json
import os
import tempfile
import uuid
from datetime import datetime, timezone


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
    categories: dict
    rules: list[dict]
    part_to_category: dict[str, str]

    def __init__(self):
        self.categories = {}
        self.rules = []
        self.part_to_category = {}
        self.default_category_id = "misc"
        self.fallback_mode = {"rebrickable_categories": False, "by_color": False}


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
    sp.categories = data.get("categories", {})
    sp.rules = data.get("rules", [])
    _migrateRules(sp.rules)
    sp.part_to_category = data.get("part_to_category", {})
    sp.fallback_mode = data.get("fallback_mode", {"rebrickable_categories": False, "by_color": False})
    return sp


def _migrateRules(rules):
    for rule in rules:
        rule.pop("priority", None)
        if "children" not in rule:
            rule["children"] = []
        if "match_mode" not in rule:
            rule["match_mode"] = "all"
        if "disabled" not in rule:
            rule["disabled"] = False
        # migrate old condition tree format to flat list
        if isinstance(rule.get("conditions"), dict):
            rule["conditions"] = _flattenConditionTree(rule["conditions"])
        if not isinstance(rule.get("conditions"), list):
            rule["conditions"] = []
        _migrateRules(rule["children"])


def _flattenConditionTree(tree):
    if tree.get("type") == "predicate":
        return [{"id": tree.get("id", str(uuid.uuid4())), "field": tree["field"], "op": tree["op"], "value": tree["value"]}]
    predicates = []
    for child in tree.get("children", []):
        predicates.extend(_flattenConditionTree(child))
    return predicates


def atomicWriteJson(file_path: str, data: dict) -> None:
    dir_path = os.path.dirname(os.path.abspath(file_path))
    base_name = os.path.basename(file_path)
    fd, temp_path = tempfile.mkstemp(prefix=f".{base_name}.", suffix=".tmp", dir=dir_path)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, file_path)
    except Exception:
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass
        raise


def saveSortingProfile(profiles_dir: str, sp: SortingProfile) -> str:
    sp.updated_at = datetime.now(timezone.utc).isoformat()
    out = {
        "id": sp.id,
        "name": sp.name,
        "description": sp.description,
        "created_at": sp.created_at,
        "updated_at": sp.updated_at,
        "default_category_id": sp.default_category_id,
        "categories": sp.categories,
        "rules": sp.rules,
        "part_to_category": sp.part_to_category,
        "fallback_mode": sp.fallback_mode,
    }
    os.makedirs(profiles_dir, exist_ok=True)
    file_path = os.path.join(profiles_dir, f"{sp.id}.json")
    atomicWriteJson(file_path, out)
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


def _findRuleInList(rules, rule_id):
    for rule in rules:
        if rule["id"] == rule_id:
            return rule
        found = _findRuleInList(rule.get("children", []), rule_id)
        if found:
            return found
    return None


def _findParentList(rules, rule_id):
    for i, rule in enumerate(rules):
        if rule["id"] == rule_id:
            return rules, i
        result = _findParentList(rule.get("children", []), rule_id)
        if result:
            return result
    return None


def _collectAncestorChecks(rules, rule_id):
    for rule in rules:
        if rule["id"] == rule_id:
            return []
        children = rule.get("children", [])
        result = _collectAncestorChecks(children, rule_id)
        if result is not None:
            checks = [{"conditions": rule.get("conditions", []), "match_mode": rule.get("match_mode", "all")}]
            checks.extend(result)
            return checks
    return None


def addRule(sp: SortingProfile, name: str, conditions: list, match_mode: str = "all", parent_id: str | None = None) -> str | None:
    rule_id = str(uuid.uuid4())
    rule = {
        "id": rule_id,
        "name": name,
        "match_mode": match_mode,
        "conditions": conditions,
        "children": [],
        "disabled": False,
    }
    if parent_id:
        parent = _findRuleInList(sp.rules, parent_id)
        if parent is None:
            return None
        parent["children"].append(rule)
    else:
        sp.rules.append(rule)
    return rule_id


def removeRule(sp: SortingProfile, rule_id: str) -> bool:
    result = _findParentList(sp.rules, rule_id)
    if not result:
        return False
    parent_list, idx = result
    parent_list.pop(idx)
    return True


def updateRule(sp: SortingProfile, rule_id: str, **fields) -> bool:
    rule = _findRuleInList(sp.rules, rule_id)
    if not rule:
        return False
    for k, v in fields.items():
        if k not in ("id", "children"):
            rule[k] = v
    return True


def getRule(sp: SortingProfile, rule_id: str) -> dict | None:
    return _findRuleInList(sp.rules, rule_id)


def getAncestorChecks(sp: SortingProfile, rule_id: str) -> list:
    result = _collectAncestorChecks(sp.rules, rule_id)
    return result or []


def reorderRules(sp: SortingProfile, rule_ids: list[str]):
    id_to_rule = {r["id"]: r for r in sp.rules}
    reordered = [id_to_rule[rid] for rid in rule_ids if rid in id_to_rule]
    for leftover in sp.rules:
        if leftover["id"] not in id_to_rule or leftover not in reordered:
            if leftover not in reordered:
                reordered.append(leftover)
    sp.rules = reordered


def reorderChildren(sp: SortingProfile, parent_id: str, rule_ids: list[str]):
    parent = _findRuleInList(sp.rules, parent_id)
    if not parent:
        return False
    children = parent.get("children", [])
    id_to_child = {c["id"]: c for c in children}
    reordered = [id_to_child[rid] for rid in rule_ids if rid in id_to_child]
    for leftover in children:
        if leftover not in reordered:
            reordered.append(leftover)
    parent["children"] = reordered
    return True
