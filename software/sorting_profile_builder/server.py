import os
import sqlite3
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from global_config import GlobalConfig
from db import PartsData, searchParts as dbSearchParts
from parts_cache import SyncManager
from sorting_profile import (
    SortingProfile, mkSortingProfile, loadSortingProfile, saveSortingProfile,
    listSortingProfiles, deleteSortingProfile,
    addRule, removeRule, updateRule, getRule, getAncestorChecks,
    reorderRules, reorderChildren, _migrateRules,
)
from rule_engine import mkCondition, generateProfile, previewRule, partsForCategory

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")


class RuleBody(BaseModel):
    name: str = "New Rule"
    match_mode: str = "all"
    conditions: list | None = None
    parent_id: str | None = None


class RuleUpdateBody(BaseModel):
    name: str | None = None
    match_mode: str | None = None
    disabled: bool | None = None


class ConditionBody(BaseModel):
    field: str = "name"
    op: str = "contains"
    value: str | int | list | None = ""


class ReorderBody(BaseModel):
    rule_ids: list[str]


class SaveRulesBody(BaseModel):
    rules: list


class FallbackModeBody(BaseModel):
    rebrickable_categories: bool = False
    by_color: bool = False


class PreviewBody(BaseModel):
    rules: list | None = None


class ConditionUpdateBody(BaseModel):
    field: str | None = None
    op: str | None = None
    value: str | int | list | None = None


