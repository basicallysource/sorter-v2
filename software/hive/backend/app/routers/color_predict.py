"""Color prediction API for the hosted-services layer.

A sorter POSTs 1..8 crop images of one piece (multipart) and gets back the
globally-active color model's prediction. Send the C4 burst crops plus any
C2/C3 channel crops of the same piece — multiview models fuse the different
lighting conditions; single-view models average their per-crop softmax.

Auth is a device token (silent enrollment, see routers/devices.py), not a
machine token — this works whether or not the sorter is registered to any
account. Every successful call is logged to color_predictions with its images
(admin-only, bucket key devices/{device_id}/color_predict/...) so the color
model can be retrained on real in-the-wild input; logging is best-effort and
never fails the prediction.
"""

from __future__ import annotations

import json
import logging
import time
import uuid as uuid_module

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from app.deps import get_current_device, get_db
from app.errors import APIError
from app.models.color_prediction import ColorPrediction
from app.models.device import Device
from app.services import color_predictor
from app.services.storage import ALLOWED_MAGIC, save_color_predict_bytes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices/color-predict", tags=["color-predict"])

MAX_IMAGES = color_predictor.MAX_PREDICT_IMAGES
MAX_IMAGE_BYTES = 2 * 1024 * 1024


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else None


def _suffix_for(data: bytes) -> str | None:
    for magic, ext in ALLOWED_MAGIC.items():
        if data.startswith(magic):
            return f".{ext}"
    return None


def _log_prediction(
    db: Session,
    device: Device,
    request: Request,
    blobs: list[bytes],
    channel_list: list[int],
    client_info: dict | None,
    result: dict,
    inference_ms: float,
) -> None:
    prediction_id = uuid_module.uuid4()
    image_keys: list[str] = []
    for seq, (data, channel) in enumerate(zip(blobs, channel_list)):
        suffix = _suffix_for(data)
        if suffix is None:
            continue
        image_keys.append(
            save_color_predict_bytes(str(device.id), str(prediction_id), seq, channel, data, suffix)
        )
    row = ColorPrediction(
        id=prediction_id,
        device_id=device.id,
        color_model_id=uuid_module.UUID(result["model_id"]) if result.get("model_id") else None,
        color_model_name=result.get("model_name"),
        color_model_filename=result.get("model_filename"),
        color_model_sha256=result.get("model_sha256"),
        multiview=result.get("multiview"),
        method=result.get("method"),
        predicted_color_id=result.get("color_id"),
        predicted_color_name=result.get("color_name"),
        confidence=result.get("confidence"),
        top=result.get("top"),
        image_keys=image_keys,
        channels=channel_list,
        image_count=len(blobs),
        scored_count=result.get("sample_count"),
        client_info=client_info,
        request_ip=_client_ip(request),
        inference_ms=inference_ms,
    )
    db.add(row)
    db.commit()


@router.post("")
async def predict_color(
    request: Request,
    images: list[UploadFile] = File(...),
    channels: str | None = Form(None, description="JSON list of camera channel numbers (2/3/4), one per image, same order. Defaults to 4."),
    client_info: str | None = Form(None, description="Optional JSON object of machine context (sorter version, piece uuid, ...). Stored with the prediction log."),
    db: Session = Depends(get_db),
    device: Device = Depends(get_current_device),
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

    parsed_client_info: dict | None = None
    if client_info:
        try:
            candidate = json.loads(client_info)
            if isinstance(candidate, dict):
                parsed_client_info = candidate
        except ValueError:
            pass

    blobs: list[bytes] = []
    for f in images:
        data = await f.read()
        if len(data) > MAX_IMAGE_BYTES:
            raise APIError(400, "Image too large", "IMAGE_TOO_LARGE")
        blobs.append(data)

    started = time.perf_counter()
    result = color_predictor.predict_bytes(db, blobs, channel_list)
    inference_ms = (time.perf_counter() - started) * 1000.0
    if result is None:
        raise APIError(503, "No active color model or no image decodable", "NO_ACTIVE_MODEL")

    try:
        _log_prediction(db, device, request, blobs, channel_list, parsed_client_info, result, inference_ms)
    except Exception:
        logger.exception("color prediction logging failed (prediction still served)")
        db.rollback()

    return result
