from __future__ import annotations

import threading
import time
from typing import Any, Optional

from blob_manager import getHiveConfig
from global_config import GlobalConfig

# The sorter-client ``HiveClient`` lives alongside the sorter tree and is
# injected onto ``sys.path`` by ``server.hive_models`` at import time.
from server.hive_models import HiveClient, HiveError

# Single source of per-piece metadata + BrickLink pricing. Hive owns the parts
# catalog; the machine fetches flattened metadata over the API and keeps a
# write-through persistent cache (local_state.hive_part_metadata_cache) so prices
# keep working across restarts and Hive outages. Nothing here reads a local
# parts.db — that dependency was removed.

# Any single physical dimension (bbox x/y/z) above this is treated as
# "too big" — the piece is sent down the center of the chute to the misc
# bottom bin instead of a real bin, regardless of its sorting category.
OVERSIZE_MAX_DIMENSION_MM = 80.0

# Serve a cached full-metadata entry immediately; if it's older than this, also
# kick a background refresh. Catalog + prices drift slowly, so this is generous.
_REFRESH_AFTER_S = 14 * 86400.0

# Per-process cache keyed by (part_num, color_key). Stores the resolved metadata
# dict, or None for parts Hive doesn't know about (a 404). Transient failures
# (connection errors, no primary target) are NOT cached so they retry.
_cache: dict[tuple[str, Optional[int]], Optional[dict[str, Any]]] = {}
_cache_lock = threading.Lock()

# Keys currently being refreshed in the background, so a burst of stale hits for
# the same part doesn't spawn a thread each.
_refreshing: set[tuple[str, Optional[int]]] = set()
_refreshing_lock = threading.Lock()

_bricklink_colors_cache: Optional[list[dict[str, Any]]] = None
_bricklink_colors_lock = threading.Lock()


def getPrimaryHiveTarget() -> Optional[dict[str, Any]]:
    config = getHiveConfig()
    if not isinstance(config, dict):
        return None
    targets = [
        target
        for target in config.get("targets", [])
        if isinstance(target, dict)
        and target.get("enabled", True)
        and isinstance(target.get("url"), str)
        and target.get("url")
        and isinstance(target.get("api_token"), str)
        and target.get("api_token")
    ]
    if not targets:
        return None
    primary_id = config.get("primary_target_id")
    for target in targets:
        if target.get("id") == primary_id:
            return target
    return targets[0]


def _client() -> Optional[HiveClient]:
    target = getPrimaryHiveTarget()
    if target is None:
        return None
    return HiveClient(target["url"], target["api_token"])


def _parseColorKey(color_id: Optional[Any]) -> Optional[int]:
    if color_id is None:
        return None
    text = str(color_id).strip()
    if not text or text == "any_color":
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _fetchFromHive(
    gc: GlobalConfig, part_num: str, color_key: Optional[int]
) -> tuple[Optional[dict[str, Any]], bool]:
    """Fetch flattened metadata for one part. Returns (metadata, definitive):
    definitive=True means Hive answered authoritatively (a dict, or a 404 → None)
    and the result may be cached; definitive=False means a transient failure that
    must not be cached."""
    client = _client()
    if client is None:
        gc.logger.warn("hive metadata: no primary Hive target configured")
        return None, False
    try:
        data = client.get_part_metadata(part_num, color_key)
    except HiveError as exc:
        if exc.status_code == 404:
            return None, True
        gc.logger.warn(f"hive metadata fetch failed for {part_num}: {exc}")
        return None, False
    except Exception as exc:
        gc.logger.warn(f"hive metadata fetch error for {part_num}: {exc}")
        return None, False
    return (data if isinstance(data, dict) else None), True


def _storeResult(
    part_num: str, color_key: Optional[int], metadata: Optional[dict[str, Any]]
) -> None:
    from local_state import put_cached_part_metadata

    with _cache_lock:
        _cache[(part_num, color_key)] = metadata
    moving_avg = metadata.get("moving_avg_price") if isinstance(metadata, dict) else None
    if isinstance(metadata, dict):
        # Only persist authoritative hits; a 404 (metadata=None) stays in-process.
        put_cached_part_metadata(part_num, color_key, metadata, moving_avg)


def _backgroundRefresh(gc: GlobalConfig, part_num: str, color_key: Optional[int]) -> None:
    key = (part_num, color_key)
    with _refreshing_lock:
        if key in _refreshing:
            return
        _refreshing.add(key)

    def _run() -> None:
        try:
            metadata, definitive = _fetchFromHive(gc, part_num, color_key)
            if definitive:
                _storeResult(part_num, color_key, metadata)
        finally:
            with _refreshing_lock:
                _refreshing.discard(key)

    threading.Thread(target=_run, daemon=True, name="hive-metadata-refresh").start()


