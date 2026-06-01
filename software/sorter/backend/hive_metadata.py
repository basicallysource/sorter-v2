from __future__ import annotations

import threading
from typing import Any, Optional

from blob_manager import getHiveConfig
from global_config import GlobalConfig

# The sorter-client ``HiveClient`` lives alongside the sorter tree and is
# injected onto ``sys.path`` by ``server.hive_models`` at import time.
from server.hive_models import HiveClient, HiveError

# Any single physical dimension (bbox x/y/z) above this is treated as
# "too big" — the piece is sent down the center of the chute to the misc
# bottom bin instead of a real bin, regardless of its sorting category.
OVERSIZE_MAX_DIMENSION_MM = 80.0

# Per-process cache keyed by part_num. Stores the resolved metadata dict, or
# None for parts Hive doesn't know about (a 404). Transient failures
# (connection errors, no primary target) are NOT cached so they retry.
_cache: dict[str, Optional[dict[str, Any]]] = {}
_cache_lock = threading.Lock()


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


def getMetadataForPieceFromHive(
    gc: GlobalConfig, part_num: Optional[str], *, use_cache: bool = True
) -> Optional[dict[str, Any]]:
    if not part_num:
        return None
    if use_cache:
        with _cache_lock:
            if part_num in _cache:
                return _cache[part_num]

    target = getPrimaryHiveTarget()
    if target is None:
        gc.logger.warn("hive metadata: no primary Hive target configured")
        return None

    try:
        client = HiveClient(target["url"], target["api_token"])
        data = client.get_part_metadata(part_num)
    except HiveError as exc:
        if exc.status_code == 404:
            with _cache_lock:
                _cache[part_num] = None
            return None
        gc.logger.warn(f"hive metadata fetch failed for {part_num}: {exc}")
        return None
    except Exception as exc:
        gc.logger.warn(f"hive metadata fetch error for {part_num}: {exc}")
        return None

    with _cache_lock:
        _cache[part_num] = data if isinstance(data, dict) else None
    return data if isinstance(data, dict) else None


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
