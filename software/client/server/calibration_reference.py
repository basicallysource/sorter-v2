from __future__ import annotations

from typing import Final


# Seeded from the user-provided HDR Pixel reference photo of the calibration plate.
# These are intentionally stored as a stable shared reference palette for later tuning.
REFERENCE_TILE_RGB: Final[dict[str, tuple[int, int, int]]] = {
    "white": (219, 239, 243),
    "black": (27, 30, 37),
    "blue": (38, 156, 221),
    "red": (226, 43, 36),
    "green": (11, 155, 99),
    "yellow": (240, 214, 29),
}


REFERENCE_TILE_HEX: Final[dict[str, str]] = {
    label: f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
    for label, rgb in REFERENCE_TILE_RGB.items()
}
