"""Color prediction API for machines.

A sorter POSTs 1..8 crop images of one piece (multipart) and gets back the
globally-active color model's prediction. Send the C4 burst crops plus any
C2/C3 channel crops of the same piece — multiview models fuse the different
lighting conditions; single-view models average their per-crop softmax.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.deps import get_current_machine, get_db
from app.errors import APIError
from app.models.machine import Machine
from app.services import color_predictor

router = APIRouter(prefix="/api/machine/color-predict", tags=["color-predict"])

MAX_IMAGES = color_predictor.MAX_PREDICT_IMAGES
MAX_IMAGE_BYTES = 2 * 1024 * 1024


@router.post("")
async def predict_color(
    images: list[UploadFile] = File(...),
    channels: str | None = Form(None, description="JSON list of camera channel numbers (2/3/4), one per image, same order. Defaults to 4."),
    db: Session = Depends(get_db),
    _machine: Machine = Depends(get_current_machine),
) -> dict:
    if not images:
        raise APIError(400, "At least one image required", "NO_IMAGES")
    if len(images) > MAX_IMAGES:
        raise APIError(400, f"At most {MAX_IMAGES} images", "TOO_MANY_IMAGES")

    channel_list: list[int] = [4] * len(images)
    if channels:
        try:
            parsed = json.loads(channels)
        except ValueError:
            raise APIError(400, "channels must be a JSON list", "BAD_CHANNELS")
        if not isinstance(parsed, list) or len(parsed) != len(images):
            raise APIError(400, "channels must match images in length", "BAD_CHANNELS")
        try:
            channel_list = [int(c) for c in parsed]
        except (TypeError, ValueError):
            raise APIError(400, "channels must be integers", "BAD_CHANNELS")

    blobs: list[bytes] = []
    for f in images:
        data = await f.read()
        if len(data) > MAX_IMAGE_BYTES:
            raise APIError(400, "Image too large", "IMAGE_TOO_LARGE")
        blobs.append(data)

    result = color_predictor.predict_bytes(db, blobs, channel_list)
    if result is None:
        raise APIError(503, "No active color model or no image decodable", "NO_ACTIVE_MODEL")
    return result
