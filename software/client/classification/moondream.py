from typing import Optional, Tuple, Any
import os
import base64
import requests
import cv2
import numpy as np

MOONDREAM_DETECT_URL = "https://api.moondream.ai/v1/detect"
MOONDREAM_OBJECT_NAME = "lego piece"
MOONDREAM_REQUEST_TIMEOUT_S = 5
JPEG_QUALITY = 85


def getDetection(image: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    api_key = os.getenv("MOONDREAM_API_KEY")
    if not api_key:
        return None

    image_url = _encodeImageUrl(image)
    payload = {"image_url": image_url, "object": MOONDREAM_OBJECT_NAME}
    headers = {
        "Content-Type": "application/json",
        "X-Moondream-Auth": api_key,
    }

    response = requests.post(
        MOONDREAM_DETECT_URL,
        headers=headers,
        json=payload,
        timeout=MOONDREAM_REQUEST_TIMEOUT_S,
    )
    response.raise_for_status()
    body = response.json()
    return _pickBestBox(body, image.shape[1], image.shape[0])


def getDetectionCrop(image: np.ndarray) -> Optional[np.ndarray]:
    box = getDetection(image)
    if box is None:
        return None

    x_min, y_min, x_max, y_max = box
    return image[y_min:y_max, x_min:x_max]


def _encodeImageUrl(image: np.ndarray) -> str:
    ok, image_buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise ValueError("failed to encode image")

    image_b64 = base64.b64encode(image_buffer).decode("utf-8")
    return f"data:image/jpeg;base64,{image_b64}"


def _pickBestBox(
    body: dict[str, Any], image_w: int, image_h: int
) -> Optional[Tuple[int, int, int, int]]:
    objects = body.get("objects")
    if not isinstance(objects, list) or len(objects) == 0:
        return None

    best_box = None
    best_area = 0

    for obj in objects:
        if not isinstance(obj, dict):
            continue

        try:
            x_min = float(obj["x_min"])
            y_min = float(obj["y_min"])
            x_max = float(obj["x_max"])
            y_max = float(obj["y_max"])
        except (KeyError, TypeError, ValueError):
            continue

        box = _normalizedBoxToPixels(x_min, y_min, x_max, y_max, image_w, image_h)
        if box is None:
            continue

        box_x_min, box_y_min, box_x_max, box_y_max = box
        box_area = (box_x_max - box_x_min) * (box_y_max - box_y_min)
        if box_area <= best_area:
            continue

        best_area = box_area
        best_box = box

    return best_box


def _normalizedBoxToPixels(
    x_min: float,
    y_min: float,
    x_max: float,
    y_max: float,
    image_w: int,
    image_h: int,
) -> Optional[Tuple[int, int, int, int]]:
    x1 = max(0, min(image_w, int(np.floor(min(x_min, x_max) * image_w))))
    y1 = max(0, min(image_h, int(np.floor(min(y_min, y_max) * image_h))))
    x2 = max(0, min(image_w, int(np.ceil(max(x_min, x_max) * image_w))))
    y2 = max(0, min(image_h, int(np.ceil(max(y_min, y_max) * image_h))))

    if x2 <= x1 or y2 <= y1:
        return None

    return (x1, y1, x2, y2)
