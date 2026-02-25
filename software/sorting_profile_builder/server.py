import os
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from global_config import GlobalConfig
from parts_cache import PartsCache, SyncManager, searchParts
from sorting_profile import (
    SortingProfile, mkSortingProfile, loadSortingProfile, saveSortingProfile,
    listSortingProfiles, deleteSortingProfile, addCategory, removeCategory,
    assignPart, unassignPart, assignBulkByRebrickableCategory,
)

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")


def mkApp(gc: GlobalConfig, cache: PartsCache, sync: SyncManager) -> FastAPI:
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
            "cache_count": len(cache.parts),
            "cat_count": len(cache.categories),
            "color_count": len(cache.colors),
            "api_total": cache.api_total_parts,
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
            "rebrickable_categories": cache.categories,
            "rebrickable_colors": cache.colors,
        })

    # --- api: sync ---

    @app.get("/api/sync-status")
    def apiSyncStatus():
        return sync.getStatus(cache)

    @app.post("/api/sync-categories")
    def apiSyncCategories():
        started = sync.startCategoriesSync(gc, cache)
        if not started:
            raise HTTPException(409, "A sync is already running")
        return {"started": True}

    @app.post("/api/sync-colors")
    def apiSyncColors():
        started = sync.startColorsSync(gc, cache)
        if not started:
            raise HTTPException(409, "A sync is already running")
        return {"started": True}

    @app.post("/api/sync-parts")
    def apiSyncParts():
        started = sync.startPartsSync(gc, cache)
        if not started:
            raise HTTPException(409, "A sync is already running")
        return {"started": True}

    @app.post("/api/sync-stop")
    def apiSyncStop():
        sync.requestStop()
        return {"stopped": True}

    @app.get("/api/search-parts")
    def apiSearchParts(q: str = "", cat_id: int | None = None, limit: int = 50):
        if not q and cat_id is None:
            return {"results": []}
        results = searchParts(cache, q, category_filter=cat_id, limit=limit)
        return {"results": results}

    @app.get("/api/parts-by-category/{cat_id}")
    def apiPartsByCategory(cat_id: int, limit: int = 200):
        results = searchParts(cache, "", category_filter=cat_id, limit=limit)
        cat = cache.categories.get(cat_id)
        return {"results": results, "category": cat}

    # --- api: profiles ---

    @app.post("/api/profiles")
    def apiCreateProfile(name: str = Form(...), description: str = Form("")):
        sp = mkSortingProfile(name, description)
        fpath = saveSortingProfile(gc.profiles_dir, sp)
        return {"id": sp.id, "path": fpath}

    @app.delete("/api/profiles/{profile_id}")
    def apiDeleteProfile(profile_id: str):
        ok = deleteSortingProfile(gc.profiles_dir, profile_id)
        if not ok:
            raise HTTPException(404, "Profile not found")
        return {"deleted": True}

    # --- api: profile editing ---

    @app.post("/api/profile/{profile_id}/categories")
    def apiAddCategory(profile_id: str, name: str = Form(...)):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        cat_id = addCategory(sp, name)
        saveSortingProfile(gc.profiles_dir, sp)
        return {"id": cat_id, "name": name}

    @app.delete("/api/profile/{profile_id}/categories/{cat_id}")
    def apiRemoveCategory(profile_id: str, cat_id: str):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        removeCategory(sp, cat_id)
        saveSortingProfile(gc.profiles_dir, sp)
        return {"removed": True}

    @app.post("/api/profile/{profile_id}/assign")
    def apiAssignPart(profile_id: str, part_key: str = Form(...), cat_id: str = Form(...)):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        assignPart(sp, part_key, cat_id)
        saveSortingProfile(gc.profiles_dir, sp)
        return {"assigned": True}

    @app.post("/api/profile/{profile_id}/unassign")
    def apiUnassignPart(profile_id: str, part_key: str = Form(...)):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        unassignPart(sp, part_key)
        saveSortingProfile(gc.profiles_dir, sp)
        return {"unassigned": True}

    @app.post("/api/profile/{profile_id}/assign-bulk")
    def apiAssignBulk(
        profile_id: str,
        rebrickable_cat_id: int = Form(...),
        internal_cat_id: str = Form(...),
    ):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        count = assignBulkByRebrickableCategory(sp, cache.parts, rebrickable_cat_id, internal_cat_id)
        saveSortingProfile(gc.profiles_dir, sp)
        return {"assigned_count": count}

    @app.get("/api/profile/{profile_id}/stats")
    def apiProfileStats(profile_id: str):
        sp = _getOpenProfile(open_profile, gc, profile_id)
        return {
            "part_count": len(sp.part_to_category),
            "category_count": len(sp.categories),
        }

    return app


def _getOpenProfile(container: dict, gc: GlobalConfig, profile_id: str) -> SortingProfile:
    sp = container.get("profile")
    if sp is None or sp.id != profile_id:
        fpath = os.path.join(gc.profiles_dir, f"{profile_id}.json")
        if not os.path.exists(fpath):
            raise HTTPException(404, "Profile not found")
        sp = loadSortingProfile(fpath)
        container["profile"] = sp
    return sp
