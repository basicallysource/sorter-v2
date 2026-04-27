from __future__ import annotations

import pytest

from server.wall_detector_teacher import (
    EXPECTED_WALL_COUNT,
    MIN_EXPECTED_WALL_COUNT,
    WALL_DETECTOR_CLASS_ID,
    WallDetection,
    WallTeacherResult,
    parse_wall_response,
    wall_detector_prompt,
    wall_detector_system_prompt,
)


def test_system_prompt_is_terse_and_json_only() -> None:
    text = wall_detector_system_prompt()
    assert "JSON" in text or "json" in text
    assert "markdown" in text.lower()


def test_user_prompt_describes_5_walls_and_image_size() -> None:
    text = wall_detector_prompt(image_width=1280, image_height=720)
    assert "5" in text  # five walls
    assert "1280" in text and "720" in text
    # The 3-bbox schema asks for grouped wall_full / wall_start_inner /
    # wall_end_outer per wall.
    assert "wall_full" in text
    assert "wall_start_inner" in text
    assert "wall_end_outer" in text


def test_user_prompt_describes_actual_mask_colors() -> None:
    """The masked regions in the cropped frame are BLACK (apply_polygon_crop
    zeros pixels outside the polygon). The white outer ring is the physical
    disc rim, not a mask. The earlier prompt had this inverted, so Gemini
    saw a mismatch between description and image and produced garbage
    bboxes."""
    text = wall_detector_prompt(image_width=1280, image_height=720).lower()
    # BLACK is the masked / drop-hole region.
    assert "black" in text and "mask" in text
    # WHITE is explicitly the physical rim, not a wall.
    assert "rim" in text and "not a wall" in text
    # Drop hole / chute is mentioned as black non-wall geometry.
    assert "drop" in text


def test_user_prompt_describes_walls_as_thin_radial_lines() -> None:
    """The walls are thin straight radial dividers with a highlight edge
    and slight shadow. The prompt has to spell that out so Gemini knows
    what visual cue to chase."""
    text = wall_detector_prompt(image_width=1280, image_height=720).lower()
    assert "radial" in text
    assert "thin" in text
    assert "hub" in text and "rim" in text
    # Highlight + shadow visual cue (helps Gemini avoid sector areas).
    assert "highlight" in text or "shadow" in text


def test_user_prompt_constrains_wall_count_to_4_or_5() -> None:
    """At most one wall hidden by occlusion → answer is always 4 or 5.
    The prompt must encode this hard constraint so the model doesn't
    hallucinate fewer or extra walls."""
    text = wall_detector_prompt(image_width=1280, image_height=720).lower()
    assert "4 or 5" in text or "4 walls" in text
    assert "do not invent" in text
    # Drop-chute occlusion explanation justifies the 4-vs-5 ambiguity.
    assert "hidden" in text or "drop" in text


def test_user_prompt_uses_gemini_normalized_scale() -> None:
    """Gemini emits bboxes/points in 0..1000 normalized space regardless of
    what we ask. The prompt must explicitly request 0..1000 with
    [y_min, x_min, y_max, x_max] ordering so the parser can rescale
    correctly."""
    text = wall_detector_prompt(image_width=1280, image_height=720).lower()
    assert "0..1000" in text or "0-1000" in text
    assert "y_min" in text and "x_min" in text


def test_user_prompt_groups_three_bboxes_per_wall() -> None:
    """Each wall must be returned as a group of three bboxes sharing a
    wall_id, so we can derive endpoints from the small marker bboxes
    instead of asking Gemini for raw points."""
    text = wall_detector_prompt(image_width=1280, image_height=720)
    assert "wall_id" in text
    assert "three" in text.lower() or "3 " in text
    assert "wall_full" in text and "wall_start_inner" in text and "wall_end_outer" in text


