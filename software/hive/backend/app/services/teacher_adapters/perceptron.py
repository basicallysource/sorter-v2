"""Perceptron Mk1 adapter — calls Perceptron's OpenAI-compatible API directly.

Per the official Perceptron docs (https://docs.perceptron.inc/) the API exposes a
``POST /v1/chat/completions`` endpoint that follows the OpenAI Chat Completions schema:

    client = OpenAI(api_key=..., base_url="https://api.perceptron.inc/v1")
    response = client.chat.completions.create(
        model="perceptron-mk1",
        messages=[{"role": "user", "content": [{"type": "text", ...}, {"type": "image_url", ...}]}],
        extra_body={"vision_config": {"enable_thinking": True}},
    )

Going through Perceptron's own API (rather than OpenRouter's chat shim) is the only way
to reliably get back the model's native ``<point_box>`` XML grounding output. The user
sets ``perceptron_api_key`` on their profile; this adapter looks it up via
``secret_kind = "perceptron"`` and hits the endpoint directly.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image

from .base import TeacherDetectionResult, TeacherRateLimitError


logger = logging.getLogger(__name__)


PERCEPTRON_API_TIMEOUT_S = 60.0
PERCEPTRON_MODEL_ID = "perceptron-mk1"


# Two known Perceptron output shapes, both 0-1000 XYXY:
#
#   1. Native XML tags (what we saw before vision_config):
#        <point_box mention="lego" confidence="0.95"> (148,244) (228,350) </point_box>
#
#   2. Python-repr style list-of-dicts (what vision_config grounding now emits):
#        [{'point_box': (891,402), (939,495), 'label': 'loose_lego_piece_or_foreign_object'}, ...]
#      Note: the dict syntax is technically invalid Python — 'point_box' is followed by
#      two bare tuples rather than one value. Regex tolerates that just fine; we match
#      the *pair* of coordinate tuples right after the 'point_box' key.
_POINT_BOX_XML_RE = re.compile(
    r'<point_box(?P<attrs>[^>]*)>\s*'
    r'\(\s*(?P<x1>-?\d+(?:\.\d+)?)\s*,\s*(?P<y1>-?\d+(?:\.\d+)?)\s*\)'
    r'\s*'
    r'\(\s*(?P<x2>-?\d+(?:\.\d+)?)\s*,\s*(?P<y2>-?\d+(?:\.\d+)?)\s*\)'
    r'\s*</point_box>',
    re.IGNORECASE | re.DOTALL,
)
_POINT_BOX_REPR_RE = re.compile(
    r"""['"]point_box['"]\s*:\s*"""
    r"\(\s*(?P<x1>-?\d+(?:\.\d+)?)\s*,\s*(?P<y1>-?\d+(?:\.\d+)?)\s*\)"
    r"\s*,\s*"
    r"\(\s*(?P<x2>-?\d+(?:\.\d+)?)\s*,\s*(?P<y2>-?\d+(?:\.\d+)?)\s*\)",
    re.IGNORECASE | re.DOTALL,
)
# Label or mention attribute, captured after the same point_box block for kind assignment.
_REPR_LABEL_AFTER_BOX_RE = re.compile(
    r"['\"](?:label|mention)['\"]\s*:\s*['\"](?P<label>[^'\"]+)['\"]",
    re.IGNORECASE,
)
_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def _decode_image_size(image_bytes: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(image_bytes)) as img:
        return int(img.width), int(img.height)


