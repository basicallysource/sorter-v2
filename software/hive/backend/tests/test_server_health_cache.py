from app.services import server_health


def test_storage_stats_pending_before_first_walk(db):
    stats = server_health.get_storage_stats(db)
    assert stats["pending"] is True
    assert stats["computed_at"] is None
    assert stats["total_bytes"] == 0
    assert stats["sample_images"] == {"bytes": 0, "files": 0}


def test_refresh_storage_cache_round_trips(db, monkeypatch):
    walked = {
        "sample_images": {"bytes": 100, "files": 3},
        "piece_images": {"bytes": 250, "files": 7},
        "model_files": {"bytes": 900, "files": 2},
        "total_bytes": 1250,
        "total_files": 12,
    }
    monkeypatch.setattr(server_health, "_walk_storage", lambda: walked)

    refreshed = server_health.refresh_storage_cache(db)
    assert refreshed["pending"] is False
    assert refreshed["total_bytes"] == 1250
    assert refreshed["computed_at"] is not None

    # A subsequent read serves the cached row without walking again.
    monkeypatch.setattr(
        server_health,
        "_walk_storage",
        lambda: (_ for _ in ()).throw(AssertionError("must not walk on read")),
    )
    read = server_health.get_storage_stats(db)
    assert read["pending"] is False
    assert read["piece_images"] == {"bytes": 250, "files": 7}
    assert read["total_files"] == 12
    assert read["computed_at"] == refreshed["computed_at"]


def test_refresh_storage_cache_upserts_single_row(db, monkeypatch):
    from app.models.server_storage_cache import ServerStorageCache

    monkeypatch.setattr(
        server_health,
        "_walk_storage",
        lambda: {
            "sample_images": {"bytes": 1, "files": 1},
            "piece_images": {"bytes": 0, "files": 0},
            "model_files": {"bytes": 0, "files": 0},
            "total_bytes": 1,
            "total_files": 1,
        },
    )
    server_health.refresh_storage_cache(db)
    server_health.refresh_storage_cache(db)
    assert db.query(ServerStorageCache).count() == 1
