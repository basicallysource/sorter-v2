import json
import os
import threading
import time
import requests

from global_config import GlobalConfig, REBRICKABLE_BASE_URL, REBRICKABLE_PAGE_SIZE

THROTTLE_SECONDS = 1.1


class SyncManager:
    running: bool
    stop_requested: bool
    last_message: str
    pages_fetched: int
    error: str | None

    def __init__(self):
        self.running = False
        self.stop_requested = False
        self.last_message = ""
        self.pages_fetched = 0
        self.error = None
        self._lock = threading.Lock()

    def getStatus(self, cache: "PartsCache") -> dict:
        with self._lock:
            return {
                "running": self.running,
                "last_message": self.last_message,
                "pages_fetched": self.pages_fetched,
                "cached_parts": len(cache.parts),
                "cached_categories": len(cache.categories),
                "cached_colors": len(cache.colors),
                "api_total": cache.api_total_parts,
                "error": self.error,
            }

    def requestStop(self) -> None:
        with self._lock:
            if self.running:
                self.stop_requested = True

    def startPartsSync(self, gc: GlobalConfig, cache: "PartsCache") -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.stop_requested = False
            self.pages_fetched = 0
            self.error = None
            self.last_message = "Starting parts sync..."
        t = threading.Thread(target=self._syncPartsLoop, args=(gc, cache), daemon=True)
        t.start()
        return True

    def startCategoriesSync(self, gc: GlobalConfig, cache: "PartsCache") -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.stop_requested = False
            self.error = None
            self.last_message = "Syncing categories..."
        t = threading.Thread(target=self._syncCategoriesOnce, args=(gc, cache), daemon=True)
        t.start()
        return True

    def startColorsSync(self, gc: GlobalConfig, cache: "PartsCache") -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.stop_requested = False
            self.error = None
            self.last_message = "Syncing colors..."
        t = threading.Thread(target=self._syncColorsOnce, args=(gc, cache), daemon=True)
        t.start()
        return True

    def _syncPartsLoop(self, gc: GlobalConfig, cache: "PartsCache") -> None:
        try:
            while True:
                with self._lock:
                    if self.stop_requested:
                        self.last_message = f"Stopped after {self.pages_fetched} pages ({len(cache.parts)} parts cached)"
                        break
                result = syncPartsPage(gc, cache)
                with self._lock:
                    self.pages_fetched += 1
                    pct = round((result["cached"] / result["total"]) * 100) if result["total"] else 0
                    self.last_message = f'{result["cached"]} / {result["total"]} parts ({pct}%)'
                if result["done"]:
                    with self._lock:
                        self.last_message = f'Sync complete! {result["cached"]} parts'
                    break
        except Exception as e:
            with self._lock:
                self.error = str(e)
                self.last_message = f"Error: {e}"
        finally:
            with self._lock:
                self.running = False
                self.stop_requested = False

    def _syncCategoriesOnce(self, gc: GlobalConfig, cache: "PartsCache") -> None:
        try:
            count = syncCategories(gc, cache)
            with self._lock:
                self.last_message = f"Synced {count} categories"
        except Exception as e:
            with self._lock:
                self.error = str(e)
                self.last_message = f"Error: {e}"
        finally:
            with self._lock:
                self.running = False

    def _syncColorsOnce(self, gc: GlobalConfig, cache: "PartsCache") -> None:
        try:
            count = syncColors(gc, cache)
            with self._lock:
                self.last_message = f"Synced {count} colors"
        except Exception as e:
            with self._lock:
                self.error = str(e)
                self.last_message = f"Error: {e}"
        finally:
            with self._lock:
                self.running = False


class PartsCache:
    categories: dict[int, dict]
    colors: dict[int, dict]
    parts: dict[str, dict]
    api_total_parts: int | None

    last_request_time: float
    request_count: int

    def __init__(self):
        self.categories = {}
        self.colors = {}
        self.parts = {}
        self.api_total_parts = None
        self.last_request_time = 0
        self.request_count = 0


def _throttle(cache: PartsCache) -> None:
    elapsed = time.time() - cache.last_request_time
    if elapsed < THROTTLE_SECONDS:
        time.sleep(THROTTLE_SECONDS - elapsed)
    cache.last_request_time = time.time()
    cache.request_count += 1
    print(f"[rebrickable] request #{cache.request_count}")