def _zone_instruction(zone: str) -> str:
    """Bare detect-style instruction. Perceptron's grounded XML mode is driven by
    ``vision_config.annotation_format = "box"`` — the instruction text only specifies
    *where to look* and how to split composite assemblies.

    Splitting hint matters: a "wheel" in everyday language is one object but in LEGO
    terms it's two pieces (rubber tire + plastic hub), and clip/hook parts attached to
    bricks count separately too. Without an explicit "one box per piece" cue Perceptron
    groups composite items into a single bbox and undercounts.
    """
    splitting = (
        " Return one box per individual lego element — a wheel counts as two pieces "
        "(tire + hub), and any clip, hook or small attached part also counts separately. "
        "If no lego pieces are visible, return no detections. Do not box the disc, "
        "the radial sectors, the center button, the feeder channel walls, or any "
        "other fixed machine geometry — the round rotor disc itself is NOT a wheel."
    )
    if zone == "classification_channel":
        return (
            "Detect each individual lego piece and foreign object on the C4 rotor disc, "
            "ignoring the bright white outer rim, parts on the rim, "
            "and parts still in the upper-left feeder channel." + splitting
        )
    if zone == "c_channel":
        return (
            "Detect each individual lego piece and foreign object inside the C-channel "
            "feed track." + splitting
        )
    if zone == "classification_chamber":
        return "Detect each individual lego piece on the small flat tray." + splitting
    if zone == "carousel":
        return (
            "Detect each individual lego piece on the rotating turntable, ignoring the "
            "black center disc." + splitting
        )
    return "Detect each individual lego piece and foreign object." + splitting


# What the model should look for, sent as Perceptron's native ``classes`` parameter.
# Brick-shaped categories only — we deliberately omit "lego tire" / "lego wheel hub"
# because the round rotor disc itself triggers a false "wheel" hit when no real parts
# are on the disc (the model boxed the entire frame as a single wheel). A real wheel
# in the feed will still be detected as "lego brick" or "lego piece" with a sensibly
# small box; we lose the specific label but gain not boxing the disc.
_ZONE_CLASSES: dict[str, list[str]] = {
    "classification_channel": [
        "lego brick", "lego plate", "lego tile", "lego slope",
        "lego clip", "lego hook", "foreign object",
    ],
    "c_channel": [
        "lego brick", "lego plate", "lego tile", "lego slope",
        "lego clip", "lego hook", "foreign object",
    ],
    "classification_chamber": ["lego piece", "foreign object"],
    "carousel": ["lego piece", "foreign object"],
}

# Drop any detection that covers more than this fraction of the image area. No real
# loose lego piece in any of the four zones fills half the frame — a hit that big is
# the model boxing fixed machine geometry (the rotor disc, the feeder channel walls,
# etc.). Tuned empirically: a chunky 2x4 brick in the C4 view is ~3% of frame.
_MAX_BOX_AREA_FRACTION = 0.50


def _classify_label(label: str) -> str:
    lowered = label.lower()
    return "lego" if any(w in lowered for w in ("lego", "brick", "plate", "tile", "piece", "tire", "wheel", "stud")) else "foreign"


def _scale_xyxy_0_1000(
    ax: float, ay: float, bx: float, by: float, width: int, height: int
) -> tuple[int, int, int, int] | None:
    sx = width / 1000.0
    sy = height / 1000.0
    x1n, x2n = sorted((ax, bx))
    y1n, y2n = sorted((ay, by))
    x1 = int(max(0.0, min(float(width), x1n * sx)))
    y1 = int(max(0.0, min(float(height), y1n * sy)))
    x2 = int(max(0.0, min(float(width), x2n * sx)))
    y2 = int(max(0.0, min(float(height), y2n * sy)))
    if x2 <= x1 or y2 <= y1:
        return None
    # Drop frame-spanning boxes: the model occasionally returns a single point_box
    # covering the entire image (e.g. when the empty rotor disc is mistaken for a
    # "wheel"). No real loose lego piece fills half the frame in any of our zones,
    # so any box that large is the model boxing fixed geometry.
    if (x2 - x1) * (y2 - y1) > _MAX_BOX_AREA_FRACTION * width * height:
        return None
    return x1, y1, x2, y2


def _parse_point_box_attrs(attrs: str) -> dict[str, str]:
    return {key.lower(): value for key, value in _ATTR_RE.findall(attrs)}


