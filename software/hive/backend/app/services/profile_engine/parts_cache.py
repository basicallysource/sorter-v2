import json
import os
import threading
from collections import Counter
from datetime import datetime, timezone

from app.services.rebrickable_downloads import downloads, rows
from app.services.set_inventory import import_sets

from .db import (
    upsertCategories, upsertColors, importParts, setMeta,
    upsertCatalogSyncState, reloadPartsData, importBrickstoreDb,
    syncBricklinkPrices, upsertPartGeometry, PartsData,
)


def _nowIso() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    # The Rebrickable imports: each downloads its CSV files and imports them in
    # one go (seconds), so there is nothing to page, resume or stop.

    def startSetsSync(self, gc, conn, parts_data, on_complete=None, on_error=None) -> bool:
        return self._startImport("sets", _syncSets, gc, conn, parts_data, on_complete, on_error)

    def startCategoriesSync(self, gc, conn, parts_data, on_complete=None, on_error=None) -> bool:
        return self._startImport("categories", _syncCategories, gc, conn, parts_data, on_complete, on_error)

    def startColorsSync(self, gc, conn, parts_data, on_complete=None, on_error=None) -> bool:
        return self._startImport("colors", _syncColors, gc, conn, parts_data, on_complete, on_error)

    def startPartsSync(self, gc, conn, parts_data, on_complete=None, on_error=None) -> bool:
        return self._startImport("parts", _syncParts, gc, conn, parts_data, on_complete, on_error)

    def _startImport(self, sync_type, work, gc, conn, parts_data, on_complete, on_error) -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.stop_requested = False
            self.pages_fetched = 0
            self.progress_current = None
            self.progress_total = None
            self.sync_type = sync_type
            self.error = None
            self.last_message = f"Downloading Rebrickable's {sync_type}..."
            self._markRunning(conn, sync_type)
        t = threading.Thread(
            target=self._runImport, args=(sync_type, work, gc, conn, parts_data, on_complete, on_error), daemon=True
        )
        t.start()
        return True

    def _runImport(self, sync_type, work, gc, conn, parts_data, on_complete=None, on_error=None) -> None:
        try:
            message, count = work(gc, conn, parts_data, self._updateProgress)
            with self._lock:
                self.last_message = message
                self._persist(
                    conn, sync_type, status="completed", completed_at=_nowIso(),
                    progress_current=count, progress_total=count,
                    last_message=message, error=None,
                )
            self._invoke_callback(on_complete)
        except Exception as e:
            with self._lock:
                self.error = str(e)
                self.last_message = f"Error: {e}"
                self._persist(conn, sync_type, status="error", error=str(e), last_message=self.last_message)
            self._invoke_callback(on_error, e)
        finally:
            with self._lock:
                self.running = False
                self.sync_type = None

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


# ---------------------------------------------------------------------------
# The Rebrickable imports, from its CSV downloads. Each returns what to say
# about it and how many rows it brought.


def _syncSets(gc, conn, parts_data, progress_fn):
    # Its own connection, in one transaction: the shared one stays free for
    # state updates, and readers see the old sets until it commits.
    counts = import_sets(gc.db_path, progress_fn=progress_fn)
    sets = counts["rebrickable_sets"]
    return (
        f"Imported {sets} sets, {counts['rebrickable_themes']} themes, "
        f"{counts['rebrickable_inventory_parts']} inventory parts",
        sets,
    )


def _syncCategories(gc, conn, parts_data, progress_fn):
    with downloads("part_categories", "parts") as files:
        part_counts = Counter(cat_id for (cat_id,) in rows(files["parts"], ("part_cat_id",)))
        categories = [
            {"id": int(cat_id), "name": name, "part_count": part_counts[cat_id]}
            for cat_id, name in rows(files["part_categories"], ("id", "name"))
        ]
    upsertCategories(conn, categories)
    reloadPartsData(conn, parts_data)
    return f"Synced {len(categories)} categories", len(categories)


def _syncColors(gc, conn, parts_data, progress_fn):
    # The downloads have no BrickLink color IDs (what the API gave as
    # external_ids): a color keeps the ones it has, and a new one has none.
    kept = {color_id: json.loads(extra) for color_id, extra in conn.execute("SELECT id, extra FROM colors") if extra}
    with downloads("colors") as files:
        colors = [
            {**kept.get(int(color_id), {}), "id": int(color_id), "name": name, "rgb": rgb, "is_trans": bool(is_trans)}
            for color_id, name, rgb, is_trans in rows(files["colors"], ("id", "name", "rgb", "is_trans"))
        ]
    upsertColors(conn, colors)
    reloadPartsData(conn, parts_data)
    return f"Synced {len(colors)} colors", len(colors)


def _syncParts(gc, conn, parts_data, progress_fn):
    with downloads("parts") as files:
        total = importParts(conn, rows(files["parts"], ("part_num", "name", "part_cat_id")))
    setMeta(conn, "api_total_parts", str(total))
    reloadPartsData(conn, parts_data)
    return f"Synced {total} parts", total
