import os
import threading
import time
from datetime import datetime, timezone

import requests

from .db import (
    upsertCategories, upsertColors, upsertParts, setMeta,
    upsertCatalogSyncState, reloadPartsData, importBrickstoreDb,
    syncBricklinkPrices, upsertPartGeometry, PartsData,
)

REBRICKABLE_BASE_URL = "https://rebrickable.com/api/v3/lego"
REBRICKABLE_PAGE_SIZE = 1000
THROTTLE_SECONDS = 1.1
REQUEST_TIMEOUT_SECONDS = 30
# Transient HTTP statuses worth retrying rather than aborting a long sync.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRY_BACKOFF_SCHEDULE = (2, 5, 15, 30, 60)
MAX_REQUEST_RETRIES = len(RETRY_BACKOFF_SCHEDULE)


def _nowIso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _interruptibleSleep(seconds: float, should_stop=None) -> None:
    slept = 0.0
    while slept < seconds:
        if should_stop and should_stop():
            return
        chunk = min(1.0, seconds - slept)
        time.sleep(chunk)
        slept += chunk


def _requestJson(url, params, throttle_fn, should_stop=None, on_retry=None):
    # Retries transient failures (rate limits, 5xx, network blips) with backoff so
    # a single hiccup doesn't kill a multi-minute paginated sync. The throttle keeps
    # us under Rebrickable's steady-state rate; this handles the spikes.
    attempt = 0
    while True:
        throttle_fn()
        resp = None
        retryable = True
        error: Exception | None = None
        try:
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            error = exc
        else:
            if resp.ok:
                return resp.json()
            retryable = resp.status_code in RETRYABLE_STATUSES
            error = requests.HTTPError(
                f"{resp.status_code} {resp.reason} for url: {resp.url}", response=resp
            )

        if not retryable or attempt >= MAX_REQUEST_RETRIES:
            raise error

        delay = RETRY_BACKOFF_SCHEDULE[min(attempt, len(RETRY_BACKOFF_SCHEDULE) - 1)]
        if resp is not None:
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = max(delay, int(retry_after))
        attempt += 1
        if on_retry:
            on_retry(f"Transient error ({error}); retry {attempt}/{MAX_REQUEST_RETRIES} in {delay}s")
        _interruptibleSleep(delay, should_stop)
        if should_stop and should_stop():
            raise error


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

    def startPartsSync(self, gc, conn, parts_data, on_complete=None, on_error=None) -> bool:
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
            self._markRunning(conn, "parts")
        t = threading.Thread(target=self._syncPartsLoop, args=(gc, conn, parts_data, on_complete, on_error), daemon=True)
        t.start()
        return True

    def startCategoriesSync(self, gc, conn, parts_data, on_complete=None, on_error=None) -> bool:
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
            self._markRunning(conn, "categories")
        t = threading.Thread(target=self._syncCategoriesOnce, args=(gc, conn, parts_data, on_complete, on_error), daemon=True)
        t.start()
        return True

    def startColorsSync(self, gc, conn, parts_data, on_complete=None, on_error=None) -> bool:
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
            self._markRunning(conn, "colors")
        t = threading.Thread(target=self._syncColorsOnce, args=(gc, conn, parts_data, on_complete, on_error), daemon=True)
        t.start()
        return True

    def startBrickstoreImport(self, gc, conn, parts_data, on_complete=None, on_error=None) -> bool:
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
            self._markRunning(conn, "brickstore")
        t = threading.Thread(target=self._importBrickstoreOnce, args=(gc, conn, parts_data, on_complete, on_error), daemon=True)
        t.start()
        return True

    def startPriceSync(self, gc, conn, parts_data, on_complete=None, on_error=None) -> bool:
        with self._lock:
            if self.running:
                return False
            if not gc.bla_api_key:
                self.error = "BLA_API_KEY not set"
                return False
            self.running = True
            self.stop_requested = False
            self.pages_fetched = 0
            self.progress_current = 0
            self.progress_total = None
            self.sync_type = "prices"
            self.error = None
            self.last_message = "Starting BrickLink price sync..."
            self._markRunning(conn, "prices")
        t = threading.Thread(target=self._syncPricesLoop, args=(gc, conn, parts_data, on_complete, on_error), daemon=True)
        t.start()
        return True

    def startGeometrySync(self, gc, conn, parts_data, on_complete=None, on_error=None) -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.stop_requested = False
            self.pages_fetched = 0
            self.progress_current = 0
            self.progress_total = None
            self.sync_type = "geometry"
            self.error = None
            self.last_message = "Preparing LDraw geometry..."
            self._markRunning(conn, "geometry")
        t = threading.Thread(target=self._runGeometrySync, args=(gc, conn, parts_data, on_complete, on_error), daemon=True)
        t.start()
        return True

    def _runGeometrySync(self, gc, conn, parts_data, on_complete=None, on_error=None) -> None:
        try:
            # lazy import so the backend still boots without numpy/scipy installed
            from . import ldraw_geometry as lg
            self._note(conn, "geometry", "Ensuring LDraw library is present...")
            ldraw_root = lg.ensureLibrary(gc.ldraw_library_dir)
            result = lg.computeAllGeometry(
                conn, ldraw_root, upsertPartGeometry, _nowIso(),
                progress_fn=self._updateProgress, should_stop_fn=self._shouldStop,
            )
            with self._lock:
                if result["stopped"]:
                    self.last_message = (
                        f"Stopped geometry: {result['computed']} / {result['total']} computed"
                    )
                    self._persist(
                        conn, "geometry", status="stopped", last_message=self.last_message,
                        progress_current=result["computed"], progress_total=result["total"],
                    )
                else:
                    self.last_message = (
                        f"Geometry complete: {result['computed']} / {result['total']} parts "
                        f"(direct {result['direct']}, parent {result['parent']})"
                    )
                    self._persist(
                        conn, "geometry", status="completed", completed_at=_nowIso(),
                        last_message=self.last_message, error=None,
                        progress_current=result["computed"], progress_total=result["total"],
                    )
            if not result["stopped"]:
                self._invoke_callback(on_complete)
        except Exception as e:
            with self._lock:
                self.error = str(e)
                self.last_message = f"Error: {e}"
                self._persist(conn, "geometry", status="error", error=str(e), last_message=self.last_message)
            self._invoke_callback(on_error, e)
        finally:
            with self._lock:
                self.running = False
                self.stop_requested = False
                self.sync_type = None

    def _invoke_callback(self, callback, *args) -> None:
        if not callable(callback):
            return
        try:
            callback(*args)
        except Exception as exc:
            print(f"[sync] callback failed: {exc}")

    def _persist(self, conn, sync_type, **fields) -> None:
        fields.setdefault("updated_at", _nowIso())
        try:
            upsertCatalogSyncState(conn, sync_type, **fields)
        except Exception as exc:
            print(f"[sync] failed to persist {sync_type} state: {exc}")

    def _note(self, conn, sync_type, message) -> None:
        with self._lock:
            self.last_message = message
        self._persist(conn, sync_type, last_message=message)

    def _markRunning(self, conn, sync_type) -> None:
        self._persist(
            conn,
            sync_type,
            status="running",
            started_at=_nowIso(),
            pages_fetched=self.pages_fetched,
            progress_current=self.progress_current,
            progress_total=self.progress_total,
            last_message=self.last_message,
            error=None,
            completed_at=None,
        )

    def _throttle(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < THROTTLE_SECONDS:
            time.sleep(THROTTLE_SECONDS - elapsed)
        self._last_request_time = time.time()
        self._request_count += 1
        print(f"[rebrickable] request #{self._request_count}")

    def _syncPartsLoop(self, gc, conn, parts_data, on_complete=None, on_error=None) -> None:
        try:
            while True:
                with self._lock:
                    if self.stop_requested:
                        self.last_message = f"Stopped after {self.pages_fetched} pages"
                        self._persist(conn, "parts", status="stopped", last_message=self.last_message)
                        break
                result = _syncPartsPage(
                    gc, conn, parts_data, self._throttle,
                    should_stop=self._shouldStop,
                    on_retry=lambda msg: self._note(conn, "parts", msg),
                )
                with self._lock:
                    self.pages_fetched += 1
                    pct = round((result["cached"] / result["total"]) * 100) if result["total"] else 0
                    self.progress_current = result["cached"]
                    self.progress_total = result["total"]
                    self.last_message = f'{result["cached"]} / {result["total"]} parts ({pct}%)'
                    self._persist(
                        conn, "parts", status="running", error=None,
                        progress_current=result["cached"], progress_total=result["total"],
                        pages_fetched=self.pages_fetched, last_message=self.last_message,
                    )
                if result["done"]:
                    with self._lock:
                        self.last_message = f'Sync complete! {result["cached"]} parts'
                        self._persist(
                            conn, "parts", status="completed", completed_at=_nowIso(),
                            progress_current=result["cached"], progress_total=result["total"],
                            last_message=self.last_message, error=None,
                        )
                    reloadPartsData(conn, parts_data)
                    self._invoke_callback(on_complete)
                    break
        except Exception as e:
            with self._lock:
                self.error = str(e)
                self.last_message = f"Error: {e}"
                self._persist(conn, "parts", status="error", error=str(e), last_message=self.last_message)
            self._invoke_callback(on_error, e)
        finally:
            with self._lock:
                self.running = False
                self.stop_requested = False
                self.sync_type = None

    def _syncCategoriesOnce(self, gc, conn, parts_data, on_complete=None, on_error=None) -> None:
        try:
            count = _syncCategories(
                gc, conn, self._throttle,
                should_stop=self._shouldStop,
                on_retry=lambda msg: self._note(conn, "categories", msg),
            )
            reloadPartsData(conn, parts_data)
            with self._lock:
                self.last_message = f"Synced {count} categories"
                self._persist(
                    conn, "categories", status="completed", completed_at=_nowIso(),
                    progress_current=count, progress_total=count,
                    last_message=self.last_message, error=None,
                )
            self._invoke_callback(on_complete)
        except Exception as e:
            with self._lock:
                self.error = str(e)
                self.last_message = f"Error: {e}"
                self._persist(conn, "categories", status="error", error=str(e), last_message=self.last_message)
            self._invoke_callback(on_error, e)
        finally:
            with self._lock:
                self.running = False
                self.sync_type = None

    def _syncColorsOnce(self, gc, conn, parts_data, on_complete=None, on_error=None) -> None:
        try:
            count = _syncColors(
                gc, conn, self._throttle,
                should_stop=self._shouldStop,
                on_retry=lambda msg: self._note(conn, "colors", msg),
            )
            reloadPartsData(conn, parts_data)
            with self._lock:
                self.last_message = f"Synced {count} colors"
                self._persist(
                    conn, "colors", status="completed", completed_at=_nowIso(),
                    progress_current=count, progress_total=count,
                    last_message=self.last_message, error=None,
                )
            self._invoke_callback(on_complete)
        except Exception as e:
            with self._lock:
                self.error = str(e)
                self.last_message = f"Error: {e}"
                self._persist(conn, "colors", status="error", error=str(e), last_message=self.last_message)
            self._invoke_callback(on_error, e)
        finally:
            with self._lock:
                self.running = False
                self.sync_type = None

    def _importBrickstoreOnce(self, gc, conn, parts_data, on_complete=None, on_error=None) -> None:
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
                self._persist(
                    conn, "brickstore", status="completed", completed_at=_nowIso(),
                    last_message=self.last_message, error=None,
                )
            self._invoke_callback(on_complete)
        except Exception as e:
            with self._lock:
                self.error = str(e)
                self.last_message = f"Error: {e}"
                self._persist(conn, "brickstore", status="error", error=str(e), last_message=self.last_message)
            self._invoke_callback(on_error, e)
        finally:
            with self._lock:
                self.running = False
                self.sync_type = None


    def _syncPricesLoop(self, gc, conn, parts_data, on_complete=None, on_error=None) -> None:
        try:
            result = syncBricklinkPrices(
                conn,
                gc.bla_api_key,
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
                    self._persist(
                        conn, "prices", status="stopped", last_message=self.last_message,
                        progress_current=result["updated"], progress_total=result["total"],
                    )
                else:
                    self.last_message = (
                        f"Price sync complete: {result['updated']} / {result['total']} updated "
                        f"({result['batches']} batches)"
                    )
                    self._persist(
                        conn, "prices", status="completed", completed_at=_nowIso(),
                        last_message=self.last_message, error=None,
                        progress_current=result["updated"], progress_total=result["total"],
                    )
            if not result["stopped"]:
                self._invoke_callback(on_complete)
        except Exception as e:
            with self._lock:
                self.error = str(e)
                self.last_message = f"Error: {e}"
                self._persist(conn, "prices", status="error", error=str(e), last_message=self.last_message)
            self._invoke_callback(on_error, e)
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


def _syncCategories(gc, conn, throttle_fn, should_stop=None, on_retry=None):
    url = f"{REBRICKABLE_BASE_URL}/part_categories/"
    data = _requestJson(
        url, {"key": gc.rebrickable_api_key, "page_size": 1000},
        throttle_fn, should_stop=should_stop, on_retry=on_retry,
    )
    cat_list = []
    for cat_data in data.get("results", []):
        cat_list.append({
            "id": cat_data["id"],
            "name": cat_data["name"],
            "part_count": cat_data["part_count"],
        })
    upsertCategories(conn, cat_list)
    return len(cat_list)


def _syncColors(gc, conn, throttle_fn, should_stop=None, on_retry=None):
    url = f"{REBRICKABLE_BASE_URL}/colors/"
    data = _requestJson(
        url, {"key": gc.rebrickable_api_key, "page_size": 1000},
        throttle_fn, should_stop=should_stop, on_retry=on_retry,
    )
    color_list = []
    for color_data in data.get("results", []):
        color_list.append(color_data)
    upsertColors(conn, color_list)
    return len(color_list)


def _syncPartsPage(gc, conn, parts_data, throttle_fn, should_stop=None, on_retry=None):
    # Page must advance off the persisted DB count, not parts_data.parts: the
    # in-memory cache is only refreshed by reloadPartsData() after the whole
    # sync finishes, so deriving the page from it pins page_num at 1 and
    # re-fetches page 1 forever (which Rebrickable eventually 429s).
    cached_before = conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0]
    page_num = (cached_before // REBRICKABLE_PAGE_SIZE) + 1
    url = f"{REBRICKABLE_BASE_URL}/parts/"
    data = _requestJson(
        url,
        {
            "key": gc.rebrickable_api_key,
            "page_size": REBRICKABLE_PAGE_SIZE,
            "inc_part_details": 1,
            "page": page_num,
        },
        throttle_fn, should_stop=should_stop, on_retry=on_retry,
    )
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
