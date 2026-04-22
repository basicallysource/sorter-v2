"""Brickognize HTTP client for the rt/ runtime.

Synchronous, blocking POST to the Brickognize classification API. No threads
owned here — bounded concurrency lives in ``BrickognizeClassifier``. Kept
self-contained: no imports from the legacy ``backend.classification`` module.

Types are re-implemented locally as TypedDicts — mirror of the 40-line
``brickognize_types.py`` but without the bridge import. Stable API surface.
"""

from __future__ import annotations

import io
import logging
from typing import Any, TypedDict, cast

import requests


DEFAULT_API_URL = "https://api.brickognize.com/predict/?predict_color=true"
DEFAULT_CONNECT_TIMEOUT_S = 3.0
DEFAULT_READ_TIMEOUT_S = 8.0
DEFAULT_FILTER_CATEGORIES: tuple[str, ...] = ("primo", "duplo")
ANY_COLOR_ID = "any_color"
ANY_COLOR_NAME = "Any Color"


class BrickognizeItem(TypedDict, total=False):
    id: str
    name: str
    img_url: str
    category: str
    type: str
    score: float


class BrickognizeColor(TypedDict, total=False):
    id: str
    name: str
    score: float


class BrickognizeResponse(TypedDict, total=False):
    listing_id: str
    items: list[BrickognizeItem]
    colors: list[BrickognizeColor]


class BrickognizeClient:
    """Minimal synchronous HTTP client wrapping the Brickognize /predict API."""

    def __init__(
        self,
        *,
        api_url: str | None = None,
        connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
        read_timeout_s: float = DEFAULT_READ_TIMEOUT_S,
        filter_categories: tuple[str, ...] = DEFAULT_FILTER_CATEGORIES,
        session: requests.Session | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._api_url = api_url or DEFAULT_API_URL
        self._connect_timeout_s = float(connect_timeout_s)
        self._read_timeout_s = float(read_timeout_s)
        self._filter_categories = tuple(c.lower() for c in filter_categories)
        self._session = session or requests.Session()
        self._logger = logger or logging.getLogger("rt.classification.brickognize")

    # ------------------------------------------------------------------

    def predict(self, image_bytes: bytes) -> BrickognizeResponse:
        """Post a single JPEG crop to Brickognize. Returns filtered response."""
        return self.predict_many([image_bytes])

    def predict_many(self, images_bytes: list[bytes]) -> BrickognizeResponse:
        """Post multiple JPEGs as evidence for one combined prediction."""
        if not images_bytes:
            raise ValueError("at least one image required")
        files: list[tuple[str, tuple[str, io.BytesIO, str]]] = []
        for idx, jpeg in enumerate(images_bytes):
            files.append(
                (
                    "query_image",
                    (f"image_{idx}.jpg", io.BytesIO(jpeg), "image/jpeg"),
                )
            )
        read_timeout = self._read_timeout_s + max(0, len(files) - 1) * 2.0
        headers = {"accept": "application/json"}
        response = self._session.post(
            self._api_url,
            headers=headers,
            files=files,
            timeout=(self._connect_timeout_s, read_timeout),
        )
        response.raise_for_status()
        payload = cast(BrickognizeResponse, response.json())
        if "items" in payload and self._filter_categories:
            payload["items"] = [
                item
                for item in payload.get("items", [])
                if not any(
                    flt in str(item.get("category", "")).lower()
                    for flt in self._filter_categories
                )
            ]
        return payload

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            self._logger.debug("BrickognizeClient: session close raised", exc_info=True)


# ----------------------------------------------------------------------
# Response helpers — pure-python, reusable from BrickognizeClassifier.

def pick_best_item(
    response: BrickognizeResponse | None,
) -> BrickognizeItem | None:
    if response is None:
        return None
    items = response.get("items") or []
    if not items:
        return None
    return max(items, key=lambda it: float(it.get("score", 0.0) or 0.0))


def pick_best_color(
    response: BrickognizeResponse | None,
) -> BrickognizeColor | None:
    if response is None:
        return None
    colors = response.get("colors") or []
    if not colors:
        return None
    return max(colors, key=lambda c: float(c.get("score", 0.0) or 0.0))


def encode_jpeg(image: Any, quality: int = 88) -> bytes:
    """Encode a BGR numpy array as JPEG bytes via OpenCV. Injected crop types
    already encoded are passed through."""
    if isinstance(image, (bytes, bytearray, memoryview)):
        return bytes(image)
    import cv2  # lazy import — keep the client testable without cv2 in some paths

    ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return bytes(buf.tobytes())


__all__ = [
    "BrickognizeClient",
    "BrickognizeColor",
    "BrickognizeItem",
    "BrickognizeResponse",
    "ANY_COLOR_ID",
    "ANY_COLOR_NAME",
    "DEFAULT_API_URL",
    "pick_best_color",
    "pick_best_item",
    "encode_jpeg",
]
