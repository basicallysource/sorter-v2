"""The profiles every machine gets from Hive without saving them: a new
sorter runs the first one out of the box, and the others are one click away.

They are defined here, in code, and kept by Hive itself (owned by a user no
one signs in as). When a definition changes, the next start publishes a new
version of it.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.sorting_profile import SortingProfile
from app.models.sorting_profile_version import SortingProfileVersion
from app.models.user import User
from app.services.profile_catalog import get_profile_catalog_service

logger = logging.getLogger("app.default_profiles")

SYSTEM_OWNER_EMAIL = "defaults@hive.invalid"


def _condition(rule_id: str, field: str, op: str, value: Any) -> dict[str, Any]:
    return {"id": f"{rule_id}-{field}", "field": field, "op": op, "value": value}


def _category_rule(rule_id: str, name: str, bricklink_categories: list[int]) -> dict[str, Any]:
    return {
        "id": rule_id,
        "rule_type": "filter",
        "name": name,
        "match_mode": "all",
        "conditions": [_condition(rule_id, "bl_category_id", "in", bricklink_categories)],
        "children": [],
        "disabled": False,
    }


# BrickLink categories: plain, modified and round of each, never the decorated
# ones (a printed tile is not a basic piece).
BASIC_PIECE_RULES = [
    _category_rule("default-basic-bricks", "Bricks", [5, 7, 8]),
    _category_rule("default-basic-plates", "Plates", [26, 27, 28]),
    _category_rule("default-basic-tiles", "Tiles", [37, 38, 117]),
    _category_rule("default-basic-slopes", "Slopes", [31, 438, 32]),
]

# Each default has more categories than a machine has bins, so each says what
# to do when the bins run out: a new category with no free bin goes to
# Everything else and the run keeps going, instead of stopping to ask.
DEFINITIONS: list[dict[str, Any]] = [
    {
        "key": "default:bricklink-categories",
        "rank": 1,
        "name": "BrickLink categories",
        "description": "One bin for each BrickLink category, busiest first.",
        "rules": [],
        "fallback_mode": {"bricklink_categories": True, "no_bin": "misc"},
    },
    {
        "key": "default:colors",
        "rank": 2,
        "name": "Colors",
        "description": "One bin for each color.",
        "rules": [],
        "fallback_mode": {"by_color": True, "no_bin": "misc"},
    },
    {
        "key": "default:colors-and-basic-pieces",
        "rank": 3,
        "name": "Colors and basic pieces",
        "description": "Bricks, plates, tiles and slopes each get a bin; everything else goes by color.",
        "rules": BASIC_PIECE_RULES,
        "fallback_mode": {"by_color": True, "no_bin": "misc"},
    },
]


def _system_owner(db: Session) -> User:
    owner = db.query(User).filter(User.email == SYSTEM_OWNER_EMAIL).first()
    if owner is None:
        owner = User(email=SYSTEM_OWNER_EMAIL, display_name="Hive", password_hash=None, role="member", is_active=True)
        db.add(owner)
        db.flush()
    return owner


def _same(version: SortingProfileVersion | None, artifact: dict[str, Any]) -> bool:
    # The compiled result, not only the definition: a catalog update that moves
    # parts between categories publishes a new version too.
    return version is not None and version.compiled_hash == artifact["artifact_hash"]


def ensure_default_profiles(db: Session) -> list[str]:
    """Create each default profile, or publish a new version of one whose
    definition changed. Returns what it did, for the log."""
    catalog = get_profile_catalog_service()
    if not catalog.parts_data.parts:
        return ["parts catalog is empty; defaults wait for it"]
    owner = _system_owner(db)
    done = []
    for definition in DEFINITIONS:
        profile = db.query(SortingProfile).filter(SortingProfile.system_key == definition["key"]).first()
        if profile is None:
            profile = SortingProfile(
                owner_id=owner.id,
                name=definition["name"],
                description=definition["description"],
                visibility="public",
                tags=["default"],
                latest_version_number=0,
                system_key=definition["key"],
                default_rank=definition["rank"],
            )
            db.add(profile)
            db.flush()
        profile.default_rank = definition["rank"]
        compiled = catalog.compile_document(
            {
                "id": str(profile.id),
                "name": definition["name"],
                "description": definition["description"],
                "rules": definition["rules"],
                "fallback_mode": definition["fallback_mode"],
                "default_category_id": "misc",
            }
        )
        if compiled.problems:
            done.append(f"{definition['key']}: {compiled.problems[0].message}")
            continue
        artifact = compiled.artifact
        latest = (
            db.query(SortingProfileVersion)
            .filter(SortingProfileVersion.profile_id == profile.id)
            .order_by(SortingProfileVersion.version_number.desc())
            .first()
        )
        if _same(latest, artifact):
            continue
        number = int(profile.latest_version_number or 0) + 1
        stats = artifact["stats"]
        db.add(
            SortingProfileVersion(
                profile_id=profile.id,
                created_by_id=owner.id,
                version_number=number,
                change_note="Hive's default" if number == 1 else "Hive's default, recompiled",
                name=definition["name"],
                description=definition["description"],
                default_category_id=artifact["default_category_id"],
                rules_json=artifact["rules"],
                fallback_mode_json=artifact["fallback_mode"],
                compiled_artifact_json=artifact,
                compiled_stats_json={**stats, "warnings": compiled.warnings, "requires": artifact["requires"]},
                compiled_hash=artifact["artifact_hash"],
                compiled_part_count=int(stats.get("sorted") or 0),
                coverage_ratio=(stats["matched"] / stats["total_parts"]) if stats.get("total_parts") else None,
                is_published=True,
                created_via="system",
            )
        )
        profile.name = definition["name"]
        profile.description = definition["description"]
        profile.latest_version_number = number
        profile.latest_published_version_number = number
        profile.profile_type = artifact["profile_type"]
        profile.updated_at = datetime.now(timezone.utc)
        done.append(f"{definition['key']}: published v{number}")
    db.commit()
    return done


def start_default_profiles_thread() -> threading.Thread:
    """Ensure the defaults off the request path: loading the catalog and
    compiling take seconds, and startup must not wait for them."""

    def run() -> None:
        db = SessionLocal()
        try:
            for line in ensure_default_profiles(db):
                logger.info("default profiles: %s", line)
        except Exception:
            logger.exception("default profiles: could not be ensured")
            db.rollback()
        try:
            from app.services.profile_display import backfill_card_bins

            count = backfill_card_bins(db)
            if count:
                logger.info("profile display: described the bins of %d older versions for their cards", count)
        except Exception:
            logger.exception("profile display: could not describe older versions")
            db.rollback()
        finally:
            db.close()

    thread = threading.Thread(target=run, name="default-profiles", daemon=True)
    thread.start()
    return thread
