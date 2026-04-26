from __future__ import annotations

import pytest

from server.wall_detector_teacher import (
    EXPECTED_WALL_COUNT,
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
    assert "bbox_xyxy" in text


def test_parse_wall_response_extracts_typed_walls() -> None:
    payload = {
        "walls": [
            {
                "bbox_xyxy": [10, 20, 50, 200],
                "confidence": 0.9,
                "angular_hint_deg": 36.0,
                "note": None,
            },
            {
                "bbox_xyxy": [600, 100, 640, 280],
                "confidence": 0.7,
                "angular_hint_deg": None,
                "note": "partial",
            },
        ],
        "notes": "two walls clearly visible",
    }
    walls, notes = parse_wall_response(payload, image_width=1280, image_height=720)
    assert len(walls) == 2
    assert walls[0].bbox_xyxy == (10.0, 20.0, 50.0, 200.0)
    assert walls[0].confidence == pytest.approx(0.9)
    assert walls[0].angular_hint_deg == pytest.approx(36.0)
    assert walls[1].note == "partial"
    assert notes == "two walls clearly visible"


def test_parse_wall_response_normalizes_bbox_order() -> None:
    """Gemini sometimes flips x1/x2 — parser fixes the order."""
    payload = {"walls": [{"bbox_xyxy": [50, 200, 10, 20], "confidence": 0.5}]}
    walls, _ = parse_wall_response(payload, image_width=1280, image_height=720)
    assert walls[0].bbox_xyxy == (10.0, 20.0, 50.0, 200.0)


def test_parse_wall_response_clamps_to_image_extents() -> None:
    payload = {"walls": [{"bbox_xyxy": [-5, -10, 1500, 800], "confidence": 0.4}]}
    walls, _ = parse_wall_response(payload, image_width=1280, image_height=720)
    assert walls[0].bbox_xyxy == (0.0, 0.0, 1280.0, 720.0)


def test_parse_wall_response_drops_degenerate_bbox() -> None:
    """Zero-area bbox after clamping → dropped."""
    payload = {
        "walls": [
            {"bbox_xyxy": [10, 10, 10, 10], "confidence": 0.9},
            {"bbox_xyxy": [20, 20, 30, 40], "confidence": 0.9},
        ]
    }
    walls, _ = parse_wall_response(payload, image_width=1280, image_height=720)
    assert len(walls) == 1


def test_parse_wall_response_caps_at_expected_count() -> None:
    payload = {
        "walls": [
            {"bbox_xyxy": [i * 10, 0, i * 10 + 5, 100], "confidence": 0.5}
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
            {"bbox_xyxy": [10, 10, 50, 100], "confidence": 1.5},
            {"bbox_xyxy": [60, 10, 80, 100], "confidence": "not-a-number"},
        ]
    }
    walls, _ = parse_wall_response(payload, image_width=1280, image_height=720)
    assert walls[0].confidence == 1.0
    assert walls[1].confidence == 0.0


def test_yolo_line_normalization() -> None:
    wall = WallDetection(bbox_xyxy=(10.0, 20.0, 50.0, 200.0), confidence=0.9)
    line = wall.to_yolo_line(image_width=1280, image_height=720)
    parts = line.split()
    assert parts[0] == str(WALL_DETECTOR_CLASS_ID)
    cx, cy, w, h = (float(p) for p in parts[1:])
    # Center: (10+50)/2 / 1280 = 0.0234375
    assert cx == pytest.approx(30.0 / 1280.0, abs=1e-5)
    # Height: (200-20)/720 = 0.25
    assert h == pytest.approx(180.0 / 720.0, abs=1e-5)


def test_to_metadata_carries_schema_and_walls() -> None:
    result = WallTeacherResult(
        image_path=__import__("pathlib").Path("/tmp/c4.jpg"),
        image_width=1280,
        image_height=720,
        walls=[
            WallDetection(bbox_xyxy=(10.0, 20.0, 50.0, 200.0), confidence=0.8)
        ],
        model="google/gemini-3.1-flash-lite-preview",
        raw_response={"walls": []},
        notes="ok",
    )
    meta = result.to_metadata()
    assert meta["schema_version"] == "wall_detector_v1"
    assert meta["wall_count"] == 1
    assert meta["expected_wall_count"] == EXPECTED_WALL_COUNT
    assert meta["model"] == "google/gemini-3.1-flash-lite-preview"
    assert meta["walls"][0]["bbox_xyxy"] == [10.0, 20.0, 50.0, 200.0]


def test_to_yolo_labels_is_one_line_per_wall() -> None:
    from pathlib import Path

    result = WallTeacherResult(
        image_path=Path("/tmp/c4.jpg"),
        image_width=1280,
        image_height=720,
        walls=[
            WallDetection(bbox_xyxy=(10.0, 20.0, 50.0, 200.0), confidence=0.8),
            WallDetection(bbox_xyxy=(600.0, 100.0, 640.0, 280.0), confidence=0.7),
        ],
        model="m",
    )
    text = result.to_yolo_labels()
    lines = text.splitlines()
    assert len(lines) == 2
    assert all(line.split()[0] == str(WALL_DETECTOR_CLASS_ID) for line in lines)
