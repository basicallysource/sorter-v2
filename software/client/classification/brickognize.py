from typing import Callable, Optional, cast
import threading
import io
import requests
import numpy as np
from PIL import Image
from global_config import GlobalConfig
from .brickognize_types import BrickognizeResponse, BrickognizeItem

API_URL = "https://api.brickognize.com/predict/"
FILTER_CATEGORIES = ["primo", "duplo"]


def classify(
    gc: GlobalConfig,
    top_image: np.ndarray,
    bottom_image: np.ndarray,
    callback: Callable[[Optional[str]], None],
) -> None:
    thread = threading.Thread(
        target=_doClassify,
        args=(gc, top_image, bottom_image, callback),
        daemon=True,
    )
    thread.start()


def _doClassify(
    gc: GlobalConfig,
    top_image: np.ndarray,
    bottom_image: np.ndarray,
    callback: Callable[[Optional[str]], None],
) -> None:
    gc.logger.info("Brickognize: classifying piece")
    try:
        top_result = _classifyImage(top_image)
        bottom_result = _classifyImage(bottom_image)

        best_item = _pickBestItem(top_result, bottom_result)
        if best_item:
            gc.logger.info(
                f"Brickognize: {best_item['id']} ({best_item['name']}) "
                f"score={best_item['score']:.2f}"
            )
            callback(best_item["id"])
        else:
            gc.logger.warn("Brickognize: no items found")
            callback(None)
    except Exception as e:
        gc.logger.error(f"Brickognize: classification failed: {e}")
        callback(None)


def _classifyImage(image: np.ndarray) -> BrickognizeResponse:
    img = Image.fromarray(image)
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="JPEG")
    img_bytes.seek(0)

    files = {"query_image": ("image.jpg", img_bytes, "image/jpeg")}
    headers = {"accept": "application/json"}

    response = requests.post(API_URL, headers=headers, files=files)
    response.raise_for_status()
    result = cast(BrickognizeResponse, response.json())

    result["items"] = [
        item
        for item in result["items"]
        if not any(f in item["category"].lower() for f in FILTER_CATEGORIES)
    ]
    return result


def _pickBestItem(
    top_result: BrickognizeResponse,
    bottom_result: BrickognizeResponse,
) -> Optional[BrickognizeItem]:
    all_items = top_result.get("items", []) + bottom_result.get("items", [])
    if not all_items:
        return None
    return max(all_items, key=lambda x: x.get("score", 0))