def _make_wall(
    *,
    hub_xy: tuple[float, float] = (640.0, 360.0),
    rim_xy: tuple[float, float] = (640.0, 600.0),
    thickness_px: float = 10.0,
    confidence: float = 0.8,
) -> WallDetection:
    """Helper: build a WallDetection with derived AABB + OBB polygon for tests
    that don't care about the exact geometry."""
    hx, hy = hub_xy
    rx, ry = rim_xy
    x_lo, x_hi = (hx, rx) if hx <= rx else (rx, hx)
    y_lo, y_hi = (hy, ry) if hy <= ry else (ry, hy)
    pad = thickness_px / 2.0
    bbox = (x_lo - pad, y_lo - pad, x_hi + pad, y_hi + pad)
    polygon = (
        (hx - pad, hy),
        (hx + pad, hy),
        (rx + pad, ry),
        (rx - pad, ry),
    )
    marker = thickness_px * 1.5
    inner = (hx - marker, hy - marker, hx + marker, hy + marker)
    outer = (rx - marker, ry - marker, rx + marker, ry + marker)
    return WallDetection(
        wall_full_xyxy=bbox,
        wall_start_inner_xyxy=inner,
        wall_end_outer_xyxy=outer,
        hub_xy=hub_xy,
        rim_xy=rim_xy,
        thickness_px=thickness_px,
        bbox_xyxy=bbox,
        polygon_xy=polygon,
        confidence=confidence,
    )


def test_metadata_flags_low_quality_labels() -> None:
    """Frames with <4 walls are flagged so the operator can drop them
    from the training set."""
    from pathlib import Path

    low = WallTeacherResult(
        image_path=Path("/tmp/c4.jpg"),
        image_width=1280,
        image_height=720,
        walls=[_make_wall(), _make_wall(rim_xy=(700.0, 600.0))],
        model="m",
    )
    high = WallTeacherResult(
        image_path=Path("/tmp/c4_full.jpg"),
        image_width=1280,
        image_height=720,
        walls=[
            _make_wall(rim_xy=(640.0 + i * 20.0, 600.0))
            for i in range(MIN_EXPECTED_WALL_COUNT)
        ],
        model="m",
    )
    assert low.to_metadata()["low_quality_label"] is True
    assert low.to_metadata()["wall_count"] == 2
    assert high.to_metadata()["low_quality_label"] is False
    assert high.to_metadata()["min_expected_wall_count"] == MIN_EXPECTED_WALL_COUNT


def _wall_entry(
    *,
    inner_yx: tuple[float, float],
    outer_yx: tuple[float, float],
    inner_size: float = 30.0,
    outer_size: float = 30.0,
    full: tuple[float, float, float, float] | None = None,
    confidence: float = 0.9,
    angular_hint_deg: float | None = None,
    note: str | None = None,
) -> dict[str, object]:
    """Build a Gemini-style 3-bbox wall entry from inner/outer midpoint hints."""
    iy, ix = inner_yx
    oy, ox = outer_yx
    inner_bbox = [iy - inner_size / 2, ix - inner_size / 2,
                  iy + inner_size / 2, ix + inner_size / 2]
    outer_bbox = [oy - outer_size / 2, ox - outer_size / 2,
                  oy + outer_size / 2, ox + outer_size / 2]
    if full is None:
        # Bounding box of the two endpoint markers.
        y_lo, y_hi = sorted([iy - inner_size / 2, oy - outer_size / 2,
                             iy + inner_size / 2, oy + outer_size / 2])[::3]
        x_lo, x_hi = sorted([ix - inner_size / 2, ox - outer_size / 2,
                             ix + inner_size / 2, ox + outer_size / 2])[::3]
        full_bbox = [y_lo, x_lo, y_hi, x_hi]
    else:
        full_bbox = list(full)
    entry: dict[str, object] = {
        "wall_full": full_bbox,
        "wall_start_inner": inner_bbox,
        "wall_end_outer": outer_bbox,
        "confidence": confidence,
    }
    if angular_hint_deg is not None:
        entry["angular_hint_deg"] = angular_hint_deg
    if note is not None:
        entry["note"] = note
    return entry


