from typing import Optional, cast
import io
import os
import requests
import numpy as np
import cv2
from PIL import Image
from global_config import GlobalConfig
from .brickognize_types import BrickognizeColor, BrickognizeItem, BrickognizeResponse

API_URL = "https://api.brickognize.com/predict/?predict_color=true"
# Fallback (connect, read) timeouts in seconds for the rare gc-less call path.
# When a GlobalConfig is available the live values come from gc.timeouts
# (brickognize_connect_s / brickognize_read_s), which default to a generous 60 s
# each so slow internet degrades to "slow" rather than "ConnectTimeout failure".
API_TIMEOUT_S = (60.0, 60.0)
# Brickognize rejects requests with more than this many query images. Callers
# should pre-trim, but we hard-cap here too so a stray oversized batch degrades
# (drops the tail) instead of erroring out the whole classification.
MAX_QUERY_IMAGES = 8
FILTER_CATEGORIES = ["primo", "duplo"]


def _classifyImages(
    gc: Optional[GlobalConfig],
    images: list[np.ndarray],
    *,
    piece_uuid: Optional[str] = None,
    dump_label: Optional[str] = None,
) -> BrickognizeResponse:
    if not images:
        raise ValueError("at least one image required")
    if len(images) > MAX_QUERY_IMAGES:
        images = images[:MAX_QUERY_IMAGES]
    dump_dir = None
    if gc is not None and gc.brickognize_dump_root is not None and piece_uuid:
        dump_dir = gc.brickognize_dump_root / piece_uuid
        os.makedirs(dump_dir, exist_ok=True)
    files: list[tuple[str, tuple[str, io.BytesIO, str]]] = []
    for i, image in enumerate(images):
        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb_image)
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="JPEG", quality=95, subsampling=0)
        payload_bytes = img_bytes.getvalue()
        if dump_dir is not None:
            label = dump_label or "img"
            with open(dump_dir / f"{label}_{i:02d}.jpg", "wb") as f:
                f.write(payload_bytes)
        files.append(
            ("query_image", (f"image_{i}.jpg", io.BytesIO(payload_bytes), "image/jpeg"))
        )

    headers = {"accept": "application/json"}
    # Multi-image queries need proportionally more time — Brickognize runs
    # inference per view before combining. Add ~2 s read-timeout per
    # additional image on top of the single-image baseline.
    if gc is not None:
        connect_timeout = gc.timeouts.brickognize_connect_s
        read_timeout = gc.timeouts.brickognize_read_s
    else:
        connect_timeout, read_timeout = API_TIMEOUT_S
    read_timeout = read_timeout + max(0, len(files) - 1) * 2.0
    response = requests.post(
        API_URL,
        headers=headers,
        files=files,
        timeout=(connect_timeout, read_timeout),
    )
    response.raise_for_status()
    result = cast(BrickognizeResponse, response.json())

    # Stamp each item/color with its position in the UNFILTERED response before
    # we drop primo/duplo items. Brickognize's feedback API keys on these ranks
    # (item_rank / color_rank), so they must survive category filtering — the
    # applied item carries its original rank even if items ahead of it are cut.
    for rank, item in enumerate(result.get("items", []) or []):
        item["rank"] = rank
    for rank, color in enumerate(result.get("colors", []) or []):
        color["rank"] = rank

    result["items"] = [
        item
        for item in result["items"]
        if not any(f in item["category"].lower() for f in FILTER_CATEGORIES)
    ]
    return result


def rankedItems(result: object, n: int) -> list[BrickognizeItem]:
    """A response's first n items (after the category filter), in Brickognize's
    order, each carrying its rank in the unfiltered response."""
    items = result.get("items", []) if isinstance(result, dict) else []
    return [item for item in items if isinstance(item, dict)][:n]


def rankedColors(result: object, n: int) -> list[BrickognizeColor]:
    """A response's n highest-scoring colors, best first, each carrying its rank
    in the response."""
    colors = result.get("colors", []) if isinstance(result, dict) else []
    valid = [color for color in colors if isinstance(color, dict)]
    return sorted(valid, key=lambda color: color.get("score", 0), reverse=True)[:n]
