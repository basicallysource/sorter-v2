from __future__ import annotations

import csv
import io
import logging
import os
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

from app import roles
from app.config import settings
from app.errors import APIError
from app.services import bricklink
from app.services.profile_engine import db as profile_db
from app.services.profile_engine import parts_cache as profile_parts_cache
from app.services.profile_engine.compiler import CatalogIndex, Compiled, catalog_index, compile_document, rule_matches
from app.services import set_inventory

logger = logging.getLogger(__name__)

CUSTOM_SET_ANY_COLOR_ID = -1
PROFILE_CATALOG_SYNC_TYPES = ("sets", "categories", "colors", "parts", "brickstore", "prices", "geometry")
# All four come from Rebrickable's CSV downloads. Sets first: they need none
# of the others, an auto-sync stops at the first sync that fails, and the parts
# sync takes new parts' years and pictures from the sets.
PROFILE_CATALOG_AUTO_SYNC_TYPES = ("sets", "categories", "colors", "parts")
PROFILE_CATALOG_LAST_SYNC_META_PREFIX = "profile_catalog.last_sync."
# How often a process that does not run the syncs looks for one that finished
# in the process that does (see ProfileCatalogService.follow_syncs).
FOLLOW_SYNCS_INTERVAL_S = 60.0


def _ensure_parent_dir(path: str) -> None:
    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# What a catalog status and an auto-sync plan are made of, read from parts.db.
# Shared by the catalog service (which counts its in-memory copy) and
# CatalogLookup (which counts rows), so the two can never describe a sync
# differently.


def _sync_meta_key(sync_type: str) -> str:
    return f"{PROFILE_CATALOG_LAST_SYNC_META_PREFIX}{sync_type}"


def _last_synced_map(conn) -> dict[str, str | None]:
    """When each kind of sync last finished."""
    out: dict[str, str | None] = {}
    for sync_type in PROFILE_CATALOG_SYNC_TYPES:
        raw = profile_db.getMeta(conn, _sync_meta_key(sync_type))
        out[sync_type] = str(raw) if raw else None
    return out


def _types_status(conn, counts: dict[str, int], running_type: str | None) -> dict[str, dict[str, Any]]:
    persisted = profile_db.getAllCatalogSyncStates(conn)
    last_synced = _last_synced_map(conn)
    types: dict[str, dict[str, Any]] = {}
    for sync_type in PROFILE_CATALOG_SYNC_TYPES:
        state = dict(
            persisted.get(sync_type)
            or {
                "sync_type": sync_type,
                "status": "idle",
                "progress_current": None,
                "progress_total": None,
                "pages_fetched": 0,
                "last_message": None,
                "error": None,
                "started_at": None,
                "updated_at": None,
                "completed_at": None,
            }
        )
        # Whoever runs the sync is the source of truth for "is this one running
        # now"; persisted status can lag a tick behind a fresh start or stop,
        # and a row left 'running' by a process that died is not running.
        if running_type == sync_type:
            state["status"] = "running"
        elif state["status"] == "running":
            state["status"] = "interrupted"
        state["cached_count"] = counts.get(sync_type)
        state["last_synced_at"] = last_synced.get(sync_type)
        types[sync_type] = state
    return types


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_stale(last_synced_at: str | None, max_age_hours: int, now: datetime) -> bool:
    if max_age_hours <= 0:
        return False
    if not last_synced_at:
        return True
    parsed = _parse_timestamp(last_synced_at)
    if parsed is None:
        return True
    return now - parsed >= timedelta(hours=max_age_hours)


def auto_sync_plan(counts: dict[str, int], last_synced: dict[str, str | None], now: datetime) -> list[str]:
    """The kinds of sync the auto-sync would run now: every one that is empty
    or older than its PROFILE_CATALOG_AUTO_SYNC_*_MAX_AGE_HOURS, in order."""
    max_age_hours = {
        "sets": settings.PROFILE_CATALOG_AUTO_SYNC_SETS_MAX_AGE_HOURS,
        "categories": settings.PROFILE_CATALOG_AUTO_SYNC_CATEGORIES_MAX_AGE_HOURS,
        "colors": settings.PROFILE_CATALOG_AUTO_SYNC_COLORS_MAX_AGE_HOURS,
        "parts": settings.PROFILE_CATALOG_AUTO_SYNC_PARTS_MAX_AGE_HOURS,
    }
    return [
        sync_type
        for sync_type in PROFILE_CATALOG_AUTO_SYNC_TYPES
        if counts.get(sync_type, 0) <= 0 or _is_stale(last_synced.get(sync_type), max_age_hours[sync_type], now)
    ]


