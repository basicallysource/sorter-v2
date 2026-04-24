"""Gemini-backed condition teacher for archived piece crop samples.

This module is a side-effect adapter for dataset enrichment: it looks at
already persisted small piece crops, asks a vision model for composition and
quality labels, and returns metadata that can be archived/uploaded as a
separate condition sample. It does not participate in the runtime piece flow.
"""

from __future__ import annotations

import base64
import math
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np

from blob_manager import BLOB_DIR, PIECE_CROPS_DIR_NAME


CONDITION_SAMPLE_SCHEMA_VERSION = "piece_condition_v1"
CONDITION_SOURCE = "piece_condition_teacher_capture"
CONDITION_CAPTURE_REASON = "piece_condition_teacher"
CONDITION_PROVIDER = "gemini_condition"
CONDITION_ANALYSIS_ID = "cond_primary"
CONDITION_STAGE = "part_condition_quality"
DEFAULT_CONDITION_OPENROUTER_MODEL = "google/gemini-3.1-flash-lite-preview"

DEFAULT_CONDITION_BACKFILL_LIMIT = 10
DEFAULT_CONDITION_MAX_CROPS_PER_PIECE = 1
CONDITION_TEACHER_TIMEOUT_S = 25.0
CONDITION_TEACHER_MAX_TOKENS = 1600

MIN_CONDITION_CROP_SIDE_PX = 8
MIN_CONDITION_CROP_MEAN_GRAY = 5.0
MIN_CONDITION_CROP_NONBLACK_RATIO = 0.02
MIN_CONDITION_CROP_P95_GRAY = 24.0
CONDITION_CROP_NONBLACK_THRESHOLD = 12

_PIECE_CROP_RE = re.compile(r"^(?P<kind>piece|wedge)_(?P<idx>\d+)\.jpg$", re.IGNORECASE)
_SEGMENT_RE = re.compile(r"^seg(?P<sequence>\d+)$", re.IGNORECASE)
_RUNTIME_PIECE_UUID_RE = re.compile(
    r"^(?:[0-9a-f]{12}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)

_COMPOSITIONS = {
    "single_part",
    "compound_part",
    "multi_part",
    "empty_or_not_lego",
    "uncertain",
}
_CONDITIONS = {
    "clean_ok",
    "minor_wear",
    "dirty",
    "damaged",
    "trash_candidate",
    "uncertain",
}


@dataclass(frozen=True, slots=True)
class ConditionCropCandidate:
    """One persisted piece crop that can become a condition sample."""

    piece_uuid: str
    path: Path
    relative_path: str
    segment_sequence: int
    kind: str
    crop_index: int
    stats: dict[str, float]


@dataclass(frozen=True, slots=True)
class ConditionAssessment:
    """Normalized Gemini assessment for one small piece crop."""

    model: str
    composition: str
    condition: str
    confidence: float
    part_count_estimate: int | None
    single_part: bool
    compound_part: bool
    multiple_parts: bool
    clean: bool
    dirty: bool
    damaged: bool
    trash_candidate: bool
    issues: tuple[str, ...]
    visible_evidence: str | None = None
    raw_payload: dict[str, Any] | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": CONDITION_SAMPLE_SCHEMA_VERSION,
            "provider": CONDITION_PROVIDER,
            "model": self.model,
            "status": "completed",
            "composition": self.composition,
            "condition": self.condition,
            "confidence": self.confidence,
            "part_count_estimate": self.part_count_estimate,
            "flags": {
                "single_part": self.single_part,
                "compound_part": self.compound_part,
                "multiple_parts": self.multiple_parts,
                "clean": self.clean,
                "dirty": self.dirty,
                "damaged": self.damaged,
                "trash_candidate": self.trash_candidate,
            },
            "issues": list(self.issues),
            "visible_evidence": self.visible_evidence,
            "raw_payload": self.raw_payload,
        }


def _clamp01(value: Any, *, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    if not math.isfinite(float(value)):
        return default
    return max(0.0, min(1.0, float(value)))


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    return bool(value) if isinstance(value, bool) else default


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return max(0, int(value))
    return None


def _clean_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _normalize_choice(value: Any, allowed: set[str], default: str) -> str:
    if isinstance(value, str):
        candidate = value.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "single": "single_part",
            "single_lego_part": "single_part",
            "compound": "compound_part",
            "assembly": "multi_part",
            "multiple_parts": "multi_part",
            "multi": "multi_part",
            "not_lego": "empty_or_not_lego",
            "empty": "empty_or_not_lego",
            "clean": "clean_ok",
            "ok": "clean_ok",
            "worn": "minor_wear",
            "minor_scratches": "minor_wear",
            "broken": "damaged",
            "trash": "trash_candidate",
        }
        candidate = aliases.get(candidate, candidate)
        if candidate in allowed:
            return candidate
    return default