def getPieceMetadata(
    gc: GlobalConfig,
    part_num: Optional[str],
    color_id: Optional[Any] = None,
    *,
    use_cache: bool = True,
) -> Optional[dict[str, Any]]:
    if not part_num:
        return None
    color_key = _parseColorKey(color_id)
    key = (part_num, color_key)

    if use_cache:
        with _cache_lock:
            if key in _cache:
                return _cache[key]

        from local_state import get_cached_part_metadata

        payload, _moving_avg, cached_at = get_cached_part_metadata(part_num, color_key)
        if payload is not None and cached_at is not None:
            with _cache_lock:
                _cache[key] = payload
            if time.time() - cached_at > _REFRESH_AFTER_S:
                _backgroundRefresh(gc, part_num, color_key)
            return payload

    metadata, definitive = _fetchFromHive(gc, part_num, color_key)
    if definitive:
        _storeResult(part_num, color_key, metadata)
    return metadata


def getBatchMovingAvgPrices(
    gc: GlobalConfig, pairs: list[tuple[Optional[str], Optional[Any]]]
) -> dict[tuple[Optional[str], Optional[Any]], Optional[float]]:
    """Moving-average price for many (part_id, color_id) pairs. Serves from the
    persistent cache (any age — historical revaluation tolerates stale) and fills
    all misses with a single batch request to Hive. Missing/unreachable → None."""
    from local_state import get_cached_part_prices, put_cached_part_prices

    result: dict[tuple[Optional[str], Optional[Any]], Optional[float]] = {}
    lookup_pairs = [(p, c) for (p, c) in pairs if p]
    cached = get_cached_part_prices([(p, c) for (p, c) in lookup_pairs])

    misses: list[dict[str, Any]] = []
    for part_id, color_id in pairs:
        if not part_id:
            result[(part_id, color_id)] = None
            continue
        color_key = _parseColorKey(color_id)
        norm = "any_color" if color_key is None else str(color_key)
        hit = cached.get((part_id, norm))
        if hit is not None:
            result[(part_id, color_id)] = hit[0]
        else:
            result[(part_id, color_id)] = None
            misses.append({"part_num": part_id, "color_id": color_key, "_orig": (part_id, color_id)})

    if not misses:
        return result

    client = _client()
    if client is None:
        return result
    try:
        payload = client.batch_piece_prices(
            [{"part_num": m["part_num"], "color_id": m["color_id"]} for m in misses]
        )
    except Exception as exc:
        gc.logger.warn(f"hive batch price fetch failed: {exc}")
        return result

    prices = payload.get("prices") if isinstance(payload, dict) else None
    if not isinstance(prices, list):
        return result

    # Align returned rows back to the original request order (the endpoint echoes
    # part_num + color_id per row).
    write_rows: list[tuple[Optional[str], Any, Optional[float]]] = []
    for miss, row in zip(misses, prices):
        moving_avg = row.get("moving_avg_price") if isinstance(row, dict) else None
        moving_avg = float(moving_avg) if isinstance(moving_avg, (int, float)) and moving_avg > 0 else None
        result[miss["_orig"]] = moving_avg
        write_rows.append((miss["part_num"], miss["color_id"], moving_avg))
    put_cached_part_prices(write_rows)
    return result


def listBrickLinkColors(gc: GlobalConfig) -> list[dict[str, Any]]:
    # BrickLink color palette for the correction dropdown. Static for the process
    # lifetime, so fetch once and memoize. Empty on any failure.
    global _bricklink_colors_cache
    with _bricklink_colors_lock:
        if _bricklink_colors_cache is not None:
            return _bricklink_colors_cache
    client = _client()
    if client is None:
        return []
    try:
        payload = client.list_bricklink_colors()
    except Exception as exc:
        gc.logger.warn(f"hive bricklink colors fetch failed: {exc}")
        return []
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []
    with _bricklink_colors_lock:
        _bricklink_colors_cache = results
    return results


def maxDimensionMm(metadata: Optional[dict[str, Any]]) -> Optional[float]:
    if not isinstance(metadata, dict):
        return None
    dims = metadata.get("dimensions")
    if not isinstance(dims, dict):
        return None
    values = [dims.get("bbox_x_mm"), dims.get("bbox_y_mm"), dims.get("bbox_z_mm")]
    numeric = [float(v) for v in values if isinstance(v, (int, float))]
    return max(numeric) if numeric else None


def isOversize(max_dimension_mm: Optional[float]) -> bool:
    return max_dimension_mm is not None and max_dimension_mm > OVERSIZE_MAX_DIMENSION_MM
