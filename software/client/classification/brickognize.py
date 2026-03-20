from typing import Callable, Optional, cast
import threading
import io
import requests
import numpy as np
import cv2
from PIL import Image
from global_config import GlobalConfig
from .brickognize_types import BrickognizeResponse, BrickognizeItem, BrickognizeColor

API_URL = "https://api.brickognize.com/predict/?predict_color=true"
ANY_COLOR = "any_color"
ANY_COLOR_NAME = "Any Color"
FILTER_CATEGORIES = ["primo", "duplo"]


def classify(
    gc: GlobalConfig,
    top_image: Optional[np.ndarray],
    bottom_image: Optional[np.ndarray],
    callback: Callable[[Optional[str], str, str, Optional[float]], None],
) -> None:
    thread = threading.Thread(
        target=_doClassify,
        args=(gc, top_image, bottom_image, callback),
        daemon=True,
    )
    thread.start()


def _doClassify(
    gc: GlobalConfig,
    top_image: Optional[np.ndarray],
    bottom_image: Optional[np.ndarray],
    callback: Callable[[Optional[str], str, str, Optional[float]], None],
) -> None:
    gc.logger.info("Brickognize: classifying piece")
    try:
        with gc.profiler.timer("classification.brickognize.total_ms"):
            top_result = None
            bottom_result = None
            if top_image is not None:
                with gc.profiler.timer("classification.brickognize.top_ms"):
                    top_result = _classifyImage(top_image)
            if bottom_image is not None:
                with gc.profiler.timer("classification.brickognize.bottom_ms"):
                    bottom_result = _classifyImage(bottom_image)

        best_item = _pickBestItem(top_result, bottom_result)
        best_color = _pickBestColor(top_result, bottom_result)
        color_id = best_color["id"] if best_color else ANY_COLOR
        color_name = best_color["name"] if best_color else ANY_COLOR_NAME
        if best_item:
            gc.logger.info(
                f"Brickognize: {best_item['id']} ({best_item['name']}) "
                f"score={best_item['score']:.2f} color={color_name}"
            )
            callback(best_item["id"], color_id, color_name, best_item["score"])
        else:
            gc.logger.warn("Brickognize: no items found")
            callback(None, color_id, color_name, None)
    except Exception as e:
        gc.logger.error(f"Brickognize: classification failed: {e}")
        callback(None, ANY_COLOR, ANY_COLOR_NAME, None)


def _classifyImage(image: np.ndarray) -> BrickognizeResponse:
    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb_image)
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="JPEG")
    payload_bytes = img_bytes.getvalue()

    files = {"query_image": ("image.jpg", io.BytesIO(payload_bytes), "image/jpeg")}
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
    top_result: Optional[BrickognizeResponse],
    bottom_result: Optional[BrickognizeResponse],
) -> Optional[BrickognizeItem]:
    all_items: list[BrickognizeItem] = []
    if top_result is not None:
        all_items += top_result.get("items", [])
    if bottom_result is not None:
        all_items += bottom_result.get("items", [])
    if not all_items:
        return None
    return max(all_items, key=lambda x: x.get("score", 0))


def _pickBestColor(
    top_result: Optional[BrickognizeResponse],
    bottom_result: Optional[BrickognizeResponse],
) -> Optional[BrickognizeColor]:
    all_colors: list[BrickognizeColor] = []
    if top_result is not None:
        all_colors += top_result.get("colors", [])
    if bottom_result is not None:
        all_colors += bottom_result.get("colors", [])
    if not all_colors:
        return None
    return max(all_colors, key=lambda x: x.get("score", 0))
