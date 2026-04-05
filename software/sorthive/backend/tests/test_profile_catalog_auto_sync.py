from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

from app.config import settings
from app.services.profile_builder_compat import builder_db
from app.services.profile_catalog import ProfileCatalogService


class _IdleSyncManager:
    def __init__(self) -> None:
        self.started: list[str] = []

    def getStatus(self, parts_data) -> dict:
        return {
            "running": False,
            "last_message": "",
            "pages_fetched": 0,
            "sync_type": None,
            "progress_current": None,
            "progress_total": None,
            "cached_parts": len(parts_data.parts),
            "cached_categories": len(parts_data.categories),
            "cached_bricklink_categories": len(parts_data.bricklink_categories),
            "cached_colors": len(parts_data.colors),
            "api_total": parts_data.api_total_parts,
            "error": None,
        }

    def requestStop(self) -> None:
        return None

    def startCategoriesSync(self, gc, conn, parts_data, on_complete=None, on_error=None) -> bool:
        self.started.append("categories")
        if callable(on_complete):
            on_complete()
        return True

    def startColorsSync(self, gc, conn, parts_data, on_complete=None, on_error=None) -> bool:
        self.started.append("colors")
        if callable(on_complete):
            on_complete()
        return True

    def startPartsSync(self, gc, conn, parts_data, on_complete=None, on_error=None) -> bool:
        self.started.append("parts")
        if callable(on_complete):
            on_complete()
        return True

    def startBrickstoreImport(self, gc, conn, parts_data, on_complete=None, on_error=None) -> bool:
        self.started.append("brickstore")
        if callable(on_complete):
            on_complete()
        return True

    def startPriceSync(self, gc, conn, parts_data, on_complete=None, on_error=None) -> bool:
        self.started.append("prices")
        if callable(on_complete):
            on_complete()
        return True


def _build_service(tmp_path: Path, sync_manager: _IdleSyncManager | None = None, *, rebrickable_api_key: str = "test-key") -> ProfileCatalogService:
    service = ProfileCatalogService.__new__(ProfileCatalogService)
    db_path = tmp_path / "parts.db"
    service._config = SimpleNamespace(
        rebrickable_api_key=rebrickable_api_key,
        bl_affiliate_api_key="",
        db_path=str(db_path),
        brickstore_db_path="",
    )
    service._lock = Lock()
    service._conn = builder_db.initDb(str(db_path))
    service._parts_data = builder_db.PartsData()
    service._sync = sync_manager or _IdleSyncManager()
    service._auto_sync_state_lock = Lock()
    service._auto_sync_stop_event = Event()
    service._auto_sync_loop_thread = None
    service._auto_sync_job_thread = None
    service._auto_sync_running = False
    service._auto_sync_plan = []
    service._auto_sync_last_checked_at = None
    service._auto_sync_last_started_at = None
    return service


def test_start_sync_records_last_synced_timestamp(tmp_path: Path) -> None:
    service = _build_service(tmp_path)

    assert service.get_last_synced_at("categories") is None

    started = service.start_sync("categories")

    assert started is True
    assert service.get_last_synced_at("categories") is not None


def test_get_auto_sync_plan_bootstraps_empty_catalog(tmp_path: Path, monkeypatch) -> None:
    service = _build_service(tmp_path)
    now = datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(settings, "PROFILE_CATALOG_AUTO_SYNC_ENABLED", True)

    assert service.get_auto_sync_plan(now=now) == ["categories", "colors", "parts"]


def test_get_auto_sync_plan_refreshes_only_stale_sections(tmp_path: Path, monkeypatch) -> None:
    service = _build_service(tmp_path)
    now = datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)

    service._parts_data.categories = {1: {"name": "Bricks"}}
    service._parts_data.colors = {5: {"name": "Red"}}
    service._parts_data.parts = {"3001": {"name": "Brick 2 x 4"}}

    builder_db.setMeta(
        service._conn,
        service._sync_meta_key("categories"),
        (now - timedelta(days=10)).isoformat(),
    )
    builder_db.setMeta(
        service._conn,
        service._sync_meta_key("colors"),
        (now - timedelta(hours=2)).isoformat(),
    )
    builder_db.setMeta(
        service._conn,
        service._sync_meta_key("parts"),
        (now - timedelta(days=2)).isoformat(),
    )

    monkeypatch.setattr(settings, "PROFILE_CATALOG_AUTO_SYNC_ENABLED", True)
    monkeypatch.setattr(settings, "PROFILE_CATALOG_AUTO_SYNC_CATEGORIES_MAX_AGE_HOURS", 24 * 7)
    monkeypatch.setattr(settings, "PROFILE_CATALOG_AUTO_SYNC_COLORS_MAX_AGE_HOURS", 24)
    monkeypatch.setattr(settings, "PROFILE_CATALOG_AUTO_SYNC_PARTS_MAX_AGE_HOURS", 24)

    assert service.get_auto_sync_plan(now=now) == ["categories", "parts"]


def test_get_auto_sync_plan_skips_when_rebrickable_key_missing(tmp_path: Path, monkeypatch) -> None:
    service = _build_service(tmp_path, rebrickable_api_key="")
    now = datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(settings, "PROFILE_CATALOG_AUTO_SYNC_ENABLED", True)

    assert service.get_auto_sync_plan(now=now) == []