def mkApp(gc: GlobalConfig, conn: sqlite3.Connection, parts_data: PartsData, sync: SyncManager) -> FastAPI:
    app = FastAPI(title="Sorting Profile Builder")
    templates = Jinja2Templates(directory=TEMPLATES_DIR)

    open_profile: dict = {"profile": None}

    # --- pages ---

    @app.get("/", response_class=HTMLResponse)
    def indexPage(request: Request):
        profiles = listSortingProfiles(gc.profiles_dir)
        return templates.TemplateResponse("index.html", {
            "request": request,
            "profiles": profiles,
            "cache_count": len(parts_data.parts),
            "cat_count": len(parts_data.categories),
            "color_count": len(parts_data.colors),
            "api_total": parts_data.api_total_parts,
        })

    @app.get("/profile/{profile_id}", response_class=HTMLResponse)
    def profilePage(request: Request, profile_id: str):
        fpath = os.path.join(gc.profiles_dir, f"{profile_id}.json")
        if not os.path.exists(fpath):
            raise HTTPException(404, "Profile not found")
        sp = loadSortingProfile(fpath)
        open_profile["profile"] = sp
        return templates.TemplateResponse("profile.html", {
            "request": request,
            "profile": sp,
            "profile_path": os.path.abspath(fpath),
            "rebrickable_categories": parts_data.categories,
            "bricklink_categories": parts_data.bricklink_categories,
            "rebrickable_colors": parts_data.colors,
            "fallback_mode": sp.fallback_mode,
        })

    # --- api: sync ---

    @app.get("/api/sync-status")
    def apiSyncStatus():
        return sync.getStatus(parts_data)

    @app.post("/api/sync-categories")
    def apiSyncCategories():
        started = sync.startCategoriesSync(gc, conn, parts_data)
        if not started:
            raise HTTPException(409, "A sync is already running")
        return {"started": True}

    @app.post("/api/sync-colors")
    def apiSyncColors():
        started = sync.startColorsSync(gc, conn, parts_data)
        if not started:
            raise HTTPException(409, "A sync is already running")
        return {"started": True}

    @app.post("/api/sync-parts")
    def apiSyncParts():
        started = sync.startPartsSync(gc, conn, parts_data)
        if not started:
            raise HTTPException(409, "A sync is already running")
        return {"started": True}

    @app.post("/api/import-brickstore")
    def apiImportBrickstore():
        started = sync.startBrickstoreImport(gc, conn, parts_data)
        if not started:
            raise HTTPException(409, "A sync is already running")
        return {"started": True}

    @app.post("/api/sync-prices")
    def apiSyncPrices():
        started = sync.startPriceSync(gc, conn, parts_data)
        if not started:
            if sync.error:
                raise HTTPException(400, sync.error)
            raise HTTPException(409, "A sync is already running")
        return {"started": True}

    @app.post("/api/sync-stop")
    def apiSyncStop():
        sync.requestStop()
        return {"stopped": True}

    @app.get("/api/search-parts")
    def apiSearchParts(q: str = "", cat_id: int | None = None, limit: int = 100, offset: int = 0):
        if not q and cat_id is None:
            return {"results": [], "total": 0, "offset": 0, "limit": limit}
        results, total = dbSearchParts(conn, q, cat_filter=cat_id, limit=limit, offset=offset)
        return {"results": results, "total": total, "offset": offset, "limit": limit}

    @app.get("/api/parts-by-category/{cat_id}")
    def apiPartsByCategory(cat_id: int, limit: int = 200):
        results, total = dbSearchParts(conn, "", cat_filter=cat_id, limit=limit, offset=0)
        cat = parts_data.categories.get(cat_id)
        return {"results": results, "category": cat}

    # --- api: profiles ---

    @app.post("/api/profiles")
    def apiCreateProfile(name: str = Form(...), description: str = Form("")):
        sp = mkSortingProfile(name, description)
        fpath = saveSortingProfile(gc.profiles_dir, sp)
        return {"id": sp.id, "path": fpath}

    @app.put("/api/profiles/{profile_id}/name")
    def apiRenameProfile(profile_id: str, name: str = Form(...)):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        sp.name = name
        saveSortingProfile(gc.profiles_dir, sp)
        return {"name": sp.name}

    @app.put("/api/profiles/{profile_id}/description")
    def apiUpdateProfileDescription(profile_id: str, description: str = Form("")):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        sp.description = description
        saveSortingProfile(gc.profiles_dir, sp)
        return {"description": sp.description}

    @app.delete("/api/profiles/{profile_id}")
    def apiDeleteProfile(profile_id: str):
        ok = deleteSortingProfile(gc.profiles_dir, profile_id)
        if not ok:
            raise HTTPException(404, "Profile not found")
        return {"deleted": True}

    # --- api: rules ---

    @app.post("/api/profile/{profile_id}/rules")
    def apiAddRule(profile_id: str, body: RuleBody):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        conditions = body.conditions or []
        rule_id = addRule(sp, body.name, conditions, match_mode=body.match_mode, parent_id=body.parent_id)
        if rule_id is None:
            raise HTTPException(404, "Parent rule not found")
        saveSortingProfile(gc.profiles_dir, sp)
        return {"id": rule_id, "rule": getRule(sp, rule_id)}

    @app.put("/api/profile/{profile_id}/rules/{rule_id}")
    def apiUpdateRule(profile_id: str, rule_id: str, body: RuleUpdateBody):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if not updateRule(sp, rule_id, **fields):
            raise HTTPException(404, "Rule not found")
        saveSortingProfile(gc.profiles_dir, sp)
        return {"rule": getRule(sp, rule_id)}

    @app.delete("/api/profile/{profile_id}/rules/{rule_id}")
    def apiDeleteRule(profile_id: str, rule_id: str):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        if not removeRule(sp, rule_id):
            raise HTTPException(404, "Rule not found")
        saveSortingProfile(gc.profiles_dir, sp)
        return {"removed": True}

    @app.put("/api/profile/{profile_id}/rules/reorder")
    def apiReorderRules(profile_id: str, body: ReorderBody):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        reorderRules(sp, body.rule_ids)
        saveSortingProfile(gc.profiles_dir, sp)
        return {"rules": sp.rules}

    @app.put("/api/profile/{profile_id}/rules/{rule_id}/children/reorder")
    def apiReorderChildren(profile_id: str, rule_id: str, body: ReorderBody):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        if not reorderChildren(sp, rule_id, body.rule_ids):
            raise HTTPException(404, "Parent rule not found")
        saveSortingProfile(gc.profiles_dir, sp)
        return {"rule": getRule(sp, rule_id)}

    @app.put("/api/profile/{profile_id}/rules")
    def apiSaveAllRules(profile_id: str, body: SaveRulesBody):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        sp.rules = body.rules
        _migrateRules(sp.rules)
        saveSortingProfile(gc.profiles_dir, sp)
        return {"rules": sp.rules}

    # --- api: conditions (flat list per rule) ---

    @app.post("/api/profile/{profile_id}/rules/{rule_id}/conditions")
    def apiAddCondition(profile_id: str, rule_id: str, body: ConditionBody):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        rule = getRule(sp, rule_id)
        if not rule:
            raise HTTPException(404, "Rule not found")
        cond = mkCondition(body.field, body.op, body.value)
        rule["conditions"].append(cond)
        saveSortingProfile(gc.profiles_dir, sp)
        return {"condition": cond, "rule": rule}

    @app.put("/api/profile/{profile_id}/rules/{rule_id}/conditions/{cond_id}")
    def apiUpdateCondition(profile_id: str, rule_id: str, cond_id: str, body: ConditionUpdateBody):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        rule = getRule(sp, rule_id)
        if not rule:
            raise HTTPException(404, "Rule not found")
        for cond in rule["conditions"]:
            if cond["id"] == cond_id:
                updates = {k: v for k, v in body.model_dump().items() if v is not None}
                cond.update(updates)
                saveSortingProfile(gc.profiles_dir, sp)
                return {"rule": rule}
        raise HTTPException(404, "Condition not found")

    @app.delete("/api/profile/{profile_id}/rules/{rule_id}/conditions/{cond_id}")
    def apiDeleteCondition(profile_id: str, rule_id: str, cond_id: str):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        rule = getRule(sp, rule_id)
        if not rule:
            raise HTTPException(404, "Rule not found")
        for i, cond in enumerate(rule["conditions"]):
            if cond["id"] == cond_id:
                rule["conditions"].pop(i)
                saveSortingProfile(gc.profiles_dir, sp)
                return {"rule": rule}
        raise HTTPException(404, "Condition not found")

    # --- api: fallback mode ---

    @app.put("/api/profile/{profile_id}/fallback-mode")
    def apiSetFallbackMode(profile_id: str, body: FallbackModeBody):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        sp.fallback_mode = {"rebrickable_categories": body.rebrickable_categories, "by_color": body.by_color}
        saveSortingProfile(gc.profiles_dir, sp)
        return {"fallback_mode": sp.fallback_mode}

    # --- api: generate & preview ---

    @app.post("/api/profile/{profile_id}/generate")
    def apiGenerate(profile_id: str):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        result = generateProfile(
            sp,
            parts_data.parts,
            parts_data.categories,
            parts_data.bricklink_categories,
            fallback_mode=sp.fallback_mode,
        )
        sp.part_to_category = result["part_to_category"]
        sp.categories = {}
        for rule in sp.rules:
            sp.categories[rule["id"]] = {"name": rule["name"]}
        for cat_id in result["stats"]["per_category"]:
            if cat_id.startswith("rb_"):
                rb_id = int(cat_id[3:])
                rb_cat = parts_data.categories.get(rb_id)
                sp.categories[cat_id] = {"name": rb_cat["name"] if rb_cat else cat_id}
        saveSortingProfile(gc.profiles_dir, sp)
        return result["stats"]

    @app.post("/api/profile/{profile_id}/preview")
    def apiPreviewProfile(profile_id: str, body: PreviewBody | None = None):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        original_rules = sp.rules
        if body and body.rules is not None:
            sp.rules = body.rules
            _migrateRules(sp.rules)
        result = generateProfile(
            sp,
            parts_data.parts,
            parts_data.categories,
            parts_data.bricklink_categories,
            fallback_mode=sp.fallback_mode,
        )
        sp.rules = original_rules
        return result["stats"]

    @app.post("/api/profile/{profile_id}/rules/{rule_id}/preview")
    def apiPreviewRule(profile_id: str, rule_id: str, body: PreviewBody | None = None, q: str = "", offset: int = 0, limit: int = 50):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        original_rules = sp.rules
        if body and body.rules is not None:
            sp.rules = body.rules
            _migrateRules(sp.rules)
        rule = getRule(sp, rule_id)
        if not rule:
            sp.rules = original_rules
            raise HTTPException(404, "Rule not found")
        ancestor_checks = getAncestorChecks(sp, rule_id)
        result = previewRule(
            rule,
            parts_data.parts,
            categories=parts_data.categories,
            bricklink_categories=parts_data.bricklink_categories,
            limit=limit,
            offset=offset,
            q=q,
            ancestor_checks=ancestor_checks,
        )
        sp.rules = original_rules
        return result

    @app.post("/api/profile/{profile_id}/category-parts/{cat_id:path}")
    def apiCategoryParts(profile_id: str, cat_id: str, body: PreviewBody | None = None, q: str = "", offset: int = 0, limit: int = 50):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        original_rules = sp.rules
        if body and body.rules is not None:
            sp.rules = body.rules
            _migrateRules(sp.rules)
        result = generateProfile(
            sp,
            parts_data.parts,
            parts_data.categories,
            parts_data.bricklink_categories,
            fallback_mode=sp.fallback_mode,
        )
        sp.rules = original_rules
        return partsForCategory(result["part_to_category"], cat_id, parts_data.parts, q=q, offset=offset, limit=limit)

    @app.get("/api/profile/{profile_id}/stats")
    def apiProfileStats(profile_id: str):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        return {
            "part_count": len(sp.part_to_category),
            "category_count": len(sp.rules),
            "rule_count": _countRules(sp.rules),
        }

    return app


def _countRules(rules):
    count = len(rules)
    for rule in rules:
        count += _countRules(rule.get("children", []))
    return count


def _getOpenProfile(container: dict, gc: GlobalConfig, profile_id: str) -> SortingProfile:
    sp = container.get("profile")
    if sp is None or sp.id != profile_id:
        fpath = os.path.join(gc.profiles_dir, f"{profile_id}.json")
        if not os.path.exists(fpath):
            raise HTTPException(404, "Profile not found")
        sp = loadSortingProfile(fpath)
        container["profile"] = sp
    return sp