def test_parse_wall_response_scales_3bbox_into_pixels() -> None:
    """Gemini emits the three bboxes in 0..1000 normalized space; the
    parser rescales them to actual image pixels."""
    payload = {
        "walls": [
            _wall_entry(
                inner_yx=(500, 500),    # disc center, normalized
                outer_yx=(500, 950),    # right edge, normalized
                inner_size=20,
                outer_size=20,
                angular_hint_deg=0.0,
            )
        ],
        "notes": "one wall pointing right",
    }
    walls, notes = parse_wall_response(payload, image_width=2000, image_height=1000)
    assert len(walls) == 1
    w = walls[0]
    # Hub/rim derived from inner/outer marker centers, scaled to pixels.
    assert w.hub_xy == pytest.approx((1000.0, 500.0))
    assert w.rim_xy == pytest.approx((1900.0, 500.0))
    # Inner marker bbox center matches hub endpoint.
    ix1, iy1, ix2, iy2 = w.wall_start_inner_xyxy
    assert ((ix1 + ix2) / 2, (iy1 + iy2) / 2) == pytest.approx((1000.0, 500.0))
    # Polygon is 4 corners.
    assert len(w.polygon_xy) == 4
    # bbox_xyxy aliases wall_full (same content).
    assert w.bbox_xyxy == w.wall_full_xyxy
    assert notes == "one wall pointing right"


def test_parse_wall_response_handles_diagonal_walls_with_obb() -> None:
    """Diagonal wall has a big AABB but a thin tilted OBB polygon."""
    payload = {
        "walls": [
            _wall_entry(
                inner_yx=(500, 500),
                outer_yx=(100, 900),
                inner_size=20,
                outer_size=20,
            )
        ]
    }
    walls, _ = parse_wall_response(payload, image_width=1000, image_height=1000)
    assert len(walls) == 1
    w = walls[0]
    # AABB spans the diagonal extent.
    x1, y1, x2, y2 = w.bbox_xyxy
    assert x1 < 502 < x2
    assert y1 < 502 < y2
    # OBB polygon has 4 corners and is thin perpendicular to hub→rim.
    polygon = w.polygon_xy
    assert len(polygon) == 4
    hub_mid_x = (polygon[0][0] + polygon[1][0]) / 2.0
    hub_mid_y = (polygon[0][1] + polygon[1][1]) / 2.0
    assert hub_mid_x == pytest.approx(500.0, abs=1.0)
    assert hub_mid_y == pytest.approx(500.0, abs=1.0)


def test_parse_wall_response_clamps_partially_out_of_range_markers() -> None:
    """Partially out-of-range marker bboxes get clamped to the image rect.
    Fully off-screen markers (no overlap with image) are dropped — those
    correspond to walls Gemini hallucinated outside the visible disc."""
    payload = {
        "walls": [
            # Inner marker straddles top-left corner; outer marker straddles
            # the right edge. Both have nonzero overlap with the image.
            _wall_entry(
                inner_yx=(20, 20),
                outer_yx=(500, 990),
                inner_size=80,    # 0..60 normalized → 0..38 px on width 640
                outer_size=80,
            )
        ]
    }
    walls, _ = parse_wall_response(payload, image_width=1280, image_height=720)
    assert len(walls) == 1
    w = walls[0]
    # Inner marker is clamped to fit inside the image (bbox 0..0.06*size).
    inner = w.wall_start_inner_xyxy
    assert inner[0] >= 0.0 and inner[1] >= 0.0
    assert inner[2] <= 1280.0 and inner[3] <= 720.0
    # Outer marker is clamped to the right edge but keeps positive area.
    outer = w.wall_end_outer_xyxy
    assert outer[2] <= 1280.0
    assert outer[2] - outer[0] > 0
    assert outer[3] - outer[1] > 0


def test_parse_wall_response_drops_degenerate_segments() -> None:
    """Zero-length segments (inner == outer marker) yield no usable OBB."""
    payload = {
        "walls": [
            _wall_entry(inner_yx=(100, 100), outer_yx=(100, 100)),
            _wall_entry(inner_yx=(100, 100), outer_yx=(400, 400)),
        ]
    }
    walls, _ = parse_wall_response(payload, image_width=1280, image_height=720)
    assert len(walls) == 1


def test_parse_wall_response_caps_at_expected_count() -> None:
    payload = {
        "walls": [
            _wall_entry(
                inner_yx=(500, 500),
                outer_yx=(100 + i * 50, 800),
            )
            for i in range(EXPECTED_WALL_COUNT + 3)
        ]
    }
    walls, _ = parse_wall_response(payload, image_width=1280, image_height=720)
    assert len(walls) == EXPECTED_WALL_COUNT


