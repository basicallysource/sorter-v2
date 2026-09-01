"""Vision-model "which upstream crops are the same piece" matcher.

Given a classified piece, this builds the piece's C4 anchor image plus ONE
numbered contact-sheet grid of the heuristic's candidate C2/C3 crops, asks a
vision model (via OpenRouter) which numbered cells show the same physical piece,
and returns the picked crop local_ids. Populates piece_crop_ai_predictions.

The grid format (all candidates in a single image, numbered) was chosen over one
image per crop after an offline experiment: it matched human labels with ~perfect
precision at ~20x lower cost, and — crucially — it respects the "piece must be
100% inside the crop" convention the human labels follow. See the labeling page
for how a stored prediction pre-selects the AI's picks instead of the heuristic's.

Runs off-thread of the request path (a script / background task), so it reads
crop bytes straight from the storage backend rather than the HTTP image routes.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import math
import re
import time
import urllib.request
from typing import Any, Optional
from uuid import UUID

from datetime import datetime, timezone

from PIL import Image, ImageDraw
from sqlalchemy.orm import Session

from app.config import settings
from app.models.machine_channel_crop import MachineChannelCrop
from app.models.machine_piece_image import MachinePieceImage
from app.models.piece_crop_ai_prediction import PieceCropAiPrediction
from app.services.channel_crop_lookup import find_possible_crops
from app.services.channel_crop_lookup_params import DEFAULT_PARAMS
from app.services.storage_backend import get_backend

log = logging.getLogger(__name__)

DEFAULT_MATCH_MODEL = "google/gemini-3.5-flash"
OPENROUTER_TIMEOUT_S = 180.0

CELL = 96
LABEL_H = 14
ANCHOR_MAX = 512
MAX_ANCHOR_VIEWS = 3

GRID_PROMPT = (
    "Image 1 shows one LEGO piece photographed in the classification chamber of a "
    "sorting machine (possibly several views of it side by side).\n"
    "Image 2 is a numbered grid of small crops from cameras EARLIER in the machine. "
    "Some crops may show the same physical piece moments before it reached the "
    "chamber; most show other pieces.\n\n"
    "Find every numbered cell that shows the SAME physical piece as Image 1 — same "
    "shape/mold AND same color. Judge by appearance only.\n"
    "Only count a cell if the piece is COMPLETELY inside the crop (not cut off at an "
    "edge). If the same piece appears but is partially cut off, do not count that cell.\n"
    "If no cell qualifies, return an empty list.\n\n"
    'Respond with valid JSON only, no markdown: {"matches": [cell numbers], '
    '"reasoning": "one short sentence"}'
)


class AiMatchError(RuntimeError):
    pass


def _load_image(key: str) -> Optional[Image.Image]:
    try:
        raw = get_backend().read_bytes(key)
    except FileNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001 — storage errors shouldn't kill a batch
        log.warning("ai-match: failed to read %s: %s", key, exc)
        return None
    try:
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        log.warning("ai-match: undecodable image %s: %s", key, exc)
        return None


def _anchor_keys(db: Session, machine_id: UUID, piece_uuid: str) -> list[str]:
    # The piece's classification-channel (C4) burst, preferred; fall back to any
    # of its images. Ordered by seq so the first views (usually sharpest) win.
    rows = (
        db.query(MachinePieceImage.channel, MachinePieceImage.seq, MachinePieceImage.image_key)
        .filter(
            MachinePieceImage.machine_id == machine_id,
            MachinePieceImage.piece_uuid == piece_uuid,
            MachinePieceImage.image_key.isnot(None),
        )
        .order_by(MachinePieceImage.seq.asc())
        .all()
    )
    c4 = [r.image_key for r in rows if r.channel == DEFAULT_PARAMS.classification_channel_id]
    keys = c4 if c4 else [r.image_key for r in rows]
    return keys[:MAX_ANCHOR_VIEWS]


def _crop_key(db: Session, machine_id: UUID, local_id: int) -> Optional[str]:
    row = (
        db.query(MachineChannelCrop.image_key)
        .filter(MachineChannelCrop.machine_id == machine_id, MachineChannelCrop.local_id == local_id)
        .first()
    )
    return row.image_key if row and row.image_key else None


def _build_anchor_image(images: list[Image.Image]) -> Image.Image:
    h = min(min(v.height for v in images), ANCHOR_MAX)
    images = [v.resize((max(1, int(v.width * h / v.height)), h), Image.BILINEAR) for v in images]
    out = Image.new("RGB", (sum(v.width for v in images), max(v.height for v in images)), (255, 255, 255))
    x = 0
    for v in images:
        out.paste(v, (x, 0))
        x += v.width
    return out


def _build_grid(cells: list[tuple[int, Image.Image]]) -> Image.Image:
    n = len(cells)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    grid = Image.new("RGB", (cols * (CELL + 2), rows * (CELL + LABEL_H + 2)), (255, 255, 255))
    draw = ImageDraw.Draw(grid)
    for i, (_local_id, img) in enumerate(cells):
        scale = min(CELL / img.width, CELL / img.height)
        thumb = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.BILINEAR)
        r, c = divmod(i, cols)
        x = c * (CELL + 2)
        y = r * (CELL + LABEL_H + 2)
        panel = Image.new("RGB", (CELL, CELL + LABEL_H), (30, 30, 30))
        panel.paste(thumb, ((CELL - thumb.width) // 2, LABEL_H + (CELL - thumb.height) // 2))
        grid.paste(panel, (x, y))
        draw.text((x + 3, y + 1), str(i + 1), fill=(255, 255, 0))
    return grid


def _image_part(img: Image.Image) -> dict[str, Any]:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


def _call_openrouter(model: str, content: list[dict[str, Any]], api_key: str) -> tuple[dict[str, Any], Optional[float]]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.1,
        "max_tokens": 2048,
        "usage": {"include": True},
    }
    req = urllib.request.Request(
        f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": settings.public_app_url,
            "X-Title": "Hive Piece-Crop AI Matcher",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=OPENROUTER_TIMEOUT_S) as resp:  # noqa: S310
            data = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001
        raise AiMatchError(f"OpenRouter request failed: {exc}") from exc
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise AiMatchError("OpenRouter returned an unexpected response shape") from exc
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise AiMatchError(f"Model response contained no JSON: {text[:200]!r}")
    parsed = json.loads(match.group())
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    cost = usage.get("cost") if isinstance(usage.get("cost"), (int, float)) and not isinstance(usage.get("cost"), bool) else None
    return parsed, cost


def match_piece_crops(
    db: Session,
    machine_id: UUID,
    piece_uuid: str,
    api_key: str,
    model: str = DEFAULT_MATCH_MODEL,
    limit: int = 60,
) -> dict[str, Any]:
    """Ask the vision model which candidate crops are the same piece.

    Returns {candidate_local_ids, same_local_ids, reasoning, cost_usd, model,
    elapsed_ms, arrival_ts}. Raises AiMatchError if the piece has no usable
    candidates/anchor or the model call fails.
    """
    lookup = find_possible_crops(db, machine_id, piece_uuid, limit=limit)
    candidates = lookup.get("candidates", [])
    candidates = [c for c in candidates if c.get("available")]
    if not candidates:
        raise AiMatchError("Piece has no available candidate crops")

    anchor_keys = _anchor_keys(db, machine_id, piece_uuid)
    anchor_imgs = [img for img in (_load_image(k) for k in anchor_keys) if img is not None]
    if not anchor_imgs:
        raise AiMatchError("Piece has no readable anchor image")

    cells: list[tuple[int, Image.Image]] = []
    for c in candidates:
        key = _crop_key(db, machine_id, c["local_id"])
        img = _load_image(key) if key else None
        if img is not None:
            cells.append((c["local_id"], img))
    if not cells:
        raise AiMatchError("None of the candidate crop images could be read")

    anchor = _build_anchor_image(anchor_imgs)
    grid = _build_grid(cells)
    content = [{"type": "text", "text": GRID_PROMPT}, _image_part(anchor), _image_part(grid)]

    start = time.monotonic()
    parsed, cost = _call_openrouter(model, content, api_key)
    elapsed_ms = int((time.monotonic() - start) * 1000)

    raw_matches = parsed.get("matches") or []
    picked_positions = {
        int(p) for p in raw_matches if isinstance(p, (int, float)) or (isinstance(p, str) and p.strip().isdigit())
    }
    candidate_local_ids = [local_id for local_id, _ in cells]
    same_local_ids = [
        local_id for pos, (local_id, _) in enumerate(cells, start=1) if pos in picked_positions
    ]

    return {
        "model": model,
        "reasoning": str(parsed.get("reasoning") or "")[:1000] or None,
        "candidate_local_ids": candidate_local_ids,
        "same_local_ids": same_local_ids,
        "cost_usd": cost,
        "elapsed_ms": elapsed_ms,
        "arrival_ts": lookup.get("arrival_ts"),
    }


def store_prediction(db: Session, machine_id: UUID, piece_uuid: str, result: dict[str, Any]) -> PieceCropAiPrediction:
    """Upsert the AI prediction for a piece (one row per machine+piece; re-run
    overwrites). Caller commits."""
    row = (
        db.query(PieceCropAiPrediction)
        .filter(
            PieceCropAiPrediction.machine_id == machine_id,
            PieceCropAiPrediction.piece_uuid == piece_uuid,
        )
        .first()
    )
    if row is None:
        row = PieceCropAiPrediction(machine_id=machine_id, piece_uuid=piece_uuid)
        db.add(row)
    row.model = result["model"]
    row.reasoning = result.get("reasoning")
    row.candidate_local_ids = result["candidate_local_ids"]
    row.same_local_ids = result["same_local_ids"]
    row.cost_usd = result.get("cost_usd")
    row.updated_at = datetime.now(timezone.utc)
    return row
