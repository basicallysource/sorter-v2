"""Single source of truth for writing the `cond_primary` analysis block.

Both the auto-labeler (Perceptron worker) and the human tagger on /review
go through ``upsert_condition_analysis`` so the on-disk shape is identical
regardless of source. The frontend's ``SampleConditionCard`` reads the
shape this writer produces; the schema mirrors the format the archived
sorter-side Gemini path used so existing samples render without changes.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import attributes

from app.models.sample import Sample


ANALYSIS_ID = "cond_primary"
ANALYSIS_KIND = "condition"
ANALYSIS_STAGE = "part_condition_quality"
PRIMARY_IMAGE_ASSET_ID = "img_primary"

# Allowed enum values — kept narrow so the UI can render with confidence.
# Adding a new value here needs a matching tone in SampleConditionCard.
COMPOSITION_VALUES: tuple[str, ...] = (
    "single_part",
    "compound_part",
    "multi_part",
    "empty_or_not_lego",
    "uncertain",
)
CONDITION_VALUES: tuple[str, ...] = (
    "clean_ok",
    "minor_wear",
    "dirty",
    "damaged",
    "scratched",
    "broken",
    "trash_candidate",
    "uncertain",
)
# Flags are flat booleans — frontend renders any boolean key dynamically.
# Listing the canonical names here keeps writers honest and gives the
# tagger UI something to iterate over.
FLAG_NAMES: tuple[str, ...] = (
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

# Source values land on the analysis block as ``provider``. Worth keeping
# discrete strings so downstream filters (e.g. "show only Perceptron
# auto-labels for QA") have something stable to match on.
SOURCE_PERCEPTRON = "perceptron_condition"
SOURCE_GEMINI = "gemini_condition"
SOURCE_HUMAN = "human_review"
ALLOWED_SOURCES: tuple[str, ...] = (
    SOURCE_PERCEPTRON,
    SOURCE_GEMINI,
    SOURCE_HUMAN,
)


def _coerce_choice(value: Any, allowed: tuple[str, ...]) -> str:
    if isinstance(value, str):
        candidate = value.strip()
        if candidate in allowed:
            return candidate
    return "uncertain"


def _coerce_flags(value: Any) -> dict[str, bool]:
    """Keep only boolean entries — silently drop anything else.

    The frontend iterates over flag keys generically, so the writer is the
    last line of defense against a typoed key sneaking into the payload.
    """

    if not isinstance(value, dict):
        return {}
    out: dict[str, bool] = {}
    for key, flag in value.items():
        if isinstance(key, str) and isinstance(flag, bool):
            out[key] = flag
    return out


def _coerce_confidence(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        as_float = float(value)
        if 0.0 <= as_float <= 1.0:
            return as_float
    return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    return None


def _coerce_issues(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def build_cond_primary_analysis(
    *,
    composition: str,
    condition: str,
    flags: dict[str, bool],
    source: str,
    model: str | None = None,
    confidence: float | None = None,
    part_count_estimate: int | None = None,
    visible_evidence: str | None = None,
    issues: list[str] | None = None,
    status: str = "completed",
    error: str | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shape a single `cond_primary` analysis entry.

    Caller passes already-coerced primitives — this function just packages
    them into the wire shape ``SampleConditionCard`` expects.
    """

    outputs: dict[str, Any] = {
        "composition": _coerce_choice(composition, COMPOSITION_VALUES),
        "condition": _coerce_choice(condition, CONDITION_VALUES),
        "confidence": _coerce_confidence(confidence),
        "part_count_estimate": _coerce_int(part_count_estimate),
        "flags": _coerce_flags(flags),
        "issues": _coerce_issues(issues),
        "visible_evidence": (
            visible_evidence.strip()
            if isinstance(visible_evidence, str) and visible_evidence.strip()
            else None
        ),
    }
    metadata: dict[str, Any] = {
        "schema_version": "piece_condition_v1",
        "written_at": datetime.now(timezone.utc).isoformat(),
        "source": source if source in ALLOWED_SOURCES else SOURCE_HUMAN,
    }
    if raw_payload is not None:
        metadata["raw_payload"] = copy.deepcopy(raw_payload)

    return {
        "analysis_id": ANALYSIS_ID,
        "kind": ANALYSIS_KIND,
        "stage": ANALYSIS_STAGE,
        "provider": source if source in ALLOWED_SOURCES else SOURCE_HUMAN,
        "model": model if isinstance(model, str) and model.strip() else None,
        "status": status if isinstance(status, str) and status.strip() else "completed",
        "input_asset_ids": [PRIMARY_IMAGE_ASSET_ID],
        "artifact_asset_ids": [],
        "outputs": outputs,
        "error": error if isinstance(error, str) and error.strip() else None,
        "metadata": metadata,
    }


def upsert_condition_analysis(
    sample: Sample,
    *,
    composition: str,
    condition: str,
    flags: dict[str, bool],
    source: str,
    model: str | None = None,
    confidence: float | None = None,
    part_count_estimate: int | None = None,
    visible_evidence: str | None = None,
    issues: list[str] | None = None,
    status: str = "completed",
    error: str | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replace any prior `cond_primary` entry on the sample with a fresh one.

    Reassigns ``sample.sample_payload`` to a new dict so SQLAlchemy's dirty
    tracking picks up the change without needing ``flag_modified``. Returns
    the newly written analysis block for callers that want to log it.
    """

    payload = copy.deepcopy(sample.sample_payload) if isinstance(sample.sample_payload, dict) else {}
    analyses_existing = payload.get("analyses")
    analyses = (
        [
            item
            for item in analyses_existing
            if isinstance(item, dict) and item.get("analysis_id") != ANALYSIS_ID
        ]
        if isinstance(analyses_existing, list)
        else []
    )
    analysis = build_cond_primary_analysis(
        composition=composition,
        condition=condition,
        flags=flags,
        source=source,
        model=model,
        confidence=confidence,
        part_count_estimate=part_count_estimate,
        visible_evidence=visible_evidence,
        issues=issues,
        status=status,
        error=error,
        raw_payload=raw_payload,
    )
    analyses.append(analysis)
    payload["analyses"] = analyses
    sample.sample_payload = payload
    # Belt-and-braces: even though we reassigned the whole dict, flag the
    # column explicitly so a SQLAlchemy Session.flush sees the change even
    # if the dialect's JSON-as-JSONB comparator gets clever.
    attributes.flag_modified(sample, "sample_payload")
    return analysis


def has_condition_analysis(sample: Sample) -> bool:
    """True if ``sample`` already carries a `cond_primary` analysis block."""

    payload = sample.sample_payload
    if not isinstance(payload, dict):
        return False
    analyses = payload.get("analyses")
    if not isinstance(analyses, list):
        return False
    return any(
        isinstance(item, dict) and item.get("analysis_id") == ANALYSIS_ID
        for item in analyses
    )
