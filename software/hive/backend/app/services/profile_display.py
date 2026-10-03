"""Bins described for people, for profile versions compiled before bins were.

A version saved before the program format carries only each bin's name. Pages
show every version by its bins (picture, conditions in words, part count,
examples), so an older version's rules are compiled again for display: on the
fly for the version a page shows, and once, at start, for the few bins a card
shows of each profile's latest version. What a machine downloads for those
versions does not change.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import Any

from sqlalchemy.orm import Session

from app.models.sorting_profile import SortingProfile
from app.models.sorting_profile_version import SortingProfileVersion
from app.services.kits import kits_for_rules
from app.services.profile_catalog import get_profile_catalog_service

logger = logging.getLogger("app.profile_display")

_CACHE: OrderedDict[tuple[str, int], dict[str, Any]] = OrderedDict()
_CACHE_SIZE = 32
_lock = threading.Lock()


def described(version: SortingProfileVersion) -> bool:
    """Whether the version was compiled with its bins described (its stats
    keep its first bins), without loading its artifact."""
    stats = version.compiled_stats_json if isinstance(version.compiled_stats_json, dict) else {}
    return "bins" in stats and not stats.get("bins_backfilled")


def _document(version: SortingProfileVersion) -> dict[str, Any]:
    return {
        "id": str(version.profile_id),
        "name": version.name,
        "description": version.description,
        "default_category_id": version.default_category_id,
        "rules": version.rules_json or [],
        "fallback_mode": version.fallback_mode_json or {},
    }


def display_for(db: Session, version: SortingProfileVersion) -> dict[str, Any]:
    """{categories, category_order, warnings, bins} for an older version, from
    its rules compiled again; kept for the last few asked for."""
    catalog = get_profile_catalog_service()
    index = catalog.index()
    key = (str(version.id), index.generation)
    with _lock:
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return cached
    owner_id = version.profile.owner_id if version.profile is not None else None
    document = _document(version)
    kits = kits_for_rules(db, owner_id, document["rules"]) if owner_id else {}
    compiled = catalog.compile_document(document, kits)
    artifact = compiled.artifact
    display = {
        "categories": artifact["categories"],
        "category_order": artifact["category_order"],
        "warnings": compiled.warnings,
        "bins": artifact["stats"]["bins"],
        "sorted": artifact["stats"]["sorted"],
    }
    with _lock:
        _CACHE[key] = display
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
    return display


def backfill_card_bins(db: Session) -> int:
    """Give each profile's latest version (and latest published) the first
    bins its card shows, when it was compiled before bins were described."""
    done = 0
    for profile in db.query(SortingProfile).all():
        numbers = {profile.latest_version_number, profile.latest_published_version_number} - {None, 0}
        if not numbers:
            continue
        versions = (
            db.query(SortingProfileVersion)
            .filter(SortingProfileVersion.profile_id == profile.id, SortingProfileVersion.version_number.in_(numbers))
            .all()
        )
        for version in versions:
            stats = version.compiled_stats_json if isinstance(version.compiled_stats_json, dict) else {}
            if "bins" in stats:
                continue
            try:
                display = display_for(db, version)
            except Exception as exc:
                logger.warning("profile display: %s v%s could not be described: %s", profile.name, version.version_number, exc)
                continue
            version.compiled_stats_json = {**stats, "bins": display["bins"], "bins_backfilled": True}
            done += 1
    db.commit()
    return done
