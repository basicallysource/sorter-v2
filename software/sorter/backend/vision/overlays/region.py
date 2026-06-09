"""Region annotation overlays — zone polygons and section labels."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from vision.handdrawn_region_provider import HanddrawnRegionProvider


class RegionOverlay:
    """Draws region annotations via region_provider.annotateFrame().

    Used for the feeder camera in default layout.
    """

    category = "regions"

    def __init__(self, region_provider) -> None:
        self._region_provider = region_provider

    def annotate(self, frame: np.ndarray) -> np.ndarray:
        return self._region_provider.annotateFrame(frame)

    def metadata(self) -> dict[str, object] | list[dict[str, object]]:
        describe = getattr(self._region_provider, "describeOverlayMetadata", None)
        if callable(describe):
            return describe()
        return {
            "type": "regions",
            "category": self.category,
        }


class ChannelRegionOverlay:
    """Draws channel-specific region annotations.

    Used for split_feeder channels (c_channel_2, c_channel_3, carousel).
    Requires a HanddrawnRegionProvider.
    """

    category = "regions"

    def __init__(self, region_provider, poly_key: str) -> None:
        self._region_provider = region_provider
        self._poly_key = poly_key

    def annotate(self, frame: np.ndarray) -> np.ndarray:
        from vision.handdrawn_region_provider import HanddrawnRegionProvider

        if isinstance(self._region_provider, HanddrawnRegionProvider):
            return self._region_provider.annotateFrameForChannel(frame, self._poly_key)
        return frame

    def metadata(self) -> dict[str, object] | list[dict[str, object]]:
        describe = getattr(self._region_provider, "describeOverlayMetadata", None)
        if callable(describe):
            return describe(self._poly_key)
        return {
            "type": "channel_regions",
            "category": self.category,
            "poly_key": self._poly_key,
        }
