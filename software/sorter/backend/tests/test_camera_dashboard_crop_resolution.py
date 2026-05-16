from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from server import shared_state
from server.routers import cameras


def _vision_manager(*, classification_channel_setup: bool):
    return SimpleNamespace(
        _usesClassificationChannelSetup=lambda: classification_channel_setup,
    )


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

    with patch("server.routers.cameras.getChannelPolygons", return_value=saved):
        spec = cameras._dashboard_crop_spec("c_channel_2", 800, 800)

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

    with patch("server.routers.cameras.getChannelPolygons", return_value=saved):
        spec = cameras._dashboard_crop_spec("c_channel_3", 800, 800)

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
    old_vm = shared_state.vision_manager
    shared_state.vision_manager = _vision_manager(classification_channel_setup=True)
    try:
        with patch("server.routers.cameras.getChannelPolygons", return_value=saved):
            spec = cameras._dashboard_crop_spec("carousel", 800, 800)
    finally:
        shared_state.vision_manager = old_vm

    assert spec is not None
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

    cropped = cameras._apply_dashboard_crop(frame, spec)

    assert cropped.shape == (4, 4, 3)
    assert cropped[0, 0].tolist() == [100, 100, 100]
    assert cropped[3, 3].tolist() == [230, 230, 230]


def test_dashboard_classification_crop_uses_per_camera_quad_resolution() -> None:
    saved = {
        "resolution": [1920, 1080],
        "polygons": {
            "top": [[100, 100], [300, 100], [300, 300], [100, 300]],
        },
        "quad_params": {
            "class_top": {"resolution": [400, 400]},
        },
    }

    with patch("server.routers.cameras.getClassificationPolygons", return_value=saved):
        spec = cameras._dashboard_crop_spec("classification_top", 800, 800)

    assert spec is not None
    assert spec["kind"] == "rectified"
    assert spec["size"] == (496, 496)
