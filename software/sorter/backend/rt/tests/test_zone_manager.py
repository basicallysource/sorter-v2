from __future__ import annotations

import pytest

from rt.runtimes._zones import TrackAngularExtent, ZoneManager


def _make(**kw) -> ZoneManager:
    kw.setdefault("max_zones", 2)
    kw.setdefault("intake_angle_deg", 0.0)
    kw.setdefault("guard_angle_deg", 10.0)
    kw.setdefault("default_half_width_deg", 10.0)
    return ZoneManager(**kw)


def test_zone_manager_rejects_invalid_max_zones() -> None:
    with pytest.raises(ValueError):
        ZoneManager(max_zones=0)


def test_add_zone_succeeds_when_empty() -> None:
    zm = _make()
    assert zm.zone_count() == 0
    assert zm.add_zone(piece_uuid="a", angle_deg=0.0, global_id=1, now_mono=1.0)
    assert zm.zone_count() == 1
    assert zm.has_piece("a") is True


def test_add_zone_rejected_when_full() -> None:
    zm = _make(max_zones=1)
    assert zm.add_zone(piece_uuid="a", angle_deg=0.0)
    assert not zm.add_zone(piece_uuid="b", angle_deg=180.0)
    assert zm.zone_count() == 1


def test_add_zone_idempotent_refresh_for_same_uuid() -> None:
    zm = _make(max_zones=1)
    assert zm.add_zone(piece_uuid="a", angle_deg=0.0, now_mono=1.0)
    assert zm.add_zone(piece_uuid="a", angle_deg=0.0, now_mono=2.5)
    zone = zm.zone_for("a")
    assert zone is not None
    assert zone.last_seen_mono == pytest.approx(2.5)


def test_remove_zone_clears_state() -> None:
    zm = _make()
    zm.add_zone(piece_uuid="a", angle_deg=0.0)
    zm.remove_zone("a")
    assert zm.zone_count() == 0
    zm.remove_zone("unknown")  # no-op


def test_is_arc_clear_true_when_empty() -> None:
    zm = _make()
    assert zm.is_arc_clear(0.0, half_width_deg=5.0) is True


def test_is_arc_clear_false_when_overlap() -> None:
    zm = _make(max_zones=2, guard_angle_deg=10.0, default_half_width_deg=10.0)
    zm.add_zone(piece_uuid="a", angle_deg=0.0)
    # Probe arc overlaps the existing zone at 0 deg.
    assert zm.is_arc_clear(5.0, half_width_deg=10.0) is False


def test_is_arc_clear_true_on_opposite_side() -> None:
    zm = _make(max_zones=2)
    zm.add_zone(piece_uuid="a", angle_deg=0.0)
    assert zm.is_arc_clear(180.0, half_width_deg=5.0) is True


def test_is_arc_clear_ignores_own_uuid() -> None:
    zm = _make()
    zm.add_zone(piece_uuid="a", angle_deg=0.0)
    assert zm.is_arc_clear(0.0, half_width_deg=5.0, ignore_piece_uuid="a") is True


def test_zone_count_matches_size() -> None:
    zm = _make(max_zones=3)
    zm.add_zone(piece_uuid="a", angle_deg=0.0)
    zm.add_zone(piece_uuid="b", angle_deg=120.0)
    assert zm.zone_count() == 2


def test_update_from_tracks_refreshes_existing() -> None:
    zm = _make(stale_timeout_s=1.0)
    zm.add_zone(piece_uuid="a", angle_deg=0.0, global_id=7, now_mono=0.0)
    extent = TrackAngularExtent(
        piece_uuid="a",
        global_id=7,
        center_deg=30.0,
        half_width_deg=12.0,
        last_seen_mono=0.5,
    )
    zm.update_from_tracks([extent], now_mono=0.5)
    zone = zm.zone_for("a")
    assert zone is not None
    assert zone.center_deg == pytest.approx(30.0)
    assert zone.last_seen_mono == pytest.approx(0.5)
    assert zone.stale is False


def test_update_from_tracks_marks_missing_stale_then_expires() -> None:
    zm = _make(stale_timeout_s=0.2)
    zm.add_zone(piece_uuid="a", angle_deg=0.0, now_mono=0.0)
    zm.update_from_tracks([], now_mono=0.1)
    zone = zm.zone_for("a")
    assert zone is not None and zone.stale is True
    # After timeout, next update drops it.
    zm.update_from_tracks([], now_mono=1.0)
    assert zm.zone_for("a") is None


def test_zones_returns_tuple_snapshot() -> None:
    zm = _make()
    zm.add_zone(piece_uuid="a", angle_deg=0.0)
    zones = zm.zones()
    assert isinstance(zones, tuple)
    assert len(zones) == 1
    assert zones[0].piece_uuid == "a"


def test_pieces_in_window_reports_overlapping_piece() -> None:
    zm = _make(drop_angle_deg=30.0, drop_tolerance_deg=14.0)
    zm.add_zone(piece_uuid="a", angle_deg=30.0, half_width_deg=6.0)
    hits = zm.pieces_in_window(center_deg=30.0, tolerance_deg=14.0)
    assert hits == ("a",)


def test_is_dropzone_clear_uses_configured_window() -> None:
    zm = _make(drop_angle_deg=30.0, drop_tolerance_deg=14.0)
    assert zm.is_dropzone_clear() is True
    zm.add_zone(piece_uuid="a", angle_deg=28.0, half_width_deg=6.0)
    assert zm.is_dropzone_clear() is False