def test_parse_wall_response_handles_missing_walls_key() -> None:
    walls, notes = parse_wall_response({}, image_width=640, image_height=480)
    assert walls == []
    assert notes is None


def test_parse_wall_response_clamps_invalid_confidence() -> None:
    payload = {
        "walls": [
            _wall_entry(inner_yx=(500, 500), outer_yx=(100, 800), confidence=1.5),
            _wall_entry(inner_yx=(500, 500), outer_yx=(800, 100), confidence="n/a"),
        ]
    }
    walls, _ = parse_wall_response(payload, image_width=1280, image_height=720)
    assert walls[0].confidence == 1.0
    assert walls[1].confidence == 0.0


def test_parse_wall_response_skips_entries_missing_one_of_three_bboxes() -> None:
    """All three of wall_full, wall_start_inner, wall_end_outer must be
    present — partial entries are dropped so YOLO never sees half-labelled
    walls."""
    payload = {
        "walls": [
            {
                "wall_full": [400, 400, 600, 800],
                "wall_start_inner": [490, 490, 510, 510],
                # outer missing
                "confidence": 0.8,
            }
        ]
    }
    walls, _ = parse_wall_response(payload, image_width=1000, image_height=1000)
    assert walls == []


def test_yolo_aabb_line_normalization() -> None:
    """AABB-YOLO line normalizes bbox center + size against image extents."""
    wall = _make_wall(
        hub_xy=(640.0, 360.0),
        rim_xy=(640.0, 540.0),
        thickness_px=20.0,
    )
    line = wall.to_yolo_line(image_width=1280, image_height=720)
    parts = line.split()
    assert parts[0] == str(WALL_DETECTOR_CLASS_ID)
    cx, cy, w, h = (float(p) for p in parts[1:])
    # Center: x stays at 640 (helper uses pad on x); y is (360+540)/2=450.
    assert cx == pytest.approx(640.0 / 1280.0, abs=1e-5)
    assert cy == pytest.approx(450.0 / 720.0, abs=1e-5)
    # Wall is vertical, height is the long axis (segment 180 + thickness 20 = 200).
    assert h == pytest.approx(200.0 / 720.0, abs=1e-5)


def test_yolo_obb_line_emits_four_corners() -> None:
    """OBB-YOLO line carries 4 normalized corners — what YOLO11n-OBB expects."""
    wall = _make_wall(
        hub_xy=(640.0, 360.0),
        rim_xy=(640.0, 540.0),
        thickness_px=20.0,
    )
    line = wall.to_yolo_obb_line(image_width=1280, image_height=720)
    parts = line.split()
    assert parts[0] == str(WALL_DETECTOR_CLASS_ID)
    assert len(parts) == 1 + 8  # class + 4 corners * (x,y)
    coords = [float(p) for p in parts[1:]]
    for value in coords:
        assert 0.0 <= value <= 1.0


def test_to_metadata_carries_schema_and_walls() -> None:
    from pathlib import Path

    result = WallTeacherResult(
        image_path=Path("/tmp/c4.jpg"),
        image_width=1280,
        image_height=720,
        walls=[_make_wall()],
        model="google/gemini-3.1-flash-lite-preview",
        raw_response={"walls": []},
        notes="ok",
    )
    meta = result.to_metadata()
    assert meta["schema_version"] == "wall_detector_v1"
    assert meta["wall_count"] == 1
    assert meta["expected_wall_count"] == EXPECTED_WALL_COUNT
    assert meta["model"] == "google/gemini-3.1-flash-lite-preview"
    record = meta["walls"][0]
    assert "bbox_xyxy" in record
    assert "polygon_xy" in record
    assert "hub_xy" in record and "rim_xy" in record


def test_to_yolo_labels_is_one_line_per_wall() -> None:
    from pathlib import Path

    result = WallTeacherResult(
        image_path=Path("/tmp/c4.jpg"),
        image_width=1280,
        image_height=720,
        walls=[
            _make_wall(),
            _make_wall(hub_xy=(700.0, 360.0), rim_xy=(700.0, 540.0)),
        ],
        model="m",
    )
    text = result.to_yolo_labels()
    lines = text.splitlines()
    assert len(lines) == 2
    assert all(line.split()[0] == str(WALL_DETECTOR_CLASS_ID) for line in lines)