def bricklink_palette(colors: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """The BrickLink color palette, derived from the Rebrickable `colors`
    catalog's external ids (parts.db has no BrickLink-colors table).

    brickognize predictions and machine piece color_ids are in BrickLink
    color space, so this is the palette the color-labeling UI picks from.
    Each Rebrickable color carries a BrickLink ext_ids/ext_descrs pair; we
    flatten those to BL id + BL name and borrow the Rebrickable rgb/is_trans
    as the swatch. First Rebrickable mapping wins on a BL-id collision."""
    by_bl_id: dict[int, dict[str, Any]] = {}
    for rb_color_id, color in sorted(colors.items()):
        bricklink = color.get("external_ids", {}).get("BrickLink", {})
        if not isinstance(bricklink, dict):
            continue
        ext_ids = bricklink.get("ext_ids", [])
        ext_descrs = bricklink.get("ext_descrs", [])
        if not isinstance(ext_ids, list):
            continue
        for index, raw_bl_id in enumerate(ext_ids):
            try:
                bl_id = int(raw_bl_id)
            except (TypeError, ValueError):
                continue
            if bl_id in by_bl_id:
                continue
            descr = ext_descrs[index] if isinstance(ext_descrs, list) and index < len(ext_descrs) else None
            bl_name = descr[0] if isinstance(descr, list) and descr else color.get("name") or str(bl_id)
            by_bl_id[bl_id] = {
                "id": bl_id,
                "name": bl_name,
                "rgb": color.get("rgb"),
                "is_trans": bool(color.get("is_trans", False)),
                "rb_color_id": rb_color_id,
            }
    return [by_bl_id[bl_id] for bl_id in sorted(by_bl_id)]


def _bricklink_category_names(conn, item_nos: list[str]) -> dict[str, str]:
    ids = list({str(x) for x in item_nos if x})
    out: dict[str, str] = {}
    if not ids:
        return out
    chunk = 900
    for start in range(0, len(ids), chunk):
        batch = ids[start : start + chunk]
        placeholders = ",".join("?" * len(batch))
        rows = conn.execute(
            f"SELECT bi.item_no, bc.name "
            f"FROM bricklink_items bi "
            f"JOIN bricklink_categories bc ON bc.id = bi.category_id "
            f"WHERE bi.item_no IN ({placeholders})",
            batch,
        )
        for item_no, cat_name in rows:
            if cat_name:
                out[str(item_no)] = cat_name
    return out


@dataclass
class CatalogConfig:
    bla_api_key: str
    db_path: str
    brickstore_db_path: str
    ldraw_library_dir: str


class ProfileCatalogService:
    def __init__(self, *, runs_syncs: bool = True) -> None:
        """``runs_syncs``: this process is the one that syncs the catalog (and
        rebuilds its search index). Hive's web process is not: the syncs run in
        the worker process, which shares parts.db with it, and the web process
        follows them (``follow_syncs``)."""
        db_path = os.path.expanduser(settings.SORTING_PROFILE_PARTS_DB_PATH)
        _ensure_parent_dir(db_path)
        self._config = CatalogConfig(
            bla_api_key=settings.BLA_API_KEY,
            db_path=db_path,
            brickstore_db_path=os.path.expanduser(settings.SORTING_PROFILE_BRICKSTORE_DB_PATH),
            ldraw_library_dir=os.path.expanduser(settings.SORTING_PROFILE_LDRAW_LIBRARY_DIR),
        )
        self.runs_syncs = runs_syncs
        # The one lock for self._conn. A sqlite3 connection opened with
        # check_same_thread=False may be handed to other threads, but only one
        # may use it at a time. Requests run on a thread pool and the web
        # process reloads the catalog on a thread of its own, so every use of
        # the connection on one of those holds this lock, for one call at a
        # time. Nothing slow runs under it: work that takes seconds (the reload
        # after a sync, the import of Rebrickable's sets) uses a connection of
        # its own, so a search never waits for it.
        self._lock = Lock()
        self._conn = profile_db.initDb(self._config.db_path)
        self._parts_data = profile_db.PartsData()
        self._loaded_sync_version = self._sync_version()
        profile_db.reloadPartsData(self._conn, self._parts_data, rebuild_search=runs_syncs)
        if runs_syncs:
            # A sync row still marked 'running' means a prior process died
            # mid-sync; flag it 'interrupted' so the UI offers a resume instead
            # of a dead bar. Only where syncs run: anywhere else, a 'running'
            # row is the worker process's sync, alive.
            profile_db.markRunningSyncsInterrupted(self._conn)
        self._follow_lock = Lock()
        self._followed_at = time.monotonic()
        self._following = False
        self._sync = profile_parts_cache.SyncManager()
        self._auto_sync_state_lock = Lock()
        self._auto_sync_stop_event = Event()
        self._auto_sync_loop_thread: Thread | None = None
        self._auto_sync_job_thread: Thread | None = None
        self._auto_sync_running = False
        self._auto_sync_plan: list[str] = []
        self._auto_sync_last_checked_at: str | None = None
        self._auto_sync_last_started_at: str | None = None

    @property
    def parts_data(self):
        return self._parts_data

    @property
    def auto_sync_enabled(self) -> bool:
        return settings.PROFILE_CATALOG_AUTO_SYNC_ENABLED

    @property
    def auto_sync_loop_running(self) -> bool:
        with self._auto_sync_state_lock:
            return bool(self._auto_sync_loop_thread and self._auto_sync_loop_thread.is_alive())

    def _sync_version(self) -> tuple[tuple[str, str], ...]:
        """When each kind of sync last finished: changes exactly when a sync
        has changed the catalog."""
        with self._lock:
            return tuple(
                self._conn.execute(
                    "SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key",
                    (f"{PROFILE_CATALOG_LAST_SYNC_META_PREFIX}%",),
                ).fetchall()
            )

    def follow_syncs(self) -> None:
        """Pick up a sync another process finished: in a process that does not
        run the syncs (the web process), reload the in-memory catalog once the
        worker process has synced parts.db. Looks at most once a minute, and
        reloads on a thread of its own, so no request waits for it."""
        if self.runs_syncs:
            return
        now = time.monotonic()
        if now - self._followed_at < FOLLOW_SYNCS_INTERVAL_S:
            return
        with self._follow_lock:
            if self._following or now - self._followed_at < FOLLOW_SYNCS_INTERVAL_S:
                return
            self._followed_at = now
            try:
                version = self._sync_version()
            except Exception:
                logger.exception("catalog: could not read the sync times")
                return
            if version == self._loaded_sync_version:
                return
            self._following = True
        Thread(target=self._reload_followed, args=(version,), name="catalog-follow", daemon=True).start()

    def _reload_followed(self, version: tuple[tuple[str, str], ...]) -> None:
        try:
            started = time.monotonic()
            # The reload reads the whole catalog, seconds of work. A connection
            # of its own (parts.db is in WAL mode, so reading never blocks the
            # process that writes) keeps it off the shared one, where searches
            # would wait for all of it.
            with closing(sqlite3.connect(self._config.db_path)) as conn:
                profile_db.reloadPartsData(conn, self._parts_data, rebuild_search=False)
            self._loaded_sync_version = version
            logger.info("catalog: reloaded after a sync in the worker process (%.1fs)", time.monotonic() - started)
        except Exception:
            logger.exception("catalog: reload after a sync failed; the next look tries again")
        finally:
            with self._follow_lock:
                self._following = False

    def status(self) -> dict[str, Any]:
        status = self._sync.getStatus(self._parts_data)
        with self._auto_sync_state_lock:
            status["auto_sync_enabled"] = self.auto_sync_enabled
            status["auto_sync_running"] = self._auto_sync_running
            status["auto_sync_loop_running"] = bool(self._auto_sync_loop_thread and self._auto_sync_loop_thread.is_alive())
            status["auto_sync_plan"] = list(self._auto_sync_plan)
            status["auto_sync_last_checked_at"] = self._auto_sync_last_checked_at
            status["auto_sync_last_started_at"] = self._auto_sync_last_started_at
        counts = self._counts()
        with self._lock:
            status["last_synced_at"] = _last_synced_map(self._conn)
            status["types"] = _types_status(self._conn, counts, status.get("sync_type"))
        return status

    def _counts(self) -> dict[str, int]:
        return {
            "sets": self.set_count(),
            "categories": len(self._parts_data.categories),
            "colors": len(self._parts_data.colors),
            "parts": len(self._parts_data.parts),
        }

    def start_sync(self, sync_type: str) -> bool:
        with self._lock:
            if sync_type == "sets":
                return self._sync.startSetsSync(
                    self._config,
                    self._conn,
                    self._parts_data,
                    on_complete=lambda: self._mark_sync_completed(sync_type),
                )
            if sync_type == "categories":
                return self._sync.startCategoriesSync(
                    self._config,
                    self._conn,
                    self._parts_data,
                    on_complete=lambda: self._mark_sync_completed(sync_type),
                )
            if sync_type == "colors":
                return self._sync.startColorsSync(
                    self._config,
                    self._conn,
                    self._parts_data,
                    on_complete=lambda: self._mark_sync_completed(sync_type),
                )
            if sync_type == "parts":
                return self._sync.startPartsSync(
                    self._config,
                    self._conn,
                    self._parts_data,
                    on_complete=lambda: self._mark_sync_completed(sync_type),
                )
            if sync_type == "brickstore":
                return self._sync.startBrickstoreImport(
                    self._config,
                    self._conn,
                    self._parts_data,
                    on_complete=lambda: self._mark_sync_completed(sync_type),
                )
            if sync_type == "prices":
                return self._sync.startPriceSync(
                    self._config,
                    self._conn,
                    self._parts_data,
                    on_complete=lambda: self._mark_sync_completed(sync_type),
                )
            if sync_type == "geometry":
                return self._sync.startGeometrySync(
                    self._config,
                    self._conn,
                    self._parts_data,
                    on_complete=lambda: self._mark_sync_completed(sync_type),
                )
        raise ValueError(f"Unsupported sync_type '{sync_type}'")

    def stop_sync(self) -> None:
        self._sync.requestStop()

    def start_auto_sync_loop(self) -> bool:
        if not self.auto_sync_enabled:
            return False
        with self._auto_sync_state_lock:
            if self._auto_sync_loop_thread and self._auto_sync_loop_thread.is_alive():
                return False
            self._auto_sync_stop_event.clear()
            self._auto_sync_loop_thread = Thread(target=self._auto_sync_loop, daemon=True)
            self._auto_sync_loop_thread.start()
            return True

    def stop_auto_sync_loop(self) -> None:
        self._auto_sync_stop_event.set()
        with self._auto_sync_state_lock:
            loop_thread = self._auto_sync_loop_thread
            job_thread = self._auto_sync_job_thread
        if loop_thread and loop_thread.is_alive():
            loop_thread.join(timeout=1.0)
        if job_thread and job_thread.is_alive():
            self._sync.requestStop()
            job_thread.join(timeout=1.0)

    def start_auto_sync_if_needed(self) -> bool:
        plan = self.get_auto_sync_plan()
        if not plan:
            return False
        with self._auto_sync_state_lock:
            if self._auto_sync_running:
                return False
            self._auto_sync_running = True
            self._auto_sync_plan = list(plan)
            self._auto_sync_last_started_at = datetime.now(timezone.utc).isoformat()
            self._auto_sync_job_thread = Thread(target=self._run_auto_sync_plan, args=(plan,), daemon=True)
            self._auto_sync_job_thread.start()
            return True

    def get_auto_sync_plan(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(timezone.utc)
        with self._auto_sync_state_lock:
            self._auto_sync_last_checked_at = now.isoformat()
            if self._auto_sync_running:
                return []
        if not self.auto_sync_enabled:
            return []
        sync_status = self._sync.getStatus(self._parts_data)
        if sync_status.get("running"):
            return []
        with self._lock:
            last_synced = _last_synced_map(self._conn)
        return auto_sync_plan(self._counts(), last_synced, now)

    def get_last_synced_at(self, sync_type: str) -> str | None:
        if sync_type not in PROFILE_CATALOG_SYNC_TYPES:
            raise ValueError(f"Unsupported sync_type '{sync_type}'")
        with self._lock:
            raw = profile_db.getMeta(self._conn, _sync_meta_key(sync_type))
        return str(raw) if raw else None

    def get_last_synced_at_map(self) -> dict[str, str | None]:
        with self._lock:
            return _last_synced_map(self._conn)

    def _auto_sync_loop(self) -> None:
        check_interval = max(1, int(settings.PROFILE_CATALOG_AUTO_SYNC_CHECK_INTERVAL_MINUTES)) * 60
        try:
            while not self._auto_sync_stop_event.is_set():
                self.start_auto_sync_if_needed()
                self._auto_sync_stop_event.wait(check_interval)
        finally:
            with self._auto_sync_state_lock:
                self._auto_sync_loop_thread = None

    def _run_auto_sync_plan(self, plan: list[str]) -> None:
        try:
            for index, sync_type in enumerate(plan):
                if self._auto_sync_stop_event.is_set():
                    break
                with self._auto_sync_state_lock:
                    self._auto_sync_plan = list(plan[index:])
                started = self.start_sync(sync_type)
                if not started:
                    break
                if not self._wait_for_current_sync():
                    break
        finally:
            with self._auto_sync_state_lock:
                self._auto_sync_running = False
                self._auto_sync_plan = []
                self._auto_sync_job_thread = None

    def wait_for_sync(self, poll_s: float = 0.5) -> bool:
        """Wait for the running sync to end (stop_sync() ends it early). True
        when it ended without an error."""
        while True:
            status = self._sync.getStatus(self._parts_data)
            if not status.get("running"):
                return not status.get("error")
            time.sleep(poll_s)

    def _wait_for_current_sync(self) -> bool:
        while not self._auto_sync_stop_event.is_set():
            status = self._sync.getStatus(self._parts_data)
            if not status.get("running"):
                return not bool(status.get("error"))
            self._auto_sync_stop_event.wait(0.5)
        return False

    def _mark_sync_completed(self, sync_type: str) -> None:
        # Not under self._lock: a sync calls this from its own thread, and one
        # that ends at once calls it inside start_sync, which holds the lock.
        profile_db.setMeta(
            self._conn,
            _sync_meta_key(sync_type),
            datetime.now(timezone.utc).isoformat(),
        )

    def _sync_meta_key(self, sync_type: str) -> str:
        return _sync_meta_key(sync_type)

    def search_parts(self, query: str = "", cat_id: int | None = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        if not query and cat_id is None:
            return {"results": [], "total": 0, "offset": offset, "limit": limit}
        with self._lock:
            results, total = profile_db.searchParts(self._conn, query, cat_filter=cat_id, limit=limit, offset=offset)
        return {"results": results, "total": total, "offset": offset, "limit": limit}

    def part_summary(self, part_num: str) -> dict[str, Any] | None:
        """Name/category/thumbnail for one part, or None if it isn't in the
        catalog — the existence check a submitted part correction is validated
        against, and what the UI renders for an already-picked part.

        Reads the in-memory parts mirror, so it's a dict lookup rather than a
        query; admin_get_part hits sqlite four times to also assemble BrickLink
        items and price-guide counts, which a label summary doesn't need.

        Accepts a BrickLink item number too, resolving it to the Rebrickable
        mold — Brickognize predicts in BrickLink ids, so a piece whose machine
        guess was '4073' has to find 'Plate Round 1 x 1 with Solid Stud' (6141)
        here or it can't be confirmed at all. The returned part_num is always
        the Rebrickable one, so labels store a single id space."""
        part = self._parts_data.parts.get(part_num)
        if part is None:
            rb_part_num = self._parts_data.bl_to_rb_part.get(part_num)
            part = self._parts_data.parts.get(rb_part_num) if rb_part_num else None
        if part is None:
            return None
        cat_id = part.get("part_cat_id")
        category = self._parts_data.categories.get(cat_id) if cat_id is not None else None
        return {
            "part_num": part["part_num"],
            "name": part.get("name"),
            "part_cat_id": cat_id,
            "category_name": (category or {}).get("name"),
            "part_img_url": part.get("part_img_url"),
        }

    def admin_overview(self) -> dict[str, Any]:
        with self._lock:
            overview = profile_db.adminCatalogOverview(self._conn)
        # status() takes the lock itself, so it is called without it.
        overview["sync"] = self.status()
        return overview

    def admin_list_parts(
        self, query: str = "", cat_id: int | None = None, missing: str | None = None,
        limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        with self._lock:
            results, total = profile_db.adminListParts(
                self._conn, query=query, cat_filter=cat_id, missing=missing, limit=limit, offset=offset
            )
        return {"results": results, "total": total, "offset": offset, "limit": limit}

    def admin_get_part(self, part_num: str) -> dict[str, Any] | None:
        with self._lock:
            return profile_db.adminGetPart(self._conn, part_num)

    def piece_metadata(self, part_num: str, color_id: int | None = None) -> dict[str, Any] | None:
        """Flattened per-piece metadata + color-selected price (and physical
        dimensions) for the machine. None when the id matches no part/item."""
        with self._lock:
            return profile_db.pieceMetadata(self._conn, part_num, color_id)

    def batch_piece_prices(self, pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Moving-average price for many (part_num, color_id) pairs in one call."""
        with self._lock:
            return profile_db.batchPieceMovingAvg(self._conn, pairs)

    def batch_part_weights(self, part_nums: list[str]) -> dict[str, float]:
        """Catalog weight in grams, keyed by part id, for the ids that have one.

        Absent means no weight on file. Used to turn a piece-count histogram
        into a mass, which is a couple of queries here and would be thousands
        through `piece_metadata`.
        """
        with self._lock:
            return profile_db.batchPartWeights(self._conn, part_nums)

    def admin_list_categories(self) -> list[dict[str, Any]]:
        with self._lock:
            return profile_db.adminListCategories(self._conn)

    def list_colors(self) -> list[dict[str, Any]]:
        colors = []
        for color_id, color in sorted(self._parts_data.colors.items()):
            colors.append(
                {
                    "id": color_id,
                    "name": color.get("name") or str(color_id),
                    "rgb": color.get("rgb"),
                    "is_trans": bool(color.get("is_trans", False)),
                }
            )
        return colors

    def list_bricklink_colors(self) -> list[dict[str, Any]]:
        """The BrickLink color palette (``bricklink_palette``)."""
        return bricklink_palette(self._parts_data.colors)

    def bricklink_category_names(self, item_nos: list[str]) -> dict[str, str]:
        """BrickLink item number -> BrickLink category name, straight from
        parts.db. The piece a machine sorted is stored under its BrickLink item
        number (that is what Brickognize predicts), and the category lives on the
        bricklink_items row, so this is a single indexed lookup per id.

        Chunked because sqlite caps a statement at 999 bound parameters, and the
        fleet-wide part set runs to thousands. An id the catalog has never seen
        is simply absent from the result; the caller decides what "no category"
        means."""
        with self._lock:
            return _bricklink_category_names(self._conn, item_nos)

    def bricklink_part_colors(self, part_id: str, limit: int = 24) -> dict[str, Any]:
        """Every color this part is stocked in on BrickLink, most pieces for sale
        first, priced live across the whole palette.

        Deliberately not a shortlist. The palette is ~214 colors, a batch holds
        500 and answers in ~0.2s, so there is no reason to guess which colors to
        ask about — and guessing was actively harmful: filtering the query to
        colors near a solid guess hid the pearl/metallic finishes that some molds
        exclusively exist in (98347 is sold in Flat Silver and Pearl Dark Gray;
        a Dark Bluish Gray guess suppressed both). Falls back to the parts.db
        cache when no key is configured or the call fails."""
        palette = {c["id"]: c for c in self.list_bricklink_colors()}

        with self._lock:
            result = bricklink.part_color_availability(self._conn, part_id, limit=limit)

        result["source"] = "cache"
        if self._config.bla_api_key and result["item_no"]:
            try:
                live = bricklink.fetch_color_quantities(
                    self._config.bla_api_key, result["item_no"], sorted(palette)
                )
            except bricklink.BrickLinkError:
                live = {}
            if live:
                items = [
                    {"color_id": color_id, **quantities}
                    for color_id, quantities in live.items()
                    if quantities["qty"] > 0
                ]
                items.sort(key=lambda it: it["qty"], reverse=True)
                total = sum(it["qty"] for it in items)
                for it in items:
                    it["share"] = (it["qty"] / total) if total else 0.0
                result["items"] = items[:limit]
                result["total_qty"] = total
                result["source"] = "live"
                result["updated_at"] = None

        for item in result["items"]:
            color = palette.get(item["color_id"])
            item["color_name"] = color["name"] if color else str(item["color_id"])
            item["rgb"] = color.get("rgb") if color else None
            item["is_trans"] = bool(color.get("is_trans", False)) if color else False
        return result

    def bricklink_known_colors(self, item_no: str) -> set[int]:
        """The BrickLink colors the catalog lists this item in (BrickStore's
        known colors; presence only, and sparse for modern colors)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT bl_color_id FROM bricklink_item_colors WHERE item_no = ?", (item_no,)
            ).fetchall()
        return {int(row[0]) for row in rows}

    def import_bricklink_csv(self, csv_content: str, filename: str | None = None) -> dict[str, Any]:
        if not isinstance(csv_content, str) or not csv_content.strip():
            raise APIError(400, "CSV content is required", "PROFILE_CATALOG_CSV_EMPTY")

        reader = csv.DictReader(io.StringIO(csv_content.lstrip("\ufeff")))
        if not reader.fieldnames:
            raise APIError(400, "CSV file has no header row", "PROFILE_CATALOG_CSV_HEADER_MISSING")

        normalized_headers = {str(name).strip(): name for name in reader.fieldnames if isinstance(name, str)}
        required_headers = {"BLItemNo", "BLColorId", "Qty"}
        missing = sorted(required_headers - set(normalized_headers))
        if missing:
            raise APIError(
                400,
                f"BrickLink CSV is missing required columns: {', '.join(missing)}",
                "PROFILE_CATALOG_CSV_HEADER_INVALID",
            )

        bricklink_parts = self._build_bricklink_part_lookup()
        bricklink_colors = self._build_bricklink_color_lookup()

        merged: dict[tuple[str, int], dict[str, Any]] = {}
        warnings: list[str] = []
        imported_rows = 0

        for row_index, row in enumerate(reader, start=2):
            if not isinstance(row, dict):
                continue
            if not any(str(value or "").strip() for value in row.values()):
                continue

            bl_item_no = str(row.get(normalized_headers["BLItemNo"], "") or "").strip()
            raw_bl_color_id = str(row.get(normalized_headers["BLColorId"], "") or "").strip()
            raw_qty = str(row.get(normalized_headers["Qty"], "") or "").strip()
            part_name = str(row.get(normalized_headers.get("PartName", ""), "") or "").strip() or None
            color_name = str(row.get(normalized_headers.get("ColorName", ""), "") or "").strip() or None

            if not bl_item_no or not raw_bl_color_id or not raw_qty:
                warnings.append(f"Row {row_index}: missing BLItemNo, BLColorId, or Qty")
                continue

            try:
                bl_color_id = int(raw_bl_color_id)
            except ValueError:
                warnings.append(f"Row {row_index}: invalid BLColorId '{raw_bl_color_id}'")
                continue

            try:
                quantity = int(float(raw_qty))
            except ValueError:
                warnings.append(f"Row {row_index}: invalid Qty '{raw_qty}'")
                continue
            if quantity <= 0:
                warnings.append(f"Row {row_index}: Qty must be greater than 0")
                continue

            rb_part_num = bricklink_parts.get(bl_item_no)
            rb_color_id = bricklink_colors.get(bl_color_id)

            if rb_part_num and rb_color_id is not None:
                part_source = "rebrickable"
                stored_part_num = rb_part_num
                stored_color_id = rb_color_id
                part_data = self._parts_data.parts.get(rb_part_num) or {}
                color_data = self._parts_data.colors.get(rb_color_id) or {}
                resolved_part_name = part_data.get("name") or part_name or bl_item_no
                resolved_color_name = color_data.get("name") or color_name or str(bl_color_id)
                resolved_img_url = part_data.get("part_img_url")
            else:
                part_source = "bricklink"
                stored_part_num = bl_item_no
                stored_color_id = bl_color_id
                resolved_part_name = part_name or bl_item_no
                resolved_color_name = color_name or str(bl_color_id)
                resolved_img_url = None
                if not rb_part_num:
                    warnings.append(f"Row {row_index}: imported BrickLink item '{bl_item_no}' without local part mapping")
                if rb_color_id is None:
                    warnings.append(f"Row {row_index}: imported BrickLink color '{bl_color_id}' without local color mapping")

            key = (stored_part_num, stored_color_id)
            item = merged.setdefault(
                key,
                {
                    "part_num": stored_part_num,
                    "part_name": resolved_part_name,
                    "img_url": resolved_img_url,
                    "color_id": stored_color_id,
                    "color_name": resolved_color_name,
                    "part_source": part_source,
                    "quantity": 0,
                },
            )
            item["quantity"] += quantity
            imported_rows += 1

        parts = sorted(
            merged.values(),
            key=lambda item: (
                str(item.get("part_name") or "").lower(),
                str(item.get("color_name") or "").lower(),
                str(item.get("part_num") or ""),
            ),
        )
        if not parts:
            raise APIError(
                400,
                "No usable BrickLink rows could be imported. Check the CSV format and that the parts catalog is synced.",
                "PROFILE_CATALOG_CSV_IMPORT_EMPTY",
            )

        suggested_name = None
        if filename:
            base = os.path.basename(filename).strip()
            stem, _ext = os.path.splitext(base)
            suggested_name = stem.strip() or None

        return {
            "parts": parts,
            "imported_rows": imported_rows,
            "imported_unique_parts": len(parts),
            "warning_count": len(warnings),
            "warnings": warnings[:20],
            "suggested_name": suggested_name,
        }

    def index(self) -> CatalogIndex:
        index = catalog_index(self._parts_data)
        if index.known_color_rows is None:
            conn = getattr(self, "_conn", None)
            pairs: list = []
            if conn is not None:
                try:
                    with self._lock:
                        pairs = conn.execute("SELECT item_no, bl_color_id FROM bricklink_item_colors").fetchall()
                except Exception:
                    pairs = []
            index.set_known_colors(pairs)
        return index

    def compile_document(self, document: dict[str, Any], kits: dict[str, dict[str, Any]] | None = None) -> Compiled:
        """Compile a profile document. `kits` holds the kits its kit rules name,
        by kit ID; a kit rule whose kit is missing compiles as an empty kit."""
        inventories = self.resolve_inventories(document.get("rules") or [], kits or {})
        return compile_document(document, self.index(), inventories)

    def preview_rule(
        self,
        *,
        rules: list[dict[str, Any]],
        rule_id: str,
        q: str = "",
        offset: int = 0,
        limit: int = 50,
        standalone: bool = False,
    ) -> dict[str, Any]:
        return rule_matches(rules, rule_id, self.index(), q=q, offset=offset, limit=limit, standalone=standalone)

    def resolve_inventories(
        self,
        rules: list[dict[str, Any]],
        kits: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """The parts of each kit rule (and each set rule from before kits), in
        the shape a sorter counts them in, keyed by rule ID."""
        inventories: dict[str, dict[str, Any]] = {}
        for rule in rules:
            if not isinstance(rule, dict) or rule.get("disabled"):
                continue
            rule_id = str(rule.get("id") or "")
            rule_type = rule.get("rule_type")
            if rule_type == "kit":
                kit = kits.get(str(rule.get("kit_id") or ""))
                inventory = self.kit_inventory(kit, rule_id=rule_id, name=rule.get("name")) if kit else None
            elif rule_type == "set":
                set_source = str(rule.get("set_source") or ("custom" if rule.get("custom_parts") else "rebrickable"))
                if set_source == "custom":
                    _, inventory = self._compile_custom_set_rule(rule)
                else:
                    _, inventory = self._compile_rebrickable_set_rule(rule)
            else:
                continue
            if inventory:
                inventories[rule_id] = inventory
        return inventories

    def kit_inventory(self, kit: dict[str, Any], *, rule_id: str, name: str | None = None) -> dict[str, Any]:
        parts: list[dict[str, Any]] = []
        for raw in kit.get("parts") or []:
            if not isinstance(raw, dict):
                continue
            compiled = self._compile_inventory_part(
                part_num=raw.get("part_num"),
                color_id=raw.get("color_id", CUSTOM_SET_ANY_COLOR_ID),
                quantity=raw.get("quantity"),
                part_name=raw.get("part_name"),
                color_name=raw.get("color_name"),
                img_url=raw.get("img_url"),
                allow_any_color=True,
                require_known_part=False,
                require_known_color=False,
                identifier_source=str(raw.get("part_source") or "rebrickable"),
            )
            if compiled is not None:
                parts.append(compiled)
        set_meta = kit.get("set_meta") if isinstance(kit.get("set_meta"), dict) else {}
        return {
            "rule_id": rule_id,
            "kit_id": str(kit.get("id")),
            "set_num": kit.get("set_num") or f"kit:{kit.get('id')}",
            "name": str(name or kit.get("name") or "Kit"),
            "img_url": kit.get("image_url") or set_meta.get("img_url"),
            "year": set_meta.get("year"),
            "num_parts": sum(int(part["quantity"]) for part in parts),
            "include_spares": bool(kit.get("include_spares", False)),
            "set_source": "kit",
            "parts": parts,
        }

    def _compile_rebrickable_set_rule(self, rule: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any] | None]:
        set_num = str(rule.get("set_num") or "").strip()
        if not set_num:
            return {}, None

        rule_id = str(rule["id"])
        include_spares = bool(rule.get("include_spares", False))

        inventory = self.set_inventory(set_num)
        mapping: dict[str, str] = {}
        set_info = self.get_set(set_num) or {}
        set_meta = rule.get("set_meta") if isinstance(rule.get("set_meta"), dict) else {}
        parts: list[dict[str, Any]] = []

        for inv_part in inventory:
            if not include_spares and inv_part.get("is_spare"):
                continue
            compiled_part = self._compile_inventory_part(
                part_num=inv_part.get("part_num"),
                color_id=inv_part.get("color_id"),
                quantity=inv_part.get("quantity"),
                part_name=inv_part.get("part_name"),
                color_name=inv_part.get("color_name"),
                img_url=inv_part.get("part_img_url"),
                is_spare=bool(inv_part.get("is_spare", False)),
                require_known_part=False,
                require_known_color=False,
            )
            if compiled_part is None:
                continue
            bl_key = self._inventory_part_to_bl_key(compiled_part)
            if bl_key not in mapping:
                mapping[bl_key] = rule_id
            parts.append(compiled_part)

        return mapping, {
            "rule_id": rule_id,
            "set_num": set_num,
            "name": str(rule.get("name") or set_meta.get("name") or set_info.get("name") or set_num),
            "img_url": (
                set_meta.get("img_url")
                or set_meta.get("set_img_url")
                or set_info.get("img_url")
            ),
            "year": set_meta.get("year") or set_info.get("year"),
            "num_parts": set_meta.get("num_parts") or set_info.get("num_parts"),
            "include_spares": include_spares,
            "set_source": "rebrickable",
            "parts": parts,
        }

    def _compile_custom_set_rule(self, rule: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any] | None]:
        rule_id = str(rule["id"])
        set_num = self._custom_set_num(rule)
        set_meta = rule.get("set_meta") if isinstance(rule.get("set_meta"), dict) else {}
        raw_parts = rule.get("custom_parts")
        if not isinstance(raw_parts, list):
            raw_parts = []

        mapping: dict[str, str] = {}
        parts: list[dict[str, Any]] = []
        total_quantity = 0
        for raw_part in raw_parts:
            if not isinstance(raw_part, dict):
                continue
            identifier_source = str(raw_part.get("part_source") or "rebrickable")
            compiled_part = self._compile_inventory_part(
                part_num=raw_part.get("part_num"),
                color_id=raw_part.get("color_id", CUSTOM_SET_ANY_COLOR_ID),
                quantity=raw_part.get("quantity"),
                part_name=raw_part.get("part_name"),
                color_name=raw_part.get("color_name"),
                img_url=raw_part.get("img_url"),
                allow_any_color=True,
                require_known_part=identifier_source != "bricklink",
                require_known_color=identifier_source != "bricklink",
                identifier_source=identifier_source,
            )
            if compiled_part is None:
                continue
            bl_key = self._inventory_part_to_bl_key(compiled_part)
            if bl_key not in mapping:
                mapping[bl_key] = rule_id
            total_quantity += int(compiled_part["quantity"])
            parts.append(compiled_part)

        return mapping, {
            "rule_id": rule_id,
            "set_num": set_num,
            "name": str(rule.get("name") or set_meta.get("name") or "Custom Set"),
            "img_url": None,
            "year": None,
            "num_parts": total_quantity,
            "include_spares": False,
            "set_source": "custom",
            "parts": parts,
        }

    def _compile_inventory_part(
        self,
        *,
        part_num: Any,
        color_id: Any,
        quantity: Any,
        part_name: Any = None,
        color_name: Any = None,
        img_url: Any = None,
        is_spare: bool = False,
        allow_any_color: bool = False,
        require_known_part: bool = True,
        require_known_color: bool = True,
        identifier_source: str = "rebrickable",
    ) -> dict[str, Any] | None:
        raw_part_num = str(part_num or "").strip()
        if not raw_part_num:
            return None

        try:
            quantity_value = int(quantity)
        except (TypeError, ValueError) as exc:
            raise APIError(400, f"Invalid quantity for custom set part '{raw_part_num}'", "PROFILE_CUSTOM_SET_QUANTITY_INVALID") from exc
        if quantity_value <= 0:
            raise APIError(400, f"Quantity must be positive for custom set part '{raw_part_num}'", "PROFILE_CUSTOM_SET_QUANTITY_INVALID")

        normalized_color_id = self._normalize_custom_color_id(color_id, allow_any_color=allow_any_color)

        if identifier_source == "bricklink":
            resolved_part_name = str(part_name or raw_part_num)
            if normalized_color_id == CUSTOM_SET_ANY_COLOR_ID:
                bl_color: int | str = "any_color"
                resolved_color_name = "Any color"
            else:
                bl_color = normalized_color_id
                resolved_color_name = str(color_name or normalized_color_id)
            return {
                "part_num": raw_part_num,
                "color_id": CUSTOM_SET_ANY_COLOR_ID if normalized_color_id == CUSTOM_SET_ANY_COLOR_ID else bl_color,
                "quantity": quantity_value,
                "is_spare": is_spare,
                "rb_part_num": None,
                "rb_color_id": None if normalized_color_id == CUSTOM_SET_ANY_COLOR_ID else normalized_color_id,
                "part_name": resolved_part_name,
                "color_name": resolved_color_name,
                "img_url": img_url,
            }

        rb_part_num = raw_part_num
        rb_part = self._parts_data.parts.get(rb_part_num)
        if rb_part is None and require_known_part:
            raise APIError(400, f"Unknown part '{rb_part_num}' in custom set", "PROFILE_CUSTOM_SET_PART_UNKNOWN")
        if normalized_color_id == CUSTOM_SET_ANY_COLOR_ID:
            bl_color: int | str = "any_color"
            resolved_color_name = "Any color"
        else:
            color = self._parts_data.colors.get(normalized_color_id)
            if color is None and require_known_color:
                raise APIError(400, f"Unknown color '{normalized_color_id}' in custom set", "PROFILE_CUSTOM_SET_COLOR_UNKNOWN")
            bl_color = self._parts_data.rb_to_bl_color.get(normalized_color_id, normalized_color_id)
            resolved_color_name = str(color_name or (color.get("name") if color else normalized_color_id))

        bl_ids = rb_part.get("external_ids", {}).get("BrickLink", []) if rb_part else []
        bl_part_id = bl_ids[0] if bl_ids else rb_part_num
        resolved_part_name = str(part_name or (rb_part.get("name") if rb_part else rb_part_num) or rb_part_num)

        return {
            "part_num": bl_part_id,
            "color_id": CUSTOM_SET_ANY_COLOR_ID if normalized_color_id == CUSTOM_SET_ANY_COLOR_ID else bl_color,
            "quantity": quantity_value,
            "is_spare": is_spare,
            "rb_part_num": rb_part_num,
            "rb_color_id": None if normalized_color_id == CUSTOM_SET_ANY_COLOR_ID else normalized_color_id,
            "part_name": resolved_part_name,
            "color_name": resolved_color_name,
            "img_url": img_url or (rb_part.get("part_img_url") if rb_part else None),
        }

    def _normalize_custom_color_id(self, color_id: Any, *, allow_any_color: bool) -> int:
        if allow_any_color and color_id in (None, "", "any", "any_color"):
            return CUSTOM_SET_ANY_COLOR_ID
        try:
            normalized = int(color_id)
        except (TypeError, ValueError) as exc:
            raise APIError(400, f"Invalid color '{color_id}' in custom set", "PROFILE_CUSTOM_SET_COLOR_INVALID") from exc
        if allow_any_color and normalized == CUSTOM_SET_ANY_COLOR_ID:
            return CUSTOM_SET_ANY_COLOR_ID
        return normalized

    def _inventory_part_to_bl_key(self, part: dict[str, Any]) -> str:
        color_id = part.get("color_id")
        color_key = "any_color" if color_id == CUSTOM_SET_ANY_COLOR_ID else color_id
        return f"{color_key}-{part['part_num']}"

    def _custom_set_num(self, rule: dict[str, Any]) -> str:
        current = str(rule.get("set_num") or "").strip()
        if current:
            return current
        return f"custom:{rule['id']}"

    def _build_bricklink_part_lookup(self) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for rb_part_num, part in self._parts_data.parts.items():
            external_ids = part.get("external_ids", {})
            bricklink_ids = external_ids.get("BrickLink", [])
            if isinstance(bricklink_ids, dict):
                bricklink_ids = bricklink_ids.get("ext_ids", [])
            if not isinstance(bricklink_ids, list):
                continue
            for bricklink_id in bricklink_ids:
                item_no = str(bricklink_id or "").strip()
                if item_no and item_no not in lookup:
                    lookup[item_no] = rb_part_num
        return lookup

    def _build_bricklink_color_lookup(self) -> dict[int, int]:
        lookup: dict[int, int] = {}
        for rb_color_id, color in self._parts_data.colors.items():
            external_ids = color.get("external_ids", {})
            bricklink = external_ids.get("BrickLink", {})
            ext_ids = bricklink.get("ext_ids", []) if isinstance(bricklink, dict) else []
            if not isinstance(ext_ids, list):
                continue
            for bricklink_color_id in ext_ids:
                try:
                    numeric = int(bricklink_color_id)
                except (TypeError, ValueError):
                    continue
                lookup.setdefault(numeric, rb_color_id)
        return lookup

    def get_set(self, set_num: str) -> dict[str, Any] | None:
        """A set's details from Rebrickable's set list, or None."""
        with self._lock:
            return set_inventory.get_set(self._conn, set_num)

    def set_inventory(self, set_num: str) -> list[dict[str, Any]]:
        """A set's parts (empty when there is no such set)."""
        with self._lock:
            return set_inventory.get_set_inventory(self._conn, set_num)

    def set_count(self) -> int:
        with self._lock:
            return set_inventory.set_count(self._conn)

    def search_sets(
        self,
        query: str,
        limit: int = 20,
        min_year: int | None = None,
        max_year: int | None = None,
    ) -> list[dict]:
        with self._lock:
            results = set_inventory.search_sets(self._conn, query, min_year=min_year, max_year=max_year, limit=limit)
        return [
            {
                "set_num": s["set_num"],
                "name": s["name"],
                "year": s["year"],
                "num_parts": s["num_parts"],
                "img_url": s["img_url"],
            }
            for s in results
        ]

    def get_set_inventory(self, set_num: str) -> dict[str, Any]:
        normalized_set_num = str(set_num or "").strip()
        if not normalized_set_num:
            raise APIError(400, "set_num is required", "SET_NUM_REQUIRED")

        found = self.get_set(normalized_set_num)
        if found is None:
            raise APIError(404, "Set not found", "SET_NOT_FOUND")

        inventory = self.set_inventory(normalized_set_num)
        inventory.sort(
            key=lambda part: (
                str(part.get("part_name") or "").lower(),
                str(part.get("color_name") or "").lower(),
                str(part.get("part_num") or ""),
            )
        )

        return {
            "set": {
                "set_num": found["set_num"],
                "name": found["name"],
                "year": found["year"],
                "num_parts": found["num_parts"],
                "img_url": found["img_url"],
            },
            "inventory": inventory,
        }


class CatalogLookup:
    """The parts catalog without its in-memory copy, for the worker process.

    The catalog service holds every part, color and category in memory (~390
    MB). The web process needs that for its requests; the worker process never
    loads it (agent-docs/process-roles.md). What the worker's own passes ask of
    the catalog is a lookup: a part's weight, its picture and name, a category
    name, the color palette. Each is a query against parts.db, here, on a
    connection of its own that never writes. The work that needs the whole
    catalog (a sync, the default profiles) runs as a catalog task in a child
    process (app.services.catalog_tasks).
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = Lock()
        self._palette: list[dict[str, Any]] | None = None
        self._palette_synced_at: str | None = None

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            if not os.path.exists(self._db_path):
                # Not created yet (a new install): no catalog to look in, and
                # connecting would create an empty file.
                raise FileNotFoundError(f"no parts catalog at {self._db_path}")
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA query_only = ON")
            self._conn = conn
        return self._conn

    def batch_part_weights(self, part_nums: list[str]) -> dict[str, float]:
        with self._lock:
            return profile_db.batchPartWeights(self._connection(), part_nums)

    def piece_metadata(self, part_num: str, color_id: int | None = None) -> dict[str, Any] | None:
        with self._lock:
            return profile_db.pieceMetadata(self._connection(), part_num, color_id)

    def bricklink_category_names(self, item_nos: list[str]) -> dict[str, str]:
        with self._lock:
            return _bricklink_category_names(self._connection(), item_nos)

    def list_bricklink_colors(self) -> list[dict[str, Any]]:
        """The palette, read again only when the colors have been synced since."""
        with self._lock:
            conn = self._connection()
            synced_at = profile_db.getMeta(conn, _sync_meta_key("colors"))
            if self._palette is None or synced_at != self._palette_synced_at:
                self._palette = bricklink_palette(profile_db._loadColors(conn))
                self._palette_synced_at = synced_at
            return list(self._palette)

    def counts(self) -> dict[str, int]:
        with self._lock:
            conn = self._connection()
            counts = {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("categories", "bricklink_categories", "colors", "parts")
            }
            counts["sets"] = set_inventory.set_count(conn)
            return counts

    def last_synced(self) -> dict[str, str | None]:
        with self._lock:
            return _last_synced_map(self._connection())

    def status(self, *, running_task: list[str] | None, auto_sync: dict[str, Any]) -> dict[str, Any]:
        """What ProfileCatalogService.status() reports, for a sync that runs in
        a catalog task: progress from the rows the task's sync keeps in
        parts.db, counts from the tables. ``running_task`` is the task the
        worker process has running (["sync", "parts"], ["auto-sync"]...)."""
        counts = self.counts()
        with self._lock:
            conn = self._connection()
            running_type = None
            if running_task and running_task[0] == "sync" and len(running_task) > 1:
                running_type = running_task[1]
            elif running_task and running_task[0] == "auto-sync":
                persisted = profile_db.getAllCatalogSyncStates(conn)
                running = [s for s in persisted.values() if s.get("status") == "running"]
                if running:
                    running_type = max(running, key=lambda s: s.get("updated_at") or "")["sync_type"]
            types = _types_status(conn, counts, running_type)
            api_total = profile_db.getMeta(conn, "api_total_parts")
            last_synced = _last_synced_map(conn)
        current = types.get(running_type) if running_type else None
        return {
            "running": current is not None,
            "last_message": (current or {}).get("last_message") or "",
            "pages_fetched": (current or {}).get("pages_fetched") or 0,
            "sync_type": running_type,
            "progress_current": (current or {}).get("progress_current"),
            "progress_total": (current or {}).get("progress_total"),
            "cached_parts": counts["parts"],
            "cached_categories": counts["categories"],
            "cached_bricklink_categories": counts["bricklink_categories"],
            "cached_colors": counts["colors"],
            "api_total": int(api_total) if api_total else None,
            "error": None,
            **auto_sync,
            "last_synced_at": last_synced,
            "types": types,
        }


_catalog_service: ProfileCatalogService | None = None
# Building the service loads the catalog and rebuilds its search index, a
# write: requests that arrive together after a start must wait for one build,
# not each start their own and find the database locked.
_catalog_service_lock = Lock()
_catalog_lookup: CatalogLookup | None = None
# The worker process never loads the catalog; its catalog tasks (child
# processes, app.catalog_task) say they may.
_loads_catalog_in_worker = False


def allow_catalog_in_this_process() -> None:
    """For a catalog task: the one kind of process with HIVE_ROLE=worker that
    loads the catalog, does one thing with it and exits."""
    global _loads_catalog_in_worker
    _loads_catalog_in_worker = True


def _may_load_catalog() -> bool:
    return roles.role() != "worker" or _loads_catalog_in_worker


def get_profile_catalog_service() -> ProfileCatalogService:
    global _catalog_service
    if _catalog_service is None:
        if not _may_load_catalog():
            raise RuntimeError(
                "The worker process never loads the parts catalog (~390 MB): look parts up with "
                "catalog_lookup(), and run work that needs the whole catalog as a catalog task "
                "(app.services.catalog_tasks)."
            )
        with _catalog_service_lock:
            if _catalog_service is None:
                _catalog_service = ProfileCatalogService(runs_syncs=roles.runs_workers())
    _catalog_service.follow_syncs()
    return _catalog_service


def get_existing_profile_catalog_service() -> ProfileCatalogService | None:
    return _catalog_service


def catalog_lookup() -> ProfileCatalogService | CatalogLookup:
    """The catalog to look parts up in: this process's catalog service where it
    may hold one (web, all, a catalog task), else (the worker process) a
    CatalogLookup that answers from parts.db and loads nothing."""
    global _catalog_lookup
    if _may_load_catalog():
        return get_profile_catalog_service()
    if _catalog_lookup is None:
        with _catalog_service_lock:
            if _catalog_lookup is None:
                _catalog_lookup = CatalogLookup(os.path.expanduser(settings.SORTING_PROFILE_PARTS_DB_PATH))
    return _catalog_lookup