def _condition_system_prompt() -> str:
    return (
        "You are a meticulous LEGO sorting quality-control teacher. "
        "Analyze exactly the crop image provided. Return only one valid JSON "
        "object, with no markdown, prose, or code fences."
    )


def _condition_prompt(width: int, height: int) -> str:
    return (
        "The image is a small crop of one tracked object from a LEGO sorting "
        "machine. It may contain one part, a legitimate compound LEGO item, "
        "multiple separable LEGO pieces, an unclear fragment, or no useful LEGO "
        "part. Do not identify the catalog part number or color; only judge "
        "composition and physical condition.\n\n"
        "Composition labels:\n"
        "- single_part: exactly one standalone LEGO/compatible part is visible. "
        "It is not visibly attached to a second separable part.\n"
        "- compound_part: one legitimate LEGO compound/accessory unit that is "
        "designed to be handled as one item, for example a steering-wheel unit, "
        "a wheel fixed on an axle, or a small wheel/holder component that is "
        "visibly connected and moves as one physical item.\n"
        "- multi_part: two or more separable LEGO/compatible parts are visible. "
        "Use this for stacked plates/bricks, arbitrary mini assemblies, parts "
        "lying side by side, parts touching/overlapping, or a second part "
        "peeking out from under/behind the main part. If multiple separable "
        "items are plausibly present, prefer multi_part over single_part.\n"
        "- empty_or_not_lego: no LEGO/compatible part is visible, or the crop is "
        "only machine/background/foreign non-LEGO material.\n"
        "- uncertain: the evidence is too blurry, cropped, dark, or occluded to "
        "make a reliable composition call.\n\n"
        "Condition labels:\n"
        "- clean_ok: clean and structurally sound enough for normal sorting/use.\n"
        "- minor_wear: usable, with only light scratches, normal scuffs, or tiny "
        "cosmetic wear.\n"
        "- dirty: visible dirt, grime, dust clumps, residue, stickers/glue, or "
        "contamination that should be cleaned before reuse.\n"
        "- damaged: visible cracks, stress whitening, warped plastic, bitten or "
        "chewed marks, torn edges, broken clips, missing chunks, or deep gouges.\n"
        "- trash_candidate: severe damage or contamination; likely should be "
        "discarded rather than sorted as a reusable part.\n"
        "- uncertain: crop quality does not support a reliable condition call.\n\n"
        "Judgement rules:\n"
        "- Be strict about single_part: a second visible part, even partly "
        "hidden or underneath, should make composition multi_part.\n"
        "- Be fair about compound_part: only use it when the visible components "
        "look like an intended LEGO compound/accessory item, not an arbitrary "
        "stack or accidental pile.\n"
        "- Transparent or translucent parts still count as parts when their "
        "outline, edge, refraction, studs, holes, tint, or shadow is visible.\n"
        "- Do not call fixed machine geometry, black crop background, shadows, "
        "or glare a LEGO part.\n"
        "- Base the decision only on visible evidence. If unsure, say uncertain "
        "and explain what is ambiguous.\n"
        "- Use trash_candidate only for severe defects; otherwise prefer dirty "
        "or damaged with the specific issue listed.\n\n"
        "Output JSON schema:\n"
        "{"
        '"composition":"single_part|compound_part|multi_part|empty_or_not_lego|uncertain",'
        '"part_count_estimate":1,'
        '"condition":"clean_ok|minor_wear|dirty|damaged|trash_candidate|uncertain",'
        '"flags":{'
        '"single_part":true,'
        '"compound_part":false,'
        '"multiple_parts":false,'
        '"clean":true,'
        '"dirty":false,'
        '"damaged":false,'
        '"trash_candidate":false'
        "},"
        '"issues":["short issue strings"],'
        '"visible_evidence":"one concise sentence explaining the visible evidence",'
        '"confidence":0.0'
        "}\n\n"
        f"Image size: {width}x{height}px."
    )


