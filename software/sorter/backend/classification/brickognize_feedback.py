from typing import Optional

import requests

# Brickognize's feedback endpoints. These are confirm/reject signals against a
# prior /predict/ call (identified by its listing_id): you tell Brickognize
# whether a specific ranked result was correct, keyed by the rank it came back
# at. You cannot hand it an arbitrary "right" answer that wasn't in the results —
# so a color correction to a different color reduces to rejecting the prediction.
PART_FEEDBACK_URL = "https://api.brickognize.com/feedback/"
COLOR_FEEDBACK_URL = "https://api.brickognize.com/feedback/color/"
# The "source" enum value Brickognize records for feedback originating from an
# external integration (as opposed to their own site / discord / etc.).
FEEDBACK_SOURCE = "external-app"
FEEDBACK_TIMEOUT_S = (30.0, 30.0)


def submitPartFeedback(
    *,
    listing_id: str,
    item_id: str,
    item_rank: int,
    is_correct: bool,
    item_type: Optional[str] = None,
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


def submitColorFeedback(
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
