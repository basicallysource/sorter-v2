from __future__ import annotations

from unittest.mock import patch

import numpy as np

from vision import dashboard_crop


def test_dashboard_crop_uses_c2_channel_resolution_metadata() -> None:
    saved = {
        "resolution": [1920, 1080],
        "polygons": {
            "second_channel": [[100, 100], [300, 100], [300, 300], [100, 300]],
        },
        "arc_params": {
            "second": {"resolution": [400, 400]},
        },
    }

    with patch("vision.dashboard_crop.get_channel_polygons", return_value=saved):
        spec = dashboard_crop.dashboard_crop_spec("c_channel_2", 800, 800)

    assert spec is not None
    assert spec["kind"] == "bbox_masked"
    np.testing.assert_allclose(
        spec["polygons"][0],
        np.array([[200, 200], [600, 200], [600, 600], [200, 600]], dtype=np.float32),
    )


def test_dashboard_crop_uses_c3_channel_resolution_metadata() -> None:
    saved = {
        "resolution": [1920, 1080],
        "polygons": {
            "third_channel": [[100, 100], [300, 100], [300, 300], [100, 300]],
        },
        "arc_params": {
            "third": {"resolution": [800, 800]},
        },
    }

    with patch("vision.dashboard_crop.get_channel_polygons", return_value=saved):
        spec = dashboard_crop.dashboard_crop_spec("c_channel_3", 800, 800)

    assert spec is not None
    assert spec["kind"] == "bbox_masked"
    np.testing.assert_allclose(
        spec["polygons"][0],
        np.array([[100, 100], [300, 100], [300, 300], [100, 300]], dtype=np.float32),
    )


def test_dashboard_crop_uses_c4_classification_channel_resolution_metadata() -> None:
    saved = {
        "resolution": [1920, 1080],
        "polygons": {
            "classification_channel": [[100, 100], [300, 100], [300, 300], [100, 300]],
        },
        "arc_params": {
            "classification_channel": {"resolution": [400, 400]},
        },
    }
    with patch("vision.dashboard_crop.get_channel_polygons", return_value=saved):
        spec = dashboard_crop.dashboard_crop_spec("carousel", 800, 800)
        alias_spec = dashboard_crop.dashboard_crop_spec("classification_channel", 800, 800)

    assert spec is not None
    assert alias_spec is not None
    np.testing.assert_allclose(spec["polygons"][0], alias_spec["polygons"][0])
    assert spec["kind"] == "bbox_masked"
    np.testing.assert_allclose(
        spec["polygons"][0],
        np.array([[200, 200], [600, 200], [600, 600], [200, 600]], dtype=np.float32),
    )


def test_dashboard_masked_crop_paints_pixels_outside_polygon_light_gray() -> None:
    frame = np.full((8, 8, 3), 100, dtype=np.uint8)
    spec = {
        "kind": "bbox_masked",
        "polygons": [
            np.array([[2, 2], [6, 2], [2, 6]], dtype=np.float32),
        ],
    }

    cropped = dashboard_crop.apply_dashboard_crop(frame, spec)

    assert cropped.shape == (4, 4, 3)
    assert cropped[0, 0].tolist() == [100, 100, 100]
    assert cropped[3, 3].tolist() == [230, 230, 230]