def parse_condition_assessment(payload: dict[str, Any], *, model: str) -> ConditionAssessment:
    """Normalize a raw condition-teacher JSON object."""

    flags = payload.get("flags")
    flags = flags if isinstance(flags, dict) else {}
    composition = _normalize_choice(payload.get("composition"), _COMPOSITIONS, "uncertain")
    condition = _normalize_choice(payload.get("condition"), _CONDITIONS, "uncertain")

    single_part = _coerce_bool(flags.get("single_part"), default=composition == "single_part")
    compound_part = _coerce_bool(flags.get("compound_part"), default=composition == "compound_part")
    multiple_parts = _coerce_bool(flags.get("multiple_parts"), default=composition == "multi_part")
    clean = _coerce_bool(flags.get("clean"), default=condition in {"clean_ok", "minor_wear"})
    dirty = _coerce_bool(flags.get("dirty"), default=condition == "dirty")
    damaged = _coerce_bool(flags.get("damaged"), default=condition in {"damaged", "trash_candidate"})
    trash_candidate = _coerce_bool(
        flags.get("trash_candidate"),
        default=condition == "trash_candidate",
    )

    raw_issues = payload.get("issues")
    issues = tuple(
        item.strip()
        for item in raw_issues
        if isinstance(item, str) and item.strip()
    ) if isinstance(raw_issues, list) else ()

    return ConditionAssessment(
        model=model,
        composition=composition,
        condition=condition,
        confidence=_clamp01(payload.get("confidence"), default=0.0),
        part_count_estimate=_coerce_int(payload.get("part_count_estimate")),
        single_part=single_part,
        compound_part=compound_part,
        multiple_parts=multiple_parts,
        clean=clean,
        dirty=dirty,
        damaged=damaged,
        trash_candidate=trash_candidate,
        issues=issues,
        visible_evidence=_clean_string(payload.get("visible_evidence")),
        raw_payload=payload,
    )


def condition_crop_stats(path: Path) -> dict[str, float]:
    """Return compact quality stats for a persisted crop image."""

    gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if gray is None or getattr(gray, "size", 0) <= 0:
        return {
            "width": 0.0,
            "height": 0.0,
            "mean_gray": 0.0,
            "nonblack_ratio": 0.0,
            "p95_gray": 0.0,
        }
    return {
        "width": float(gray.shape[1]),
        "height": float(gray.shape[0]),
        "mean_gray": float(gray.mean()),
        "nonblack_ratio": float((gray > CONDITION_CROP_NONBLACK_THRESHOLD).mean()),
        "p95_gray": float(np.percentile(gray, 95)),
    }


def condition_crop_is_usable(stats: dict[str, float]) -> bool:
    return (
        stats.get("width", 0.0) >= MIN_CONDITION_CROP_SIDE_PX
        and stats.get("height", 0.0) >= MIN_CONDITION_CROP_SIDE_PX
        and stats.get("mean_gray", 0.0) >= MIN_CONDITION_CROP_MEAN_GRAY
        and stats.get("nonblack_ratio", 0.0) >= MIN_CONDITION_CROP_NONBLACK_RATIO
        and stats.get("p95_gray", 0.0) >= MIN_CONDITION_CROP_P95_GRAY
    )


def _relative_to_blob(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(BLOB_DIR.resolve()))
    except Exception:
        return str(path)


def _relative_piece_crop_path(path: Path, root: Path) -> str:
    try:
        return str(Path(PIECE_CROPS_DIR_NAME) / path.resolve().relative_to(root.resolve()))
    except Exception:
        return _relative_to_blob(path)


def _parse_piece_crop(path: Path) -> tuple[str, int, str, int] | None:
    name_match = _PIECE_CROP_RE.match(path.name)
    if name_match is None:
        return None
    segment_match = _SEGMENT_RE.match(path.parent.name)
    if segment_match is None:
        return None
    piece_uuid = path.parent.parent.name
    if not piece_uuid or _RUNTIME_PIECE_UUID_RE.match(piece_uuid) is None:
        return None
    return (
        piece_uuid,
        int(segment_match.group("sequence")),
        name_match.group("kind").lower(),
        int(name_match.group("idx")),
    )


