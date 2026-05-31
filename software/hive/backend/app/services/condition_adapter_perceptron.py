"""Perceptron Mk1 adapter for condition labeling (no grounding, plain JSON).

Asks Perceptron to look at one already-cropped piece image and return
``{composition, condition, flags, ...}``. Distinct from the detection
adapter because condition labeling needs a structured classification
response, not bounding boxes — different prompt, different parser, but
the same HTTP plumbing.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image

from app.services.teacher_adapters.base import TeacherRateLimitError


logger = logging.getLogger(__name__)


PERCEPTRON_API_TIMEOUT_S = 60.0
PERCEPTRON_MODEL_ID = "perceptron-mk1"
MAX_INPUT_EDGE_PX = 1024


_COMPOSITION_FALLBACK_VALUES = {
    "single_part",
    "compound_part",
    "multi_part",
    "empty_or_not_lego",
    "uncertain",
}
_CONDITION_FALLBACK_VALUES = {
    "clean_ok",
    "minor_wear",
    "dirty",
    "damaged",
    "scratched",
    "broken",
    "trash_candidate",
    "uncertain",
}
_FLAG_NAMES = (
    "single_part",
    "compound_part",
    "multiple_parts",
    "clean",
    "dirty",
    "damaged",
    "scratched",
    "broken",
    "trash_candidate",
)


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True, slots=True)
class ConditionAssessmentResult:
    composition: str
    condition: str
    flags: dict[str, bool]
    confidence: float | None
    part_count_estimate: int | None
    visible_evidence: str | None
    issues: list[str]
    raw_text: str
    raw_payload: dict[str, Any] | None


def _prompt() -> str:
    return (
        "You are inspecting one already-cropped image of a single LEGO piece "
        "(or what should be one). Return a single JSON object with these keys:\n"
        '  "composition": one of "single_part", "compound_part", "multi_part", '
        '"empty_or_not_lego", "uncertain"\n'
        '  "condition":   one of "clean_ok", "minor_wear", "dirty", "damaged", '
        '"scratched", "broken", "trash_candidate", "uncertain"\n'
        '  "flags": object of booleans for any of: '
        '"single_part", "compound_part", "multiple_parts", "clean", "dirty", '
        '"damaged", "scratched", "broken", "trash_candidate"\n'
        '  "confidence": float 0..1\n'
        '  "part_count_estimate": integer (0 if empty/not lego)\n'
        '  "visible_evidence": one short sentence quoting what you see\n'
        '  "issues": array of short strings (empty if none)\n'
        "\nDefinitions:\n"
        "- compound_part: a *single legitimate LEGO assembly* (e.g. a hinge with both halves, a wheel "
        "with tire and hub).\n"
        "- multi_part: TWO OR MORE separate pieces in the crop that aren't meant to be assembled.\n"
        "- scratched: visible surface scratches on otherwise intact plastic.\n"
        "- broken: chipped, cracked, missing pip/clutch — structurally damaged.\n"
        "- trash_candidate: piece is so worn / dirty / broken it shouldn't go in a sort bin.\n"
        "\nReturn ONLY the JSON object, no markdown, no explanation."
    )


def _shrink_for_upload(image_bytes: bytes) -> bytes:
    """Downscale to at most MAX_INPUT_EDGE_PX so we don't push 4K crops over the wire.

    Many sorter piece crops are already small (~200px) but C4 finalize crops can
    be much larger; capping the long edge keeps the call cheap without losing
    enough detail to flip a condition judgment.
    """

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            if max(img.width, img.height) <= MAX_INPUT_EDGE_PX:
                return image_bytes
            img.thumbnail((MAX_INPUT_EDGE_PX, MAX_INPUT_EDGE_PX), Image.LANCZOS)
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=88)
            return buf.getvalue()
    except Exception:
        return image_bytes


def _parse_json(text: str) -> dict[str, Any] | None:
    """Tolerantly extract a JSON object even if the model wrapped it in chatter."""

    stripped = text.strip()
    if not stripped:
        return None
    try:
        loaded = json.loads(stripped)
        return loaded if isinstance(loaded, dict) else None
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_RE.search(stripped)
    if not match:
        return None
    try:
        loaded = json.loads(match.group(0))
        return loaded if isinstance(loaded, dict) else None
    except json.JSONDecodeError:
        return None


def _coerce_flags(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, bool] = {}
    for key, flag in value.items():
        if isinstance(key, str) and isinstance(flag, bool):
            out[key] = flag
    return out


def _coerce_choice(value: Any, allowed: set[str]) -> str:
    if isinstance(value, str):
        candidate = value.strip()
        if candidate in allowed:
            return candidate
    return "uncertain"


def _coerce_confidence(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        clamped = max(0.0, min(1.0, float(value)))
        return clamped
    return None


def _coerce_part_count(value: Any) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0, int(value))
    return None


def _coerce_issues(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def assess_condition(
    *,
    image_bytes: bytes,
    api_key: str,
    base_url: str,
) -> ConditionAssessmentResult:
    """Ask Perceptron to label one crop. Raises on transport/HTTP errors.

    Always returns a result with at least ``composition=uncertain`` and
    ``condition=uncertain`` rather than raising on a malformed model reply —
    the result still lands in the DB so a human can override on /review.
    """

    payload_bytes = _shrink_for_upload(image_bytes)
    image_b64 = base64.b64encode(payload_bytes).decode("ascii")
    body_payload: dict[str, Any] = {
        "model": PERCEPTRON_MODEL_ID,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _prompt()},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                ],
            },
        ],
        "temperature": 0.0,
        # response_format hints at structured JSON. Perceptron's docs say the
        # field is honoured the same way OpenAI's chat endpoint honours it;
        # if ignored, the parser still extracts the JSON object from the body.
        "response_format": {"type": "json_object"},
    }
    endpoint_url = f"{base_url.rstrip('/')}/chat/completions"
    request = Request(
        endpoint_url,
        data=json.dumps(body_payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Hive-Condition/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=PERCEPTRON_API_TIMEOUT_S) as response:  # noqa: S310
            data = json.loads(response.read().decode())
    except HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            err = json.loads(raw)
            message = err.get("error", {}).get("message") or err.get("message") or err.get("detail")
        except json.JSONDecodeError:
            stripped = re.sub(r"<[^>]+>", " ", raw)
            stripped = re.sub(r"\s+", " ", stripped).strip()
            message = stripped[:200] if stripped else None
        if exc.code == 429:
            retry_after = None
            hdr = exc.headers.get("Retry-After")
            if hdr is not None:
                try:
                    retry_after = float(hdr)
                except (TypeError, ValueError):
                    retry_after = None
            raise TeacherRateLimitError(
                f"Perceptron rate-limited: {message or 'HTTP 429'}",
                retry_after_s=retry_after,
            ) from exc
        raise RuntimeError(
            f"Perceptron HTTP {exc.code} at {endpoint_url}: {message or 'unknown error'}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"Perceptron API at {endpoint_url} could not be reached: {exc}"
        ) from exc

    try:
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Perceptron returned an unexpected response shape") from exc

    parsed = _parse_json(content) or {}
    return ConditionAssessmentResult(
        composition=_coerce_choice(parsed.get("composition"), _COMPOSITION_FALLBACK_VALUES),
        condition=_coerce_choice(parsed.get("condition"), _CONDITION_FALLBACK_VALUES),
        flags=_coerce_flags(parsed.get("flags")),
        confidence=_coerce_confidence(parsed.get("confidence")),
        part_count_estimate=_coerce_part_count(parsed.get("part_count_estimate")),
        visible_evidence=(
            parsed.get("visible_evidence").strip()
            if isinstance(parsed.get("visible_evidence"), str) and parsed.get("visible_evidence").strip()
            else None
        ),
        issues=_coerce_issues(parsed.get("issues")),
        raw_text=content,
        raw_payload=data,
    )
