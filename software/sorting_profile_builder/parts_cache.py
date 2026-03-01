import os
import threading
import time
import requests

from global_config import GlobalConfig, REBRICKABLE_BASE_URL, REBRICKABLE_PAGE_SIZE
from db import (
    upsertCategories, upsertColors, upsertParts, setMeta,
    reloadPartsData, importBrickstoreDb, syncBricklinkPrices, PartsData,
)

THROTTLE_SECONDS = 1.1


class SyncManager:
    running: bool
    stop_requested: bool
    last_message: str
    pages_fetched: int
    progress_current: int | None
    progress_total: int | None
    sync_type: str | None
    error: str | None

    def __init__(self):
        self.running = False
        self.stop_requested = False
        self.last_message = ""
        self.pages_fetched = 0
        self.progress_current = None
        self.progress_total = None
        self.sync_type = None
        self.error = None
        self._lock = threading.Lock()
        self._last_request_time = 0
        self._request_count = 0

    def getStatus(self, parts_data: PartsData) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "last_message": self.last_message,
                "pages_fetched": self.pages_fetched,
                "sync_type": self.sync_type,
                "progress_current": self.progress_current,
                "progress_total": self.progress_total,
                "cached_parts": len(parts_data.parts),
                "cached_categories": len(parts_data.categories),
                "cached_bricklink_categories": len(parts_data.bricklink_categories),
                "cached_colors": len(parts_data.colors),
                "api_total": parts_data.api_total_parts,
                "error": self.error,
            }

    def requestStop(self) -> None:
        with self._lock:
            if self.running:
                self.stop_requested = True

    def startPartsSync(self, gc, conn, parts_data) -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.stop_requested = False
            self.pages_fetched = 0
            self.progress_current = len(parts_data.parts)
            self.progress_total = parts_data.api_total_parts
            self.sync_type = "parts"
            self.error = None
            self.last_message = "Starting parts sync..."
        t = threading.Thread(target=self._syncPartsLoop, args=(gc, conn, parts_data), daemon=True)
        t.start()
        return True

    def startCategoriesSync(self, gc, conn, parts_data) -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.stop_requested = False
            self.pages_fetched = 0
            self.progress_current = None
            self.progress_total = None
            self.sync_type = "categories"
            self.error = None
            self.last_message = "Syncing categories..."
        t = threading.Thread(target=self._syncCategoriesOnce, args=(gc, conn, parts_data), daemon=True)
        t.start()
        return True

    def startColorsSync(self, gc, conn, parts_data) -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.stop_requested = False
            self.pages_fetched = 0
            self.progress_current = None
            self.progress_total = None
            self.sync_type = "colors"
            self.error = None
            self.last_message = "Syncing colors..."
        t = threading.Thread(target=self._syncColorsOnce, args=(gc, conn, parts_data), daemon=True)
        t.start()
        return True

    def startBrickstoreImport(self, gc, conn, parts_data) -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.stop_requested = False
            self.pages_fetched = 0
            self.progress_current = None
            self.progress_total = None
            self.sync_type = "brickstore"
            self.error = None
            self.last_message = "Importing BrickStore DB..."
        t = threading.Thread(target=self._importBrickstoreOnce, args=(gc, conn, parts_data), daemon=True)
        t.start()
        return True

    def startPriceSync(self, gc, conn, parts_data) -> bool:
        with self._lock:
            if self.running:
                return False
            if not gc.bl_affiliate_api_key:
                self.error = "BL_AFFILIATE_API_KEY not set"
                return False
            self.running = True
            self.stop_requested = False
            self.pages_fetched = 0
            self.progress_current = 0
            self.progress_total = None
            self.sync_type = "prices"
            self.error = None
            self.last_message = "Starting BrickLink price sync..."
        t = threading.Thread(target=self._syncPricesLoop, args=(gc, conn, parts_data), daemon=True)
        t.start()
        return True

    def _throttle(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < THROTTLE_SECONDS:
            time.sleep(THROTTLE_SECONDS - elapsed)
        self._last_request_time = time.time()
        self._request_count += 1
        print(f"[rebrickable] request #{self._request_count}")

    def _syncPartsLoop(self, gc, conn, parts_data) -> None:
        try:
            while True:
                with self._lock:
                    if self.stop_requested:
                        self.last_message = f"Stopped after {self.pages_fetched} pages"
                        break
                result = _syncPartsPage(gc, conn, parts_data, self._throttle)
                with self._lock:
                    self.pages_fetched += 1
                    pct = round((result["cached"] / result["total"]) * 100) if result["total"] else 0
                    self.progress_current = result["cached"]
                    self.progress_total = result["total"]
                    self.last_message = f'{result["cached"]} / {result["total"]} parts ({pct}%)'
                if result["done"]:
                    with self._lock:
                        self.last_message = f'Sync complete! {result["cached"]} parts'
                    reloadPartsData(conn, parts_data)
                    break
        except Exception as e:
            with self._lock:
                self.error = str(e)
                self.last_message = f"Error: {e}"
        finally:
            with self._lock:
                self.running = False
                self.stop_requested = False
                self.sync_type = None

    def _syncCategoriesOnce(self, gc, conn, parts_data) -> None:
        try:
            count = _syncCategories(gc, conn, self._throttle)
            reloadPartsData(conn, parts_data)
            with self._lock:
                self.last_message = f"Synced {count} categories"
        except Exception as e:
            with self._lock:
                self.error = str(e)
                self.last_message = f"Error: {e}"
        finally:
            with self._lock:
                self.running = False
                self.sync_type = None

    def _syncColorsOnce(self, gc, conn, parts_data) -> None:
        try:
            count = _syncColors(gc, conn, self._throttle)
            reloadPartsData(conn, parts_data)
            with self._lock:
                self.last_message = f"Synced {count} colors"
        except Exception as e:
            with self._lock:
                self.error = str(e)
                self.last_message = f"Error: {e}"
        finally:
            with self._lock:
                self.running = False
                self.sync_type = None

    def _importBrickstoreOnce(self, gc, conn, parts_data) -> None:
        try:
            if not os.path.exists(gc.brickstore_db_path):
                raise FileNotFoundError(f"BrickStore DB not found: {gc.brickstore_db_path}")
            result = importBrickstoreDb(conn, gc.brickstore_db_path)
            reloadPartsData(conn, parts_data)
            with self._lock:
                self.last_message = (
                    f"Imported {result['categories']} categories, "
                    f"{result['items']} items ({result['skipped']} skipped)"
                )
        except Exception as e:
            with self._lock:
                self.error = str(e)
                self.last_message = f"Error: {e}"
        finally:
            with self._lock:
                self.running = False
                self.sync_type = None


    def _syncPricesLoop(self, gc, conn, parts_data) -> None:
        try:
            result = syncBricklinkPrices(
                conn,
                gc.bl_affiliate_api_key,
                should_stop_fn=self._shouldStop,
                progress_fn=self._updateProgress,
            )
            reloadPartsData(conn, parts_data)
            with self._lock:
                if result["stopped"]:
                    self.last_message = (
                        f"Stopped price sync: {result['updated']} / {result['total']} updated "
                        f"({result['batches']} batches)"
                    )
                else:
                    self.last_message = (
                        f"Price sync complete: {result['updated']} / {result['total']} updated "
                        f"({result['batches']} batches)"
                    )
        except Exception as e:
            with self._lock:
                self.error = str(e)
                self.last_message = f"Error: {e}"
        finally:
            with self._lock:
                self.running = False
                self.stop_requested = False
                self.sync_type = None

    def _shouldStop(self) -> bool:
        with self._lock:
            return self.stop_requested

    def _updateProgress(self, current, total, message) -> None:
        with self._lock:
            self.progress_current = current
            self.progress_total = total
            self.last_message = message


def _syncCategories(gc, conn, throttle_fn):
    throttle_fn()
    url = f"{REBRICKABLE_BASE_URL}/part_categories/"
    resp = requests.get(url, params={"key": gc.rebrickable_api_key, "page_size": 1000})
    resp.raise_for_status()
    data = resp.json()
    cat_list = []
    for cat_data in data.get("results", []):
        cat_list.append({
            "id": cat_data["id"],
            "name": cat_data["name"],
            "part_count": cat_data["part_count"],
        })
    upsertCategories(conn, cat_list)
    return len(cat_list)


def _syncColors(gc, conn, throttle_fn):
    throttle_fn()
    url = f"{REBRICKABLE_BASE_URL}/colors/"
    resp = requests.get(url, params={"key": gc.rebrickable_api_key, "page_size": 1000})
    resp.raise_for_status()
    data = resp.json()
    color_list = []
    for color_data in data.get("results", []):
        color_list.append(color_data)
    upsertColors(conn, color_list)
    return len(color_list)


def _syncPartsPage(gc, conn, parts_data, throttle_fn):
    throttle_fn()
    page_num = (len(parts_data.parts) // REBRICKABLE_PAGE_SIZE) + 1
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
    parts_list = []
    for part_data in data.get("results", []):
        pnum = part_data["part_num"]
        if pnum not in parts_data.parts:
            parts_list.append(part_data)
    upsertParts(conn, parts_list)
    setMeta(conn, "api_total_parts", str(total))
    parts_data.api_total_parts = total
    # update in-memory count
    cached = conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0]
    done = data.get("next") is None
    return {"fetched": len(parts_list), "total": total, "cached": cached, "done": done}
