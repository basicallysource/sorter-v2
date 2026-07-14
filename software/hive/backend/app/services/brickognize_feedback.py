"""Submit part/color corrections to Brickognize's feedback API.

These are confirm/reject signals against a prior /predict/ call (identified by
its listing_id): we tell Brickognize whether a specific ranked result was
correct, keyed by the rank it came back at. Brickognize can't be handed an
arbitrary "right" answer that wasn't in its results, so a color correction to a
different color reduces to rejecting the prediction.

Mirrors the sorter-side client (sorter/backend/classification/brickognize_feedback.py);
kept separate because the two backends don't share code.
"""

from __future__ import annotations

import requests

PART_FEEDBACK_URL = "https://api.brickognize.com/feedback/"
COLOR_FEEDBACK_URL = "https://api.brickognize.com/feedback/color/"
FEEDBACK_SOURCE = "external-app"
FEEDBACK_TIMEOUT_S = (30.0, 30.0)


def submit_part_feedback(
    *,
    listing_id: str,
    item_id: str,
    item_rank: int,
    is_correct: bool,
    item_type: str | None = None,
) -> None:
    payload = {
        "listing_id": listing_id,
        "item_id": str(item_id),
        "item_type": item_type or "part",
        "is_prediction_correct": bool(is_correct),
        "source": FEEDBACK_SOURCE,
        "item_rank": int(item_rank),
    }
    response = requests.post(PART_FEEDBACK_URL, json=payload, timeout=FEEDBACK_TIMEOUT_S)
    response.raise_for_status()


def submit_color_feedback(
    *,
    listing_id: str,
    color_id: str,
    color_rank: int,
    is_correct: bool,
) -> None:
    payload = {
        "listing_id": listing_id,
        "is_prediction_correct": bool(is_correct),
        "source": FEEDBACK_SOURCE,
        "color_id": str(color_id),
        "color_rank": int(color_rank),
    }
    response = requests.post(COLOR_FEEDBACK_URL, json=payload, timeout=FEEDBACK_TIMEOUT_S)
    response.raise_for_status()