def loadPartsCache(gc: GlobalConfig) -> PartsCache:
    cache = PartsCache()
    if not os.path.exists(gc.parts_json_path):
        # init empty file
        with open(gc.parts_json_path, "w") as f:
            json.dump({"categories": {}, "parts": {}}, f)
        return cache
    try:
        with open(gc.parts_json_path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return cache
    for cat_id_str, cat_data in data.get("categories", {}).items():
        cache.categories[int(cat_id_str)] = cat_data
    for color_id_str, color_data in data.get("colors", {}).items():
        cache.colors[int(color_id_str)] = color_data
    cache.parts = data.get("parts", {})
    return cache


def savePartsCache(gc: GlobalConfig, cache: PartsCache) -> None:
    cats_out = {}
    for cat_id, cat_data in cache.categories.items():
        cats_out[str(cat_id)] = cat_data
    colors_out = {}
    for color_id, color_data in cache.colors.items():
        colors_out[str(color_id)] = color_data
    out = {"categories": cats_out, "colors": colors_out, "parts": cache.parts}
    with open(gc.parts_json_path, "w") as f:
        json.dump(out, f, indent=2)


def syncCategories(gc: GlobalConfig, cache: PartsCache) -> int:
    _throttle(cache)
    url = f"{REBRICKABLE_BASE_URL}/part_categories/"
    resp = requests.get(url, params={"key": gc.rebrickable_api_key, "page_size": 1000})
    resp.raise_for_status()
    data = resp.json()
    count = 0
    for cat_data in data.get("results", []):
        cat_id = cat_data["id"]
        cache.categories[cat_id] = {
            "id": cat_id,
            "name": cat_data["name"],
            "part_count": cat_data["part_count"],
        }
        count += 1
    savePartsCache(gc, cache)
    return count


def syncColors(gc: GlobalConfig, cache: PartsCache) -> int:
    _throttle(cache)
    url = f"{REBRICKABLE_BASE_URL}/colors/"
    resp = requests.get(url, params={"key": gc.rebrickable_api_key, "page_size": 1000})
    resp.raise_for_status()
    data = resp.json()
    count = 0
    for color_data in data.get("results", []):
        color_id = color_data["id"]
        cache.colors[color_id] = color_data
        count += 1
    savePartsCache(gc, cache)
    return count


def syncPartsPage(gc: GlobalConfig, cache: PartsCache) -> dict:
    _throttle(cache)
    page_num = (len(cache.parts) // REBRICKABLE_PAGE_SIZE) + 1
    url = f"{REBRICKABLE_BASE_URL}/parts/"
    resp = requests.get(url, params={
        "key": gc.rebrickable_api_key,
        "page_size": REBRICKABLE_PAGE_SIZE,
        "inc_part_details": 1,
        "page": page_num,
    })
    resp.raise_for_status()
    data = resp.json()
    total = data["count"]
    cache.api_total_parts = total
    fetched = 0
    for part_data in data.get("results", []):
        pnum = part_data["part_num"]
        if pnum not in cache.parts:
            cache.parts[pnum] = part_data
            fetched += 1
    savePartsCache(gc, cache)
    done = data.get("next") is None
    return {"fetched": fetched, "total": total, "cached": len(cache.parts), "done": done}


def searchParts(cache: PartsCache, query: str, category_filter: int | None = None, limit: int = 50) -> list[dict]:
    query_lower = query.lower().strip()
    results = []
    for pnum, part_data in cache.parts.items():
        if len(results) >= limit:
            break
        if category_filter is not None and part_data.get("part_cat_id") != category_filter:
            continue
        if not query_lower or _partMatchesQuery(pnum, part_data, query_lower):
            enriched = dict(part_data)
            cat_id = part_data.get("part_cat_id")
            cat = cache.categories.get(cat_id)
            enriched["_category_name"] = cat["name"] if cat else "Unknown"
            results.append(enriched)
    return results


def _partMatchesQuery(part_num: str, part_data: dict, query_lower: str) -> bool:
    if query_lower in part_num.lower():
        return True
    if query_lower in part_data.get("name", "").lower():
        return True
    for provider, ids in part_data.get("external_ids", {}).items():
        for ext_id in ids:
            if query_lower in str(ext_id).lower():
                return True
    return False