def condition_source_key(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    path = Path(raw)
    parts = path.parts
    if PIECE_CROPS_DIR_NAME in parts:
        index = parts.index(PIECE_CROPS_DIR_NAME)
        return str(Path(*parts[index:]))
    return raw


def iter_condition_crop_candidates(
    *,
    piece_crops_root: Path | None = None,
    existing_source_keys: set[str] | None = None,
    force: bool = False,
    randomize: bool = False,
    since_ts: float | None = None,
    until_ts: float | None = None,
) -> Iterable[ConditionCropCandidate]:
    """Yield usable crop candidates from the piece-crop archive."""

    root = piece_crops_root or (BLOB_DIR / PIECE_CROPS_DIR_NAME)
    if not root.exists():
        return

    existing = existing_source_keys or set()
    paths = [
        path
        for path in root.rglob("*.jpg")
        if path.is_file() and _parse_piece_crop(path) is not None
    ]
    if randomize:
        random.shuffle(paths)
    else:
        paths.sort(
            key=lambda item: item.stat().st_mtime if item.exists() else 0.0,
            reverse=True,
        )
    for path in paths:
        try:
            mtime = path.stat().st_mtime
        except Exception:
            continue
        if since_ts is not None and mtime < since_ts:
            continue
        if until_ts is not None and mtime > until_ts:
            continue
        parsed = _parse_piece_crop(path)
        if parsed is None:
            continue
        piece_uuid, sequence, kind, crop_index = parsed
        relative_path = _relative_piece_crop_path(path, root)
        key = condition_source_key(relative_path)
        if not force and key is not None and key in existing:
            continue
        stats = condition_crop_stats(path)
        if not condition_crop_is_usable(stats):
            continue
        yield ConditionCropCandidate(
            piece_uuid=piece_uuid,
            path=path,
            relative_path=relative_path,
            segment_sequence=sequence,
            kind=kind,
            crop_index=crop_index,
            stats=stats,
        )


def select_condition_crop_candidates(
    *,
    limit: int,
    max_crops_per_piece: int = DEFAULT_CONDITION_MAX_CROPS_PER_PIECE,
    piece_crops_root: Path | None = None,
    existing_source_keys: set[str] | None = None,
    force: bool = False,
    randomize: bool = False,
    since_ts: float | None = None,
    until_ts: float | None = None,
) -> list[ConditionCropCandidate]:
    """Return a bounded set of crop candidates, limiting repeats per piece."""

    max_items = max(0, int(limit))
    if max_items <= 0:
        return []
    per_piece_limit = max(1, int(max_crops_per_piece))
    selected: list[ConditionCropCandidate] = []
    per_piece: dict[str, int] = {}
    for candidate in iter_condition_crop_candidates(
        piece_crops_root=piece_crops_root,
        existing_source_keys=existing_source_keys,
        force=force,
        randomize=randomize,
        since_ts=since_ts,
        until_ts=until_ts,
    ):
        if per_piece.get(candidate.piece_uuid, 0) >= per_piece_limit:
            continue
        selected.append(candidate)
        per_piece[candidate.piece_uuid] = per_piece.get(candidate.piece_uuid, 0) + 1
        if len(selected) >= max_items:
            break
    return selected


def _encode_image_for_llm(path: Path) -> tuple[str, int, int]:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None or getattr(image, "size", 0) <= 0:
        raise ValueError("Condition crop image could not be decoded.")
    height, width = image.shape[:2]
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("Condition crop image could not be encoded.")
    return base64.b64encode(encoded.tobytes()).decode("ascii"), int(width), int(height)


class GeminiConditionTeacher:
    """OpenRouter/Gemini assessor for one small tracked-piece crop."""

    def assess_image(
        self,
        image_path: Path,
        *,
        model: str | None = None,
    ) -> ConditionAssessment:
        from server.services.llm_client import (
            chat_completion,
            extract_json_object,
            message_text,
            normalize_openrouter_model,
        )

        normalized_model = normalize_openrouter_model(model or DEFAULT_CONDITION_OPENROUTER_MODEL)
        image_b64, width, height = _encode_image_for_llm(image_path)
        messages = [
            {"role": "system", "content": _condition_system_prompt()},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _condition_prompt(width, height)},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                ],
            },
        ]

        try:
            response = chat_completion(
                messages,
                model=normalized_model,
                response_format={"type": "json_object"},
                max_tokens=CONDITION_TEACHER_MAX_TOKENS,
                timeout=CONDITION_TEACHER_TIMEOUT_S,
            )
        except Exception:
            response = chat_completion(
                messages,
                model=normalized_model,
                max_tokens=CONDITION_TEACHER_MAX_TOKENS,
                timeout=CONDITION_TEACHER_TIMEOUT_S,
            )
        try:
            payload = extract_json_object(message_text(response.choices[0].message.content))
        except Exception as exc:
            raise RuntimeError("Gemini condition teacher returned invalid JSON") from exc
        return parse_condition_assessment(payload, model=normalized_model)


__all__ = [
    "CONDITION_ANALYSIS_ID",
    "CONDITION_CAPTURE_REASON",
    "CONDITION_PROVIDER",
    "CONDITION_SAMPLE_SCHEMA_VERSION",
    "CONDITION_SOURCE",
    "CONDITION_STAGE",
    "DEFAULT_CONDITION_OPENROUTER_MODEL",
    "ConditionAssessment",
    "ConditionCropCandidate",
    "GeminiConditionTeacher",
    "_condition_prompt",
    "condition_crop_is_usable",
    "condition_crop_stats",
    "condition_source_key",
    "parse_condition_assessment",
    "select_condition_crop_candidates",
]
