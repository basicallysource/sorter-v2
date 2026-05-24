"""Hive teacher dispatch + zone prompts shared across all adapters.

Prompts and source-role mapping live here so every adapter can pull from the same source of
truth. The actual model call lives in :mod:`teacher_adapters` — this module just dispatches
to the right adapter and exposes the legacy ``run_teacher_detection`` signature used by the
worker and the sync rerun endpoint.

Prompt changes here MUST be mirrored in ``software/sorter/backend/vision/gemini_sam_detector.py``
(see [[project_teacher_zones]]) so Hive backfills produce the same boxes the sorter produces
live.
"""

from __future__ import annotations

from typing import Any

from app.services.teacher_adapters import (
    default_model_id,
    get_adapter,
    list_adapters,
    supported_model_ids,
)


# Public for adapters + the model allow-list.
SUPPORTED_OPENROUTER_MODELS: tuple[str, ...] = supported_model_ids()
DEFAULT_OPENROUTER_MODEL: str = default_model_id()


ZONE_PROMPTS: dict[str, tuple[str, str]] = {
    "classification_chamber": (
        "The image comes from the machine's classification chamber. A top-down "
        "camera looks at a small flat tray where one LEGO piece at a time is "
        "delivered for identification. The tray is lit by a bright LED ring "
        "around its edge.",
        "Ignore the tray surface, the LED ring and its bright halo, specular "
        "reflections on the tray, and shadows cast by the piece. Do NOT shrink "
        "a piece's bounding box to exclude glare or highlights on the piece "
        "itself — glare is part of the piece.",
    ),
    "carousel": (
        "The image comes from the machine's carousel drop zone. A top-down "
        "camera looks at a rotating turntable with a black center disc where "
        "sorted pieces land.",
        "Ignore the turntable surface, the black center disc, specular "
        "reflections on the turntable, and shadows that are not part of a "
        "piece. Do NOT treat the black disc as a piece.",
    ),
    "classification_channel": (
        "The image comes from the machine's classification C-channel / C4 "
        "turntable. A top-down camera watches a rotating turntable and its "
        "transfer/drop area while parts move toward classification and ejection. "
        "The C4 turntable is the round disc in the center of the frame, surrounded "
        "by a bright white outer rim/ring. The feeder C-channel terminates at the "
        "upper-left corner of the frame and drops parts ONTO the C4 disc — pieces "
        "still queued inside that feeder channel can be visible at the very edge "
        "of the frame, but they are NOT in the C4 work zone and must be ignored.",
        "Ignore the turntable surface, fixed dark center/opening, exit chute, "
        "outlet slot, rails, screws, lips, fixed black wedges/openings, LED "
        "glare, specular reflections, and shadows. In this camera view there "
        "is a fixed lower-right opening/notch/cut-out where the exit path "
        "and shadows even if it looks like a rectangular or wedge-shaped "
        "object. The C4 rotor may show four or five evenly spaced radial "
        "divider walls/fins running from the dark center toward the outer rim; "
        "ignore those divider walls, their raised edges, and their linear "
        "shadows even when they look like long grey objects. These are machine "
        "geometry, not pieces. Only label loose physical items sitting on, "
        "beside, or moving over that geometry. "
        "Critically: ONLY detect pieces that sit on the C4 rotor disc itself "
        "(inside the round white outer ring). Any piece that is wholly or even "
        "partially outside that disc — pieces still parked in the feeder C-channel "
        "that's visible in the upper-left corner, pieces resting on the white rim, "
        "pieces hanging off the edge — must be skipped entirely. A piece whose "
        "bounding box would touch or cross the bright white rim/ring is OUT and "
        "must not be returned. Err on the side of skipping anything near the rim.",
    ),
    "c_channel": (
        "The image comes from one of the machine's feed channels. A top-down "
        "camera looks at a narrow C-shaped channel along which pieces slide "
        "toward the classification chamber.",
        "Ignore the channel surface, fixed side walls, rails, screws, slots, "
        "dark fixed openings, specular reflections, and shadows. These are "
        "machine geometry, not pieces. Only label loose physical items.",
    ),
}


