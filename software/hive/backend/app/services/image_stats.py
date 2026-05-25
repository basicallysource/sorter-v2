"""Per-sample image quality stats — exposure + clipping.

A few cheap numpy summaries of the grayscale histogram are enough to
flag obvious failure modes (lights-off batch, sensor-saturation streak)
without trying to be a full IQA model:

  - luminance_mean    : average pixel intensity 0..255
  - luminance_p05/p95 : 5th / 95th percentile — robust min/max
  - clipped_low_ratio : fraction of pixels at <5  (crushed shadows)
  - clipped_high_ratio: fraction of pixels at >250 (blown highlights)

Computed once at upload + backfilled for old rows. The :class:`ExposureStats`
dataclass mirrors the columns 1:1 so callers can stick them into the ORM
row without remembering field names.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import IO

import numpy as np
from PIL import Image, UnidentifiedImageError


logger = logging.getLogger(__name__)


# Thresholds the filter UI uses. Tuned for the sorter's clean-disc /
# C-channel framings — most "normal" frames sit in 60-200 mean luminance.
# Anything under 35 looks like the lights-off batch the user flagged.
UNDEREXPOSED_MEAN_MAX = 35.0
UNDEREXPOSED_CLIPPED_LOW = 0.60
OVEREXPOSED_MEAN_MIN = 210.0
OVEREXPOSED_CLIPPED_HIGH = 0.40


@dataclass(frozen=True, slots=True)
class ExposureStats:
    luminance_mean: float
    luminance_p05: float
    luminance_p95: float
    clipped_low_ratio: float
    clipped_high_ratio: float

    def classify(self) -> str:
        if (
            self.luminance_mean <= UNDEREXPOSED_MEAN_MAX
            or self.clipped_low_ratio >= UNDEREXPOSED_CLIPPED_LOW
        ):
            return "underexposed"
        if (
            self.luminance_mean >= OVEREXPOSED_MEAN_MIN
            or self.clipped_high_ratio >= OVEREXPOSED_CLIPPED_HIGH
        ):
            return "overexposed"
        return "normal"


def compute_exposure_stats_bytes(image_bytes: bytes) -> ExposureStats | None:
    """Cheap grayscale histogram summary. ``None`` for un-decodable input."""

    if not image_bytes:
        return None
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img.load()
            gray = img.convert("L")
            arr = np.asarray(gray, dtype=np.uint8)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.warning("compute_exposure_stats_bytes: skipping un-decodable image: %s", exc)
        return None
    if arr.size == 0:
        return None
    p05, p95 = np.percentile(arr, (5, 95))
    return ExposureStats(
        luminance_mean=float(arr.mean()),
        luminance_p05=float(p05),
        luminance_p95=float(p95),
        clipped_low_ratio=float((arr < 5).mean()),
        clipped_high_ratio=float((arr > 250).mean()),
    )


def compute_exposure_stats_from_stream(stream: IO[bytes]) -> ExposureStats | None:
    """Read the full stream, compute stats, rewind. Mirrors the pHash helper."""

    pos = stream.tell()
    try:
        return compute_exposure_stats_bytes(stream.read())
    finally:
        try:
            stream.seek(pos)
        except (OSError, ValueError):
            pass
