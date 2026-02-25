import json
import os
import threading
import time
import tempfile
from typing import Callable
import requests
from datetime import datetime, timezone

from bricklink_api import BricklinkApiError, BricklinkClient, BricklinkRateLimitError

from global_config import GlobalConfig, REBRICKABLE_BASE_URL, REBRICKABLE_PAGE_SIZE

THROTTLE_SECONDS = 1.1
BRICKLINK_BASE_THROTTLE_SECONDS = 0.25
BRICKLINK_MAX_THROTTLE_SECONDS = 300.0
BRICKLINK_SAVE_EVERY_PARTS = 10
BRICKLINK_ITEM_TYPE_PART = "PART"
BRICKLINK_PRICE_GUIDE_MAX_RETRIES = 8
BRICKLINK_REQUEST_WINDOW_SECONDS = 24 * 60 * 60
BRICKLINK_DAILY_REQUEST_LIMIT = 5000
BRICKLINK_REQUEST_RECORD_FILENAME = "bricklink_request_record.json"
BRICKLINK_PRIORITY_CATEGORY_NAMES = [
    "Bricks",
    "Plates",
    "Tiles",
    "Bricks Sloped",
    "Bricks Special",
    "Plates Special",
    "Bricks Wedged",
    "Plates Angled",
    "Bricks Curved",
    "Bricks Round and Cones",
    "Tiles Round and Curved",
    "Tiles Special",
    "Plates Round Curved and Dishes",
    "Bars, Ladders and Fences",
    "Windows and Doors",
    "Panels",
    "Hinges, Arms and Turntables",
    "Wheels and Tyres",
    "Containers",
    "Technic Bricks",
    "Technic Connectors",
    "Technic Axles",
    "Technic Pins",
    "Technic Bushes",
    "Technic Beams",
    "Technic Beams Special",
    "Technic Panels",
    "Technic Gears",
    "Technic Special",
    "Gear Parts",
]
BRICKLINK_DEFERRED_CATEGORY_NAMES = [
    "Stickers",
    "Flags, Banners and Signs",
    "Minifigs",
    "Minifig Accessories",
    "Minifig Heads",
    "Minifig Upper Body",
    "Minifig Lower Body",
    "Minifig Headwear",
    "Minifig Neckwear",
    "Minifig Hipwear",
    "Minifig Headwear Accessories",
    "Minifig Shields, Weapons, & Tools",
    "Minidoll Heads",
    "Minidoll Upper Body",
    "Minidoll Lower Body",
    "Belville, Scala and Fabuland",
    "Clikits",
    "Pen & Watch",
    "HO Scale",
    "Modulex",
    "Other",
]


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

    def getStatus(self, cache: "PartsCache") -> dict:
        with self._lock:
            return {
                "running": self.running,
                "last_message": self.last_message,
                "pages_fetched": self.pages_fetched,
                "sync_type": self.sync_type,
                "progress_current": self.progress_current,
                "progress_total": self.progress_total,
                "cached_parts": len(cache.parts),
                "cached_categories": len(cache.categories),
                "cached_bricklink_categories": len(cache.bricklink_categories),
                "cached_colors": len(cache.colors),
                "api_total": cache.api_total_parts,
                "bricklink_cached_parts": cache.bricklink_synced_parts,
                "bricklink_target_parts": cache.bricklink_target_parts,
                "bricklink_request_count": cache.bricklink_request_count,
                "bricklink_rate_limit_hits": cache.bricklink_rate_limit_hits,
                "bricklink_throttle_seconds": round(cache.bricklink_throttle_seconds, 2),
                "bricklink_requests_last_24h": len(cache.bricklink_request_times),
                "bricklink_requests_remaining_24h": max(
                    0,
                    BRICKLINK_DAILY_REQUEST_LIMIT - len(cache.bricklink_request_times),
                ),
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
            self.progress_current = len(cache.parts)
            self.progress_total = cache.api_total_parts
            self.sync_type = "parts"
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
            self.pages_fetched = 0
            self.progress_current = None
            self.progress_total = None
            self.sync_type = "categories"
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
            self.pages_fetched = 0
            self.progress_current = None
            self.progress_total = None
            self.sync_type = "colors"
            self.error = None
            self.last_message = "Syncing colors..."
        t = threading.Thread(target=self._syncColorsOnce, args=(gc, cache), daemon=True)
        t.start()
        return True

    def startBricklinkSync(self, gc: GlobalConfig, cache: "PartsCache") -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.stop_requested = False
            self.pages_fetched = 0
            self.progress_current = 0
            self.progress_total = None
            self.sync_type = "bricklink"
            self.error = None
            self.last_message = "Starting BrickLink sync..."
        t = threading.Thread(target=self._syncBricklinkLoop, args=(gc, cache), daemon=True)
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
                    self.progress_current = result["cached"]
                    self.progress_total = result["total"]
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
                self.sync_type = None

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
                self.sync_type = None

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
                self.sync_type = None

    def _syncBricklinkLoop(self, gc: GlobalConfig, cache: "PartsCache") -> None:
        try:
            result = syncBricklinkParts(
                gc,
                cache,
                should_stop_fn=self._shouldStopRequested,
                progress_fn=self._updateBricklinkProgress,
            )
            with self._lock:
                if result["stopped"]:
                    self.last_message = (
                        f'Stopped BrickLink sync at {result["processed"]} / {result["total"]} parts'
                    )
                else:
                    self.last_message = (
                        f'BrickLink sync complete: {result["processed"]} / {result["total"]} parts'
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

    def _shouldStopRequested(self) -> bool:
        with self._lock:
            return self.stop_requested

    def _updateBricklinkProgress(self, current: int, total: int, message: str) -> None:
        with self._lock:
            self.progress_current = current
            self.progress_total = total
            self.last_message = message


class PartsCache:
    categories: dict[int, dict]
    bricklink_categories: dict[int, dict]
    colors: dict[int, dict]
    parts: dict[str, dict]
    api_total_parts: int | None

    last_request_time: float
    request_count: int
    bricklink_last_request_time: float
    bricklink_request_count: int
    bricklink_throttle_seconds: float
    bricklink_rate_limit_hits: int
    bricklink_success_streak: int
    bricklink_target_parts: int | None
    bricklink_synced_parts: int | None
    bricklink_request_record_path: str | None
    bricklink_request_times: list[float]

    def __init__(self):
        self.categories = {}
        self.bricklink_categories = {}
        self.colors = {}
        self.parts = {}
        self.api_total_parts = None
        self.last_request_time = 0
        self.request_count = 0
        self.bricklink_last_request_time = 0
        self.bricklink_request_count = 0
        self.bricklink_throttle_seconds = BRICKLINK_BASE_THROTTLE_SECONDS
        self.bricklink_rate_limit_hits = 0
        self.bricklink_success_streak = 0
        self.bricklink_target_parts = 0
        self.bricklink_synced_parts = 0
        self.bricklink_request_record_path = None
        self.bricklink_request_times = []


def _throttle(cache: PartsCache) -> None:
    elapsed = time.time() - cache.last_request_time
    if elapsed < THROTTLE_SECONDS:
        time.sleep(THROTTLE_SECONDS - elapsed)
    cache.last_request_time = time.time()
    cache.request_count += 1
    print(f"[rebrickable] request #{cache.request_count}")


def _atomicWriteJson(file_path: str, data: dict) -> None:
    dir_path = os.path.dirname(os.path.abspath(file_path))
    base_name = os.path.basename(file_path)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{base_name}.", suffix=".tmp", dir=dir_path)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _mkBricklinkRequestRecordPath(gc: GlobalConfig) -> str:
    parts_dir = os.path.dirname(os.path.abspath(gc.parts_json_path))
    return os.path.join(parts_dir, BRICKLINK_REQUEST_RECORD_FILENAME)


def _pruneBricklinkRequestTimes(cache: PartsCache, now_ts: float | None = None) -> None:
    if now_ts is None:
        now_ts = time.time()
    cutoff_ts = now_ts - BRICKLINK_REQUEST_WINDOW_SECONDS
    cache.bricklink_request_times = [
        ts for ts in cache.bricklink_request_times
        if isinstance(ts, (int, float)) and ts > cutoff_ts
    ]


def _saveBricklinkRequestRecord(cache: PartsCache) -> None:
    if not cache.bricklink_request_record_path:
        return
    _pruneBricklinkRequestTimes(cache)
    out = {
        "window_seconds": BRICKLINK_REQUEST_WINDOW_SECONDS,
        "max_requests": BRICKLINK_DAILY_REQUEST_LIMIT,
        "request_times": cache.bricklink_request_times,
    }
    _atomicWriteJson(cache.bricklink_request_record_path, out)


def _loadBricklinkRequestRecord(cache: PartsCache) -> None:
    if not cache.bricklink_request_record_path:
        return
    if not os.path.exists(cache.bricklink_request_record_path):
        _saveBricklinkRequestRecord(cache)
        return
    try:
        with open(cache.bricklink_request_record_path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        cache.bricklink_request_times = []
        _saveBricklinkRequestRecord(cache)
        return
    request_times = data.get("request_times", [])
    if not isinstance(request_times, list):
        request_times = []
    cache.bricklink_request_times = []
    for ts in request_times:
        if isinstance(ts, (int, float)):
            cache.bricklink_request_times.append(float(ts))
    _pruneBricklinkRequestTimes(cache)
    _saveBricklinkRequestRecord(cache)


def _recordBricklinkRequest(cache: PartsCache, request_ts: float) -> None:
    cache.bricklink_request_times.append(float(request_ts))
    _pruneBricklinkRequestTimes(cache, now_ts=request_ts)
    _saveBricklinkRequestRecord(cache)


def _ensureBricklinkQuotaAvailable(cache: PartsCache) -> None:
    now_ts = time.time()
    _pruneBricklinkRequestTimes(cache, now_ts=now_ts)
    if len(cache.bricklink_request_times) < BRICKLINK_DAILY_REQUEST_LIMIT:
        return
    oldest_ts = min(cache.bricklink_request_times)
    next_allowed_ts = oldest_ts + BRICKLINK_REQUEST_WINDOW_SECONDS + 1
    next_allowed_iso = datetime.fromtimestamp(next_allowed_ts, tz=timezone.utc).isoformat()
    raise RuntimeError(
        "BrickLink request quota reached "
        f"({BRICKLINK_DAILY_REQUEST_LIMIT} in last 24h). "
        f"Next request after {next_allowed_iso} UTC."
    )


def _throttleBricklink(cache: PartsCache) -> None:
    _ensureBricklinkQuotaAvailable(cache)
    elapsed = time.time() - cache.bricklink_last_request_time
    wait_seconds = cache.bricklink_throttle_seconds - elapsed
    if wait_seconds > 0:
        time.sleep(wait_seconds)
    _ensureBricklinkQuotaAvailable(cache)
    request_ts = time.time()
    cache.bricklink_last_request_time = request_ts
    cache.bricklink_request_count += 1
    _recordBricklinkRequest(cache, request_ts)
    print(
        "[bricklink] request "
        f"#{cache.bricklink_request_count} "
        f"(throttle={cache.bricklink_throttle_seconds:.2f}s, "
        f"24h={len(cache.bricklink_request_times)}/{BRICKLINK_DAILY_REQUEST_LIMIT})"
    )


def _onBricklinkSuccess(cache: PartsCache) -> None:
    cache.bricklink_success_streak += 1
    if cache.bricklink_success_streak >= 20:
        cache.bricklink_throttle_seconds = max(
            BRICKLINK_BASE_THROTTLE_SECONDS,
            round(cache.bricklink_throttle_seconds * 0.9, 2),
        )
        cache.bricklink_success_streak = 0


def _onBricklinkRateLimit(cache: PartsCache, retry_after_seconds: float | None) -> None:
    cache.bricklink_rate_limit_hits += 1
    cache.bricklink_success_streak = 0
    cache.bricklink_throttle_seconds = min(
        BRICKLINK_MAX_THROTTLE_SECONDS,
        round((cache.bricklink_throttle_seconds * 1.8) + 0.5, 2),
    )
    sleep_seconds = cache.bricklink_throttle_seconds
    if retry_after_seconds is not None:
        sleep_seconds = max(sleep_seconds, retry_after_seconds)
    print(
        "[bricklink] rate limited "
        f"(hits={cache.bricklink_rate_limit_hits}, next_throttle={cache.bricklink_throttle_seconds:.2f}s, sleep={sleep_seconds:.2f}s)"
    )
    time.sleep(sleep_seconds)


def _bricklinkRequestWithBackoff(
    cache: PartsCache,
    request_fn: Callable[[], dict],
    request_label: str,
) -> dict:
    last_error = None
    for attempt_num in range(1, BRICKLINK_PRICE_GUIDE_MAX_RETRIES + 1):
        try:
            _throttleBricklink(cache)
            response = request_fn()
            _onBricklinkSuccess(cache)
            return response
        except BricklinkRateLimitError as e:
            last_error = e
            print(f"[bricklink] {request_label} rate limited on attempt {attempt_num}")
            _onBricklinkRateLimit(cache, e.retry_after_seconds)
    raise RuntimeError(f"BrickLink request failed after retries ({request_label}): {last_error}")


def _requireBricklinkCredentials(gc: GlobalConfig) -> None:
    missing = []
    if not gc.bl_consumer_key:
        missing.append("BL_CONSUMER_KEY")
    if not gc.bl_consumer_secret:
        missing.append("BL_CONSUMER_SECRET")
    if not gc.bl_token_value:
        missing.append("BL_TOKEN_VALUE")
    if not gc.bl_token_secret:
        missing.append("BL_TOKEN_SECRET")
    if missing:
        raise RuntimeError("Missing BrickLink env vars: " + ", ".join(missing))


def _mkBricklinkClient(gc: GlobalConfig) -> BricklinkClient:
    _requireBricklinkCredentials(gc)
    return BricklinkClient(
        consumer_key=gc.bl_consumer_key,
        consumer_secret=gc.bl_consumer_secret,
        token_value=gc.bl_token_value,
        token_secret=gc.bl_token_secret,
    )


def syncBricklinkCategories(gc: GlobalConfig, cache: PartsCache, client: BricklinkClient | None = None) -> int:
    bl_client = client or _mkBricklinkClient(gc)
    response = _bricklinkRequestWithBackoff(
        cache,
        bl_client.getCategories,
        "categories",
    )
    count = 0
    for cat_data in response.get("data", []):
        if not isinstance(cat_data, dict):
            continue
        cat_id = cat_data.get("category_id")
        if cat_id is None:
            continue
        cache.bricklink_categories[int(cat_id)] = cat_data
        count += 1
    savePartsCache(gc, cache)
    return count


def _getBricklinkPartIds(part_data: dict) -> list[str]:
    external_ids = part_data.get("external_ids") or {}
    bricklink_ids = external_ids.get("BrickLink") or []
    ids = []
    for item_id in bricklink_ids:
        if item_id is None:
            continue
        item_id_str = str(item_id).strip()
        if not item_id_str:
            continue
        if item_id_str not in ids:
            ids.append(item_id_str)
    return ids


def _mkBricklinkPartPriorityMaps(cache: PartsCache) -> tuple[dict[int, int], dict[int, int]]:
    priority_by_cat_id = {}
    deferred_by_cat_id = {}

    priority_name_to_rank = {}
    for idx, name in enumerate(BRICKLINK_PRIORITY_CATEGORY_NAMES):
        priority_name_to_rank[name] = idx

    deferred_name_to_rank = {}
    for idx, name in enumerate(BRICKLINK_DEFERRED_CATEGORY_NAMES):
        deferred_name_to_rank[name] = idx

    for cat_id, cat_data in cache.categories.items():
        cat_name = str(cat_data.get("name", ""))
        if cat_name in priority_name_to_rank:
            priority_by_cat_id[cat_id] = priority_name_to_rank[cat_name]
        if cat_name in deferred_name_to_rank:
            deferred_by_cat_id[cat_id] = deferred_name_to_rank[cat_name]

    return priority_by_cat_id, deferred_by_cat_id


def _bricklinkPartSortKey(
    cache: PartsCache,
    part_num: str,
    part_data: dict,
    priority_by_cat_id: dict[int, int],
    deferred_by_cat_id: dict[int, int],
) -> tuple:
    cat_id = part_data.get("part_cat_id")
    cat_data = cache.categories.get(cat_id) or {}
    cat_count = int(cat_data.get("part_count") or 0)
    bricklink_ids = _getBricklinkPartIds(part_data)
    request_cost_estimate = max(1, len(bricklink_ids)) * 2

    if cat_id in priority_by_cat_id:
        return (0, priority_by_cat_id[cat_id], request_cost_estimate, part_num)

    if cat_id in deferred_by_cat_id:
        return (2, deferred_by_cat_id[cat_id], request_cost_estimate, part_num)

    return (1, -cat_count, request_cost_estimate, part_num)


def _countBricklinkSyncedPartsForPartNums(cache: PartsCache, part_nums: list[str]) -> int:
    count = 0
    for part_num in part_nums:
        part_data = cache.parts.get(part_num)
        if not isinstance(part_data, dict):
            continue
        target_ids = _getBricklinkPartIds(part_data)
        if not target_ids:
            continue
        if _isBricklinkPartSyncComplete(part_data, target_ids):
            count += 1
    return count


def countBricklinkTargetParts(cache: PartsCache) -> int:
    priority_by_cat_id, _ = _mkBricklinkPartPriorityMaps(cache)
    count = 0
    for part_data in cache.parts.values():
        if part_data.get("part_cat_id") not in priority_by_cat_id:
            continue
        if _getBricklinkPartIds(part_data):
            count += 1
    return count


def countBricklinkSyncedParts(cache: PartsCache) -> int:
    priority_by_cat_id, _ = _mkBricklinkPartPriorityMaps(cache)
    count = 0
    for part_data in cache.parts.values():
        if part_data.get("part_cat_id") not in priority_by_cat_id:
            continue
        target_ids = _getBricklinkPartIds(part_data)
        if not target_ids:
            continue
        if _isBricklinkPartSyncComplete(part_data, target_ids):
            count += 1
    return count


def _isBricklinkPartSyncComplete(part_data: dict, target_ids: list[str]) -> bool:
    bricklink_data = part_data.get("bricklink_data")
    if not isinstance(bricklink_data, dict):
        return False
    items_map = bricklink_data.get("items")
    if not isinstance(items_map, dict):
        return False
    for item_no in target_ids:
        item_entry = items_map.get(item_no)
        if not isinstance(item_entry, dict):
            return False
        has_catalog_attempt = "catalog" in item_entry or "catalog_error" in item_entry
        has_price_attempt = "price_guide" in item_entry or "price_guide_error" in item_entry
        if not has_catalog_attempt or not has_price_attempt:
            return False
    return True


def _utcNowIso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mkBricklinkPriceGuideParams(gc: GlobalConfig) -> dict[str, str]:
    return {
        "guide_type": gc.bl_price_guide_type,
        "new_or_used": gc.bl_price_guide_new_or_used,
        "currency_code": gc.bl_price_guide_currency_code,
        "country_code": gc.bl_price_guide_country_code,
    }


def _syncSingleBricklinkItem(
    gc: GlobalConfig,
    cache: PartsCache,
    client: BricklinkClient,
    part_num: str,
    bricklink_item_no: str,
    items_map: dict[str, dict],
) -> bool:
    item_entry = items_map.get(bricklink_item_no)
    if not isinstance(item_entry, dict):
        item_entry = {}
        items_map[bricklink_item_no] = item_entry

    changed = False

    if "catalog" not in item_entry and "catalog_error" not in item_entry:
        try:
            item_entry["catalog"] = _bricklinkRequestWithBackoff(
                cache,
                lambda: client.getItem(BRICKLINK_ITEM_TYPE_PART, bricklink_item_no),
                f"item {bricklink_item_no}",
            )
        except BricklinkApiError as e:
            item_entry["catalog_error"] = str(e)
        item_entry["catalog_synced_at"] = _utcNowIso()
        changed = True

    if "price_guide" not in item_entry and "price_guide_error" not in item_entry:
        price_params = _mkBricklinkPriceGuideParams(gc)
        try:
            item_entry["price_guide"] = _bricklinkRequestWithBackoff(
                cache,
                lambda: client.getPriceGuide(BRICKLINK_ITEM_TYPE_PART, bricklink_item_no, price_params),
                f"price {bricklink_item_no}",
            )
        except BricklinkApiError as e:
            item_entry["price_guide_error"] = str(e)
        item_entry["price_guide_request"] = price_params
        item_entry["price_guide_synced_at"] = _utcNowIso()
        changed = True

    if changed:
        item_entry["part_num"] = part_num
        item_entry["bricklink_item_no"] = bricklink_item_no
    return changed


def syncBricklinkParts(
    gc: GlobalConfig,
    cache: PartsCache,
    should_stop_fn: Callable[[], bool] | None = None,
    progress_fn: Callable[[int, int, str], None] | None = None,
) -> dict:
    client = _mkBricklinkClient(gc)
    priority_by_cat_id, deferred_by_cat_id = _mkBricklinkPartPriorityMaps(cache)
    target_part_nums = []
    for part_num, part_data in cache.parts.items():
        if not _getBricklinkPartIds(part_data):
            continue
        cat_id = part_data.get("part_cat_id")
        if cat_id not in priority_by_cat_id:
            continue
        target_part_nums.append(part_num)
    target_part_nums.sort(
        key=lambda part_num: _bricklinkPartSortKey(
            cache,
            part_num,
            cache.parts.get(part_num) or {},
            priority_by_cat_id,
            deferred_by_cat_id,
        )
    )

    total = len(target_part_nums)
    processed = 0
    changed_parts = 0
    starting_synced = _countBricklinkSyncedPartsForPartNums(cache, target_part_nums)
    cache.bricklink_target_parts = total
    cache.bricklink_synced_parts = starting_synced

    if progress_fn is not None:
        progress_fn(0, total, f"BrickLink sync starting (priority categories, 0 / {total})")

    if should_stop_fn is not None and should_stop_fn():
        savePartsCache(gc, cache)
        return {"processed": processed, "total": total, "changed_parts": changed_parts, "stopped": True}

    if progress_fn is not None:
        progress_fn(0, total, "BrickLink sync: fetching BrickLink categories...")
    syncBricklinkCategories(gc, cache, client=client)
    if progress_fn is not None:
        progress_fn(0, total, f"BrickLink categories synced ({len(cache.bricklink_categories)})")

    for part_num in target_part_nums:
        if should_stop_fn is not None and should_stop_fn():
            savePartsCache(gc, cache)
            return {"processed": processed, "total": total, "changed_parts": changed_parts, "stopped": True}

        part_data = cache.parts.get(part_num)
        if not isinstance(part_data, dict):
            processed += 1
            continue

        bricklink_ids = _getBricklinkPartIds(part_data)
        if not bricklink_ids:
            processed += 1
            continue

        if _isBricklinkPartSyncComplete(part_data, bricklink_ids):
            processed += 1
            if progress_fn is not None:
                progress_fn(
                    processed,
                    total,
                    (
                        f"BrickLink {processed} / {total} "
                        f"(priority only, resume skip, throttle {cache.bricklink_throttle_seconds:.2f}s)"
                    ),
                )
            continue

        bricklink_data = part_data.get("bricklink_data")
        if not isinstance(bricklink_data, dict):
            bricklink_data = {}
            part_data["bricklink_data"] = bricklink_data
        items_map = bricklink_data.get("items")
        if not isinstance(items_map, dict):
            items_map = {}
            bricklink_data["items"] = items_map

        bricklink_data["external_ids"] = bricklink_ids
        bricklink_data["primary_item_no"] = bricklink_ids[0]
        bricklink_data["price_guide_defaults"] = _mkBricklinkPriceGuideParams(gc)
        bricklink_data["last_sync_started_at"] = _utcNowIso()

        part_changed = False
        for bricklink_item_no in bricklink_ids:
            part_changed = _syncSingleBricklinkItem(
                gc=gc,
                cache=cache,
                client=client,
                part_num=part_num,
                bricklink_item_no=bricklink_item_no,
                items_map=items_map,
            ) or part_changed

        bricklink_data["last_sync_finished_at"] = _utcNowIso()
        if part_changed:
            changed_parts += 1
        if _isBricklinkPartSyncComplete(part_data, bricklink_ids):
            if isinstance(cache.bricklink_synced_parts, int):
                cache.bricklink_synced_parts += 1
            else:
                cache.bricklink_synced_parts = 1

        processed += 1
        if progress_fn is not None:
            progress_fn(
                processed,
                total,
                (
                    f"BrickLink {processed} / {total} "
                    f"(priority only, updated {changed_parts}, req {cache.bricklink_request_count}, "
                    f"throttle {cache.bricklink_throttle_seconds:.2f}s)"
                ),
            )

        if part_changed and (changed_parts % BRICKLINK_SAVE_EVERY_PARTS == 0):
            savePartsCache(gc, cache)

    savePartsCache(gc, cache)
    cache.bricklink_target_parts = total
    return {"processed": processed, "total": total, "changed_parts": changed_parts, "stopped": False}


def loadPartsCache(gc: GlobalConfig) -> PartsCache:
    cache = PartsCache()
    cache.bricklink_request_record_path = _mkBricklinkRequestRecordPath(gc)
    _loadBricklinkRequestRecord(cache)
    if not os.path.exists(gc.parts_json_path):
        # init empty file
        _atomicWriteJson(gc.parts_json_path, {"categories": {}, "parts": {}})
        return cache
    try:
        with open(gc.parts_json_path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return cache
    for cat_id_str, cat_data in data.get("categories", {}).items():
        cache.categories[int(cat_id_str)] = cat_data
    for cat_id_str, cat_data in data.get("bricklink_categories", {}).items():
        cache.bricklink_categories[int(cat_id_str)] = cat_data
    for color_id_str, color_data in data.get("colors", {}).items():
        cache.colors[int(color_id_str)] = color_data
    cache.parts = data.get("parts", {})
    cache.bricklink_target_parts = countBricklinkTargetParts(cache)
    cache.bricklink_synced_parts = countBricklinkSyncedParts(cache)
    return cache


def savePartsCache(gc: GlobalConfig, cache: PartsCache) -> None:
    cats_out = {}
    for cat_id, cat_data in cache.categories.items():
        cats_out[str(cat_id)] = cat_data
    bl_cats_out = {}
    for cat_id, cat_data in cache.bricklink_categories.items():
        bl_cats_out[str(cat_id)] = cat_data
    colors_out = {}
    for color_id, color_data in cache.colors.items():
        colors_out[str(color_id)] = color_data
    out = {
        "categories": cats_out,
        "bricklink_categories": bl_cats_out,
        "colors": colors_out,
        "parts": cache.parts,
    }
    _atomicWriteJson(gc.parts_json_path, out)


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
        if limit > 0 and len(results) >= limit:
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
