from __future__ import annotations

from unittest.mock import patch

import numpy as np

from vision.handdrawn_region_provider import HanddrawnRegionProvider


def _provider_with_channel_resolutions() -> HanddrawnRegionProvider:
    saved = {
        "resolution": [1920, 1080],
        "polygons": {
            "second_channel": [[440, 160], [840, 160], [840, 560], [440, 560]],
            "third_channel": [[960, 640], [1620, 640], [1620, 1300], [960, 1300]],
        },
        "channel_angles": {"second": 0, "third": 0},
        "arc_params": {
            "second": {
                "center": [640, 360],
                "inner_radius": 100,
                "outer_radius": 200,
                "resolution": [1280, 720],
            },
            "third": {
                "center": [1296, 972],
                "inner_radius": 220,
                "outer_radius": 440,
                "resolution": [2592, 1944],
            },
        },
    }
    with patch("vision.handdrawn_region_provider.getChannelPolygons", return_value=saved):
        return HanddrawnRegionProvider()


def test_split_channel_overlay_uses_c2_resolution_metadata() -> None:
    provider = _provider_with_channel_resolutions()
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    sx, sy = provider._scaleForFrame(frame, "second_channel")

    assert sx == 1.0
    assert sy == 1.0


def test_split_channel_overlay_uses_c3_resolution_metadata() -> None:
    provider = _provider_with_channel_resolutions()
    frame = np.zeros((1944, 2592, 3), dtype=np.uint8)

    sx, sy = provider._scaleForFrame(frame, "third_channel")

    assert sx == 1.0
    assert sy == 1.0


def test_split_channel_overlay_still_falls_back_to_global_resolution() -> None:
    provider = _provider_with_channel_resolutions()
    frame = np.zeros((540, 960, 3), dtype=np.uint8)

    sx, sy = provider._scaleForFrame(frame, "carousel")

    assert sx == 0.5
    assert sy == 0.5