SOURCE_ROLE_TO_ZONE: dict[str, str] = {
    "classification_chamber": "classification_chamber",
    "carousel": "carousel",
    "classification_channel": "classification_channel",
    "c_channel": "c_channel",
    "c_channel_1": "c_channel",
    "c_channel_2": "c_channel",
    "c_channel_3": "c_channel",
    "c_channel_full": "c_channel",
}


def normalize_openrouter_model(model: str | None) -> str:
    if isinstance(model, str):
        normalized = model.strip()
        if normalized in SUPPORTED_OPENROUTER_MODELS:
            return normalized
    return DEFAULT_OPENROUTER_MODEL


def zone_for_source_role(source_role: str | None) -> str | None:
    if not source_role:
        return None
    return SOURCE_ROLE_TO_ZONE.get(source_role)


_CLASSIFICATION_CHANNEL_PROMPT = (
    'You are detecting loose physical objects on a C4 classification turntable from a '
    'top-down {width}x{height} camera image.\n\n'
    'Task:\n'
    'Return one tight bounding box for each loose physical item that is fully inside the '
    'active C4 rotor disc. Detect LEGO/compatible plastic parts and foreign objects such '
    'as screws, coins, stones, tape, hair, wrappers, fragments, tools, or unknown debris.\n\n'
    'Active detection zone:\n'
    '- The C4 rotor disc is the round disc in the center, bounded by the bright white '
    'outer rim/ring.\n'
    '- Detect ONLY objects whose entire bounding box lies inside the rotor disc, not '
    'touching or crossing the bright white rim.\n'
    '- Skip anything on the rim, crossing the rim, hanging off the edge, or outside the disc.\n'
    '- Skip parts still queued in the feeder C-channel at the upper-left edge of the frame, '
    'even if visible.\n'
    '- Err on the side of skipping objects near the rim.\n'
    '- Pixels outside the active crop may be solid white from a polygon mask; treat this '
    'as out-of-frame, not background and not an object.\n\n'
    'Ignore fixed machine geometry:\n'
    'Do NOT detect the turntable surface, dark center/opening, outlet slot, exit chute, '
    'rails, screws, lips, fixed black wedges/openings, LED glare, specular reflections, '
    'shadows, or any fixed machine feature.\n\n'
    'C4-specific ignore rules:\n'
    '- Ignore the fixed lower-right exit opening/notch/cut-out, including its rim, dark '
    'interior, straight edges, and shadows.\n'
    '- Ignore the four or five evenly spaced radial divider walls/fins running from the '
    'dark center toward the outer rim.\n'
    '- Ignore the raised edges and long straight shadows of those divider walls/fins, even '
    'if they look like long grey objects.\n\n'
    'Detection rules:\n'
    '- Detect every distinct loose physical item exactly once.\n'
    '- Prefer splitting over grouping: if touching, overlapping, or stacked items are '
    'visually separable by silhouette, edge, color/material, studs, holes, or visible '
    'boundaries, return one box per item.\n'
    '- If a cluster is fused or visually inseparable, return one box around the cluster.\n'
    '- Include small, dark, shiny, transparent, translucent, low-contrast, partly occluded, '
    'or edge-cropped items if they are clearly physical objects inside the disc.\n'
    '- Ignore dust, scratches, stains, shadows, glare, and artifacts.\n'
    '- Ignore detections with object-confidence below 0.5.\n'
    '- Ignore objects whose bounding box is smaller than about 1% of image area unless they '
    'are clearly real physical objects.\n'
    '- Bounding boxes must be tight around the visible object extent, including glare that '
    'belongs to the object itself.\n\n'
    'Classification:\n'
    '- kind = "lego" only if the item is confidently a LEGO/compatible plastic part.\n'
    '- kind = "foreign" for screws, coins, stones, wrappers, debris, unknown objects, or '
    'anything uncertain.\n'
    '- confidence measures whether the item is a real object, not whether the class label '
    'is certain.\n\n'
    'Output JSON only:\n'
    '{{\n'
    '  "detections": [\n'
    '    {{\n'
    '      "kind": "lego|foreign",\n'
    '      "description": "<short label>",\n'
    '      "bbox": [y_min, x_min, y_max, x_max],\n'
    '      "confidence": 0.0\n'
    '    }}\n'
    '  ]\n'
    '}}\n\n'
    'bbox:\n'
    '- Normalized 0-1000 coordinates.\n'
    '- Order: [y_min, x_min, y_max, x_max].\n\n'
    'If no valid objects are visible, return:\n'
    '{{"detections":[]}}'
)