def _extract_point_boxes(text: str, width: int, height: int) -> list[dict[str, Any]]:
    """Parse Perceptron's grounded output in either XML or Python-repr form.

    Both formats use 0-1000 XYXY normalized coordinates. We try XML first (the legacy
    shape and the documented one), then fall back to Python-repr (what vision_config
    grounding actually emits in practice). They never appear in the same response, so
    whichever has matches wins.
    """
    detections: list[dict[str, Any]] = []

    # 1. Try the documented <point_box> XML form first.
    for match in _POINT_BOX_XML_RE.finditer(text):
        attrs = _parse_point_box_attrs(match.group("attrs") or "")
        try:
            ax = float(match.group("x1"))
            ay = float(match.group("y1"))
            bx = float(match.group("x2"))
            by = float(match.group("y2"))
        except (TypeError, ValueError):
            continue
        coords = _scale_xyxy_0_1000(ax, ay, bx, by, width, height)
        if coords is None:
            continue
        try:
            confidence = float(attrs.get("confidence", "0.8"))
        except (TypeError, ValueError):
            confidence = 0.8
        if confidence < 0.5:
            continue
        label = (attrs.get("mention") or attrs.get("label") or "piece").strip() or "piece"
        x1, y1, x2, y2 = coords
        detections.append(
            {
                "kind": _classify_label(label),
                "description": label,
                "bbox": [x1, y1, x2, y2],
                "confidence": confidence,
            }
        )
    if detections:
        return detections

    # 2. Fall back to the Python-repr list-of-dicts shape vision_config emits.
    for match in _POINT_BOX_REPR_RE.finditer(text):
        try:
            ax = float(match.group("x1"))
            ay = float(match.group("y1"))
            bx = float(match.group("x2"))
            by = float(match.group("y2"))
        except (TypeError, ValueError):
            continue
        coords = _scale_xyxy_0_1000(ax, ay, bx, by, width, height)
        if coords is None:
            continue
        # Look for a label in the same dict (between this point_box and the next), so
        # multiple boxes don't all inherit the first dict's label.
        tail_end = text.find("{", match.end())
        tail = text[match.end(): tail_end if tail_end != -1 else min(match.end() + 200, len(text))]
        label_match = _REPR_LABEL_AFTER_BOX_RE.search(tail)
        label = label_match.group("label").strip() if label_match else "piece"
        # vision_config doesn't emit per-detection confidence — default to high since the
        # model already self-filtered by confidence before composing the response.
        x1, y1, x2, y2 = coords
        detections.append(
            {
                "kind": _classify_label(label),
                "description": label,
                "bbox": [x1, y1, x2, y2],
                "confidence": 0.9,
            }
        )

    return detections


