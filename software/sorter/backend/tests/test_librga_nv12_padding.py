from __future__ import annotations

import pytest

from vision.librga_nv12 import _slice_tight_nv12


def _padded_nv12(width: int, height: int) -> bytes:
    vstride = (height + 15) // 16 * 16
    y = bytes(range(256)) * (width * vstride // 256 + 1)
    return (y * 2)[: width * vstride * 3 // 2]


def test_slices_mpp_padded_1080p_to_tight() -> None:
    width, height = 1920, 1080  # MPP decodes this as 1920x1088
    padded = _padded_nv12(width, height)
    assert len(padded) == 1920 * 1088 * 3 // 2

    tight = _slice_tight_nv12(padded, width, height)

    assert len(tight) == width * height * 3 // 2
    # Y plane is the unpadded prefix; UV plane starts after the padded Y.
    assert tight[: width * height] == padded[: width * height]
    uv_offset = width * 1088
    assert tight[width * height :] == padded[uv_offset : uv_offset + width * height // 2]


def test_rejects_sizes_that_match_no_known_layout() -> None:
    with pytest.raises(ValueError, match="vstride"):
        _slice_tight_nv12(b"\x00" * 1000, 1920, 1080)