def gemini_prompt_template(zone: str) -> str:
    """Return the raw chat-style prompt template for ``zone`` with ``{width}`` and
    ``{height}`` placeholders left literal.

    Editable in admin settings — when the admin saves a custom prompt for this zone we
    store the template here, not a per-image rendered string.
    """
    if zone == "classification_channel":
        return _CLASSIFICATION_CHANNEL_PROMPT

    context, ignore_rules = ZONE_PROMPTS.get(zone, ZONE_PROMPTS["classification_chamber"])
    return (
        f"{context}\n\n"
        f"{ignore_rules}\n\n"
        "Pixels outside the active region may appear as solid white "
        "(255,255,255) where the polygon mask was applied. Treat this white "
        "border as out-of-frame — it is NOT background and NOT an object.\n\n"
        "Detection rules:\n"
        "- Detect every distinct physical item exactly once: LEGO parts AND "
        "any foreign object (screws, coins, pebbles, plastic fragments, tape, "
        "hair, wrappers, tools, etc.). Non-LEGO matters — it is how the "
        "machine catches contamination.\n"
        "- Strive for exhaustive recall: do not omit any real loose part that "
        "is visible enough to localize, including small, partly occluded, "
        "edge-cropped, low-contrast, dark, shiny, transparent, or translucent "
        "pieces. Scan the entire active crop before returning.\n"
        "- Prefer splitting over grouping: if multiple loose parts touch, "
        "overlap, stack, or partially cover each other but their visible "
        "bodies, edges, color/material changes, studs, holes, or silhouettes "
        "allow separation, return one tight box per part. Do not draw one "
        "large box around a pile of separable parts.\n"
        "- Do not detect fixed machine geometry, even if it is dark, high "
        "contrast, or shaped like a part. In particular, ignore outlet slots, "
        "exit chutes, turntable holes, fixed black shadows/openings, rails, "
        "and walls. For the C4 turntable specifically, ignore the lower-right "
        "exit opening/notch/cut-out and its rim, dark interior, straight edges, "
        "and shadows; also ignore the evenly spaced radial divider walls/fins "
        "and their long straight shadows. Do not draw boxes around these fixed "
        "features.\n"
        "- Return a tight bounding box covering each item's full extent, "
        "including any glare on the item itself.\n"
        "- Ignore objects whose bounding box is smaller than ~1% of the image "
        "area unless they are clearly a physical object (not dust/scratch).\n"
        "- If two items are touching or stacked and visually separable, "
        "return one box per item; if fused into one indistinct cluster, "
        "return a single box covering the cluster.\n"
        "- Omit detections with confidence below 0.5.\n"
        "- If no items are visible, return an empty detections array.\n\n"
        "Output format (JSON only, no markdown):\n"
        '{"detections":[{"kind":"lego|foreign","description":"<short label>",'
        '"bbox":[y_min,x_min,y_max,x_max],"confidence":0.0-1.0}]}\n\n'
        "Field semantics:\n"
        "- bbox: Gemini's normalized 0-1000 scale, order "
        "[y_min, x_min, y_max, x_max], for this {width}x{height} image.\n"
        "- kind: 'lego' if you are confident it is a LEGO/compatible plastic "
        "part; 'foreign' for anything else (screw, coin, stone, wrapper, "
        "unknown). When unsure, prefer 'foreign' — the machine must flag it "
        "for human review either way.\n"
        "- confidence: 0.9+ you are certain the item exists (regardless of "
        "kind); 0.5-0.7 uncertain whether it is an item at all vs. artifact. "
        "Confidence is about 'is this an object', NOT 'is this LEGO'."
    )