def _call_perceptron_chat(
    *,
    api_key: str,
    base_url: str,
    instruction: str,
    classes: list[str],
    image_b64: str,
) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
    """POST to Perceptron's OpenAI-compatible /chat/completions endpoint.

    Returns (assistant_text, usage_dict_or_none, raw_response).

    Perceptron's chat-completions endpoint accepts vendor-specific options as a nested
    ``vision_config`` object — that's the only place the docs explicitly show extras on
    the chat path ("extra_body={'vision_config': {'enable_thinking': True}}" in the
    Quickstart). Putting ``annotation_format`` / ``classes`` / ``reasoning`` as top-level
    fields gets them silently dropped, which is what we observed (the model kept replying
    in prose). Nested inside ``vision_config`` they're honoured and the model emits the
    structured ``<point_box>`` XML we parse.
    """
    endpoint_url = f"{base_url.rstrip('/')}/chat/completions"
    body_payload: dict[str, Any] = {
        "model": PERCEPTRON_MODEL_ID,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                ],
            },
        ],
        # Native Perceptron grounding parameters live under vision_config — see
        # https://docs.perceptron.inc/quickstart for the canonical shape.
        "vision_config": {
            "annotation_format": "box",
            "classes": classes,
            "enable_thinking": False,
        },
        "temperature": 0.0,
    }

    body = json.dumps(body_payload).encode()
    request = Request(
        endpoint_url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Hive-Teacher/1.0",
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
            # Strip HTML so a Cloudflare 502 doesn't dominate the error banner.
            stripped = re.sub(r"<[^>]+>", " ", raw)
            stripped = re.sub(r"\s+", " ", stripped).strip()
            message = stripped[:200] if stripped else None
        if exc.code == 429:
            retry_after = None
            try:
                hdr = exc.headers.get("Retry-After")
                if hdr is not None:
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
        raise RuntimeError(f"Perceptron API at {endpoint_url} could not be reached: {exc}") from exc

    try:
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Perceptron returned an unexpected response shape") from exc
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
    return content, usage, data


class PerceptronAdapter:
    """Perceptron Mk1 via the provider's OpenAI-compatible /v1/chat/completions endpoint."""

    model_id = "perceptron/perceptron-mk1"
    display_name = "Perceptron Mk1"
    adapter_kind = "perceptron"
    secret_kind = "perceptron"
    notes = "Purpose-built detection model. Calls Perceptron's native API directly."
    # Perceptron documents 300 req/min for /chat/completions and recommends a 4-worker
    # pool as a default — see https://docs.perceptron.inc/scaling. Empirically at 4 +
    # 0.2s we sit at ~2.5 req/s (half the quota) because individual calls take ~400ms.
    # Push concurrency to 6 and shorten spacing to 0.15s to land around ~3.5-4 req/s
    # with comfortable headroom before the 5/s ceiling; the worker's 429-with-Retry-After
    # backoff catches the rare overshoot without disturbing the rest of the pool.
    max_concurrent = 7
    min_interval_s = 0.15

    def detect(
        self,
        *,
        image_bytes: bytes,
        zone: str,
        api_key: str,
        public_app_url: str,
        override_prompt: str | None = None,
    ) -> TeacherDetectionResult:
        # Late import to avoid circular dependency with app.config -> services -> base.
        from app.config import settings

        width, height = _decode_image_size(image_bytes)
        if width <= 0 or height <= 0:
            raise RuntimeError("Sample image has zero dimensions")

        # Use the caller-supplied override if any (admin-edited settings prompt or
        # compare-page ad-hoc textarea). Falls back to the built-in short native
        # instruction. NOTE: long chat-style overrides will pull Perceptron into
        # conversational prose mode regardless of vision_config — that's a tradeoff
        # the editor accepts when they save a non-trivial custom prompt.
        instruction = (
            override_prompt.strip()
            if override_prompt and override_prompt.strip()
            else _zone_instruction(zone)
        )
        classes = _ZONE_CLASSES.get(zone, ["lego piece", "foreign object"])
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        base_url = getattr(settings, "PERCEPTRON_BASE_URL", "https://api.perceptron.inc/v1")

        start = time.monotonic()
        text, usage, raw = _call_perceptron_chat(
            api_key=api_key,
            base_url=base_url,
            instruction=instruction,
            classes=classes,
            image_b64=image_b64,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        detections = _extract_point_boxes(text, width, height)
        detections.sort(key=lambda d: d["confidence"], reverse=True)
        bboxes = [d["bbox"] for d in detections]
        score = detections[0]["confidence"] if detections else 0.0

        cost_usd: float | None = None
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        if isinstance(usage, dict):
            cv = usage.get("cost") or usage.get("cost_usd")
            if isinstance(cv, (int, float)) and not isinstance(cv, bool):
                cost_usd = float(cv)
            pt = usage.get("prompt_tokens") or usage.get("input_tokens")
            if isinstance(pt, int) and not isinstance(pt, bool):
                prompt_tokens = pt
            ct = usage.get("completion_tokens") or usage.get("output_tokens")
            if isinstance(ct, int) and not isinstance(ct, bool):
                completion_tokens = ct

        # If the API didn't bill us inline, compute cost from the published $/M rates
        # (0.15 input / 1.50 output per million tokens, per docs.perceptron.inc/models).
        if cost_usd is None and prompt_tokens is not None and completion_tokens is not None:
            cost_usd = (prompt_tokens / 1_000_000) * 0.15 + (completion_tokens / 1_000_000) * 1.50

        return TeacherDetectionResult(
            model=self.model_id,
            algorithm="perceptron_mk1",
            bboxes=bboxes,
            score=score,
            count=len(bboxes),
            image_width=width,
            image_height=height,
            detections=detections,
            cost_usd=cost_usd,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            elapsed_ms=elapsed_ms,
            adapter_kind=self.adapter_kind,
            raw_response={"text": text, "full": raw},
        )