def gemini_prompt(width: int, height: int, zone: str) -> str:
    """Build the Gemini-style detection prompt for OpenAI-chat-shaped adapters.

    Public (no underscore) so :mod:`teacher_adapters.openrouter_chat` can call it. Perceptron
    builds its own much shorter instruction in its adapter and does not need this.
    """
    return gemini_prompt_template(zone).format(width=width, height=height)


def apply_teacher_result_to_sample(
    sample: Any,
    result: dict[str, Any],
    *,
    source: str,
    job_id: str | None = None,
) -> None:
    """Mutate ``sample`` in place with a teacher detection result.

    Used by both the background worker and the synchronous admin endpoint so the on-disk
    audit shape stays identical. ``source`` distinguishes ``hive_teacher_worker`` (queued
    backfill) from ``hive_teacher_inline`` (admin clicked re-run on a single sample).
    """
    from datetime import datetime, timezone

    sample.detection_algorithm = result.get("algorithm", "gemini_sam")
    sample.detection_bboxes = [list(b) for b in result["bboxes"]]
    sample.detection_count = int(result["count"])
    sample.detection_score = float(result["score"]) if result["count"] > 0 else None
    sample.review_status = "unreviewed"
    sample.review_count = 0
    sample.accepted_count = 0
    sample.rejected_count = 0
    sample.resolved_at = None
    extra = dict(sample.extra_metadata or {})
    audit: dict[str, Any] = {
        "model": result["model"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": int(result["count"]),
        "score": float(result["score"]) if result["count"] > 0 else None,
        "source": source,
    }
    if job_id is not None:
        audit["job_id"] = job_id
    extra["teacher_rerun"] = audit
    sample.extra_metadata = extra


def run_teacher_detection(
    *,
    image_bytes: bytes,
    zone: str,
    api_key: str,
    public_app_url: str,
    openrouter_model: str | None = None,
    override_prompt: str | None = None,
) -> dict[str, Any]:
    """Dispatch to the registered adapter for ``openrouter_model``.

    Returns the legacy dict shape (consumed by the worker + sync rerun endpoint) so callers
    don't need to know about the new adapter package. The detail page uses the adapter
    objects directly to get the richer ``TeacherDetectionResult`` (with latency etc.).

    ``override_prompt`` is forwarded to the adapter; pass the resolved per-zone prompt
    from :mod:`app.services.teacher_prompts` so admin-edited templates take effect.
    """
    model_id = normalize_openrouter_model(openrouter_model)
    adapter = get_adapter(model_id)
    if adapter is None:
        # normalize_openrouter_model already restricts to registered ids; this branch is for
        # callers that bypass normalization, e.g. an old job row referencing a model we
        # later removed from the registry. Fall back to the default.
        adapter = get_adapter(DEFAULT_OPENROUTER_MODEL)
        if adapter is None:
            raise RuntimeError("No teacher adapter is registered")

    result = adapter.detect(
        image_bytes=image_bytes,
        zone=zone,
        api_key=api_key,
        public_app_url=public_app_url,
        override_prompt=override_prompt,
    )
    return result.to_payload()


__all__ = [
    "DEFAULT_OPENROUTER_MODEL",
    "SOURCE_ROLE_TO_ZONE",
    "SUPPORTED_OPENROUTER_MODELS",
    "ZONE_PROMPTS",
    "apply_teacher_result_to_sample",
    "gemini_prompt",
    "list_adapters",
    "normalize_openrouter_model",
    "run_teacher_detection",
    "zone_for_source_role",
]
