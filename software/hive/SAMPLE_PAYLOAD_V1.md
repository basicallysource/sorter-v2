# Unified Sample Payload v1

This document defines the recommended day-0 sample format for Sorter -> Hive uploads.

The goal is to make every sample look the same regardless of whether it came from:

- classification chamber live runtime
- classification chamber manual capture
- feeder or carousel teacher capture
- settings detection tests
- later enrichments such as Gemini overlays or Brickognize results

## Why Change

The current upload format is serviceable, but it has three structural problems:

1. The canonical fields are very small, while most interesting data is pushed into `extra_metadata`.
2. Detection and classification results do not follow one shared shape.
3. Some important enrichment happens after the first upload, so the first Hive record can be incomplete.

Today, Hive stores a flat record plus `extra_metadata`:

- `source_role`
- `capture_reason`
- `captured_at`
- `detection_algorithm`
- `detection_bboxes`
- `detection_count`
- `detection_score`
- `extra_metadata`

That is fine for bootstrapping, but it will get messy once we want consistent:

- overlays
- Gemini or other detector outputs
- candidate boxes
- teacher-capture trigger context
- Brickognize or other classification outputs
- future analysis stages

## Design Goals

- One canonical JSON shape for every sample.
- One shared format for all machine analyses.
- Support incremental enrichment without creating disconnected side data.
- Keep a few denormalized columns in Hive for fast filtering and review UIs.
- Do not require a big-bang rewrite of the current upload path.

## Canonical Shape

Every sample should have a single JSON payload:

```json
{
  "schema_version": "hive_sample_v1",
  "sample": {},
  "assets": {},
  "analyses": [],
  "annotations": {},
  "provenance": {}
}
```

### `sample`

Identity and capture context.

```json
{
  "source_session_id": "20260416-abc123",
  "local_sample_id": "1713269000123-deadbeef",
  "source_role": "classification_chamber",
  "capture_reason": "live_classification",
  "capture_scope": "classification",
  "capture_mode": "runtime",
  "captured_at": "2026-04-16T08:12:00Z",
  "machine_id": "sorter-01",
  "run_id": "run-456",
  "piece_uuid": "piece-789",
  "preferred_view": "top"
}
```

Recommended enums:

| Field | Examples |
| --- | --- |
| `source_role` | `classification_chamber`, `c_channel_2`, `c_channel_3`, `carousel` |
| `capture_reason` | `live_classification`, `manual_capture`, `settings_detection_test`, `channel_move_complete`, `carousel_classic_trigger` |
| `capture_scope` | `classification`, `feeder`, `carousel` |
| `capture_mode` | `runtime`, `manual`, `settings_test`, `background_teacher`, `backfill` |
| `preferred_view` | `top`, `bottom`, `carousel`, `c_channel_2`, `c_channel_3` |

### `assets`

All images and derived artifacts live in one dictionary keyed by stable asset IDs.

```json
{
  "img_primary": {
    "kind": "crop",
    "view": "top",
    "role": "primary",
    "mime_type": "image/jpeg",
    "width_px": 512,
    "height_px": 512
  },
  "img_full_top": {
    "kind": "full_frame",
    "view": "top",
    "role": "context",
    "mime_type": "image/jpeg"
  },
  "img_overlay_det_primary": {
    "kind": "overlay",
    "view": "top",
    "role": "analysis_artifact",
    "mime_type": "image/jpeg",
    "derived_from_asset_id": "img_primary"
  },
  "img_cls_top_crop": {
    "kind": "classification_crop",
    "view": "top",
    "role": "analysis_input",
    "mime_type": "image/jpeg",
    "derived_from_asset_id": "img_primary"
  }
}
```

Recommended asset fields:

- `kind`: `crop`, `full_frame`, `overlay`, `classification_crop`, `analysis_json`, `debug_preview`
- `view`: `top`, `bottom`, `carousel`, `c_channel_2`, `c_channel_3`, `unknown`
- `role`: `primary`, `context`, `analysis_input`, `analysis_artifact`, `debug`
- `mime_type`
- `width_px`, `height_px`
- `derived_from_asset_id`

### `analyses`

All machine-produced outputs use the same structure.

```json
[
  {
    "analysis_id": "det_primary",
    "kind": "detection",
    "stage": "primary_detection",
    "provider": "gemini_sam",
    "model": "gemini-2.5-flash",
    "status": "completed",
    "input_asset_ids": ["img_primary"],
    "artifact_asset_ids": ["img_overlay_det_primary"],
    "started_at": "2026-04-16T08:12:01Z",
    "completed_at": "2026-04-16T08:12:02Z",
    "outputs": {
      "found": true,
      "primary_box_index": 0,
      "boxes": [
        {
          "box_px": [12, 34, 120, 160],
          "box_norm": [0.02, 0.07, 0.23, 0.31],
          "score": 0.92,
          "label": "piece_candidate"
        }
      ],
      "message": "Cloud vision found candidate pieces."
    },
    "error": null,
    "metadata": {
      "source_camera": "top"
    }
  },
  {
    "analysis_id": "cls_brickognize",
    "kind": "classification",
    "stage": "part_classification",
    "provider": "brickognize",
    "model": null,
    "status": "completed",
    "input_asset_ids": ["img_cls_top_crop"],
    "artifact_asset_ids": [],
    "started_at": "2026-04-16T08:12:03Z",
    "completed_at": "2026-04-16T08:12:04Z",
    "outputs": {
      "best_candidate_index": 0,
      "candidates": [
        {
          "part_id": "3001",
          "item_name": "Brick 2 x 4",
          "item_category": "Brick",
          "color_id": "5",
          "color_name": "Red",
          "confidence": 0.83,
          "preview_url": "https://..."
        }
      ],
      "source_view": "top"
    },
    "error": null,
    "metadata": {}
  }
]
```

Required shared fields:

- `analysis_id`
- `kind`: `detection` or `classification`
- `stage`
- `provider`
- `status`: `pending`, `completed`, `failed`, `skipped`
- `input_asset_ids`
- `artifact_asset_ids`
- `outputs`

Recommended shared fields:

- `model`
- `started_at`
- `completed_at`
- `error`
- `metadata`

### Detection Output Shape

All detectors should serialize into the same structure:

```json
{
  "found": true,
  "primary_box_index": 0,
  "boxes": [
    {
      "box_px": [12, 34, 120, 160],
      "box_norm": [0.02, 0.07, 0.23, 0.31],
      "score": 0.92,
      "label": "piece_candidate"
    }
  ],
  "message": "Detector message"
}
```

Notes:

- `box_px` uses `[x1, y1, x2, y2]`.
- `box_norm` is optional but strongly recommended.
- `primary_box_index` replaces ad-hoc `detection_bbox` vs `detection_candidate_bboxes`.
- Single-box detectors still emit `boxes` with one entry.

### Classification Output Shape

All classifiers should serialize into the same structure:

```json
{
  "best_candidate_index": 0,
  "candidates": [
    {
      "part_id": "3001",
      "item_name": "Brick 2 x 4",
      "item_category": "Brick",
      "color_id": "5",
      "color_name": "Red",
      "confidence": 0.83,
      "preview_url": "https://..."
    }
  ],
  "source_view": "top"
}
```

Notes:

- Brickognize, Recognize, or future classifiers should all emit `candidates`.
- A failed or empty lookup still creates an analysis record with `status = failed` or `status = completed` plus an empty `candidates` list.

### `annotations`

Human review and hand labels live here, not as unrelated `extra_metadata` keys.

```json
{
  "manual_regions": {
    "version": "hive-annotorious-v1",
    "updated_at": "2026-04-16T08:20:00Z",
    "updated_by_display_name": "Reviewer",
    "annotations": []
  },
  "manual_classification": {
    "version": "hive-classification-v1",
    "updated_at": "2026-04-16T08:21:00Z",
    "updated_by_display_name": "Reviewer",
    "part_id": "3001",
    "item_name": "Brick 2 x 4",
    "color_id": "5",
    "color_name": "Red"
  }
}
```

### `provenance`

Technical and trigger context that should travel with the sample but should not define the review schema.

```json
{
  "session_name": "runtime-2026-04-16",
  "processor": "classification_training",
  "archive_mode": "runtime_archive_only",
  "trigger": {
    "algorithm": "heatmap_diff",
    "metadata": {
      "trigger_score": 0.81,
      "trigger_hot_pixels": 1432
    }
  },
  "pipeline": {
    "sorter_backend_version": null,
    "firmware_version": null
  }
}
```

## Full Example

```json
{
  "schema_version": "hive_sample_v1",
  "sample": {
    "source_session_id": "20260416-abc123",
    "local_sample_id": "1713269000123-deadbeef",
    "source_role": "classification_chamber",
    "capture_reason": "live_classification",
    "capture_scope": "classification",
    "capture_mode": "runtime",
    "captured_at": "2026-04-16T08:12:00Z",
    "machine_id": "sorter-01",
    "run_id": "run-456",
    "piece_uuid": "piece-789",
    "preferred_view": "top"
  },
  "assets": {
    "img_primary": {
      "kind": "crop",
      "view": "top",
      "role": "primary",
      "mime_type": "image/jpeg"
    },
    "img_full_top": {
      "kind": "full_frame",
      "view": "top",
      "role": "context",
      "mime_type": "image/jpeg"
    },
    "img_overlay_det_primary": {
      "kind": "overlay",
      "view": "top",
      "role": "analysis_artifact",
      "mime_type": "image/jpeg",
      "derived_from_asset_id": "img_primary"
    },
    "img_cls_top_crop": {
      "kind": "classification_crop",
      "view": "top",
      "role": "analysis_input",
      "mime_type": "image/jpeg",
      "derived_from_asset_id": "img_primary"
    }
  },
  "analyses": [
    {
      "analysis_id": "det_primary",
      "kind": "detection",
      "stage": "primary_detection",
      "provider": "gemini_sam",
      "model": "gemini-2.5-flash",
      "status": "completed",
      "input_asset_ids": ["img_primary"],
      "artifact_asset_ids": ["img_overlay_det_primary"],
      "outputs": {
        "found": true,
        "primary_box_index": 0,
        "boxes": [
          {
            "box_px": [12, 34, 120, 160],
            "score": 0.92,
            "label": "piece_candidate"
          }
        ],
        "message": "Cloud vision found candidate pieces."
      },
      "metadata": {}
    },
    {
      "analysis_id": "cls_brickognize",
      "kind": "classification",
      "stage": "part_classification",
      "provider": "brickognize",
      "model": null,
      "status": "completed",
      "input_asset_ids": ["img_cls_top_crop"],
      "artifact_asset_ids": [],
      "outputs": {
        "best_candidate_index": 0,
        "candidates": [
          {
            "part_id": "3001",
            "item_name": "Brick 2 x 4",
            "color_id": "5",
            "color_name": "Red",
            "confidence": 0.83
          }
        ],
        "source_view": "top"
      },
      "metadata": {}
    }
  ],
  "annotations": {},
  "provenance": {
    "session_name": "runtime-2026-04-16",
    "processor": "classification_training",
    "archive_mode": "runtime_archive_only"
  }
}
```

## Transport Recommendation

Keep file upload as `multipart/form-data`, but move the metadata contract to the canonical sample payload.

Recommended request shape:

- `metadata`: JSON string containing the full canonical payload
- file parts named by asset ID, for example:
  - `img_primary`
  - `img_full_top`
  - `img_overlay_det_primary`
  - `img_cls_top_crop`

This is cleaner than a permanently hard-coded trio of:

- `image`
- `full_frame`
- `overlay`

It also allows later uploads to attach additional assets without redesigning the API again.

## Incremental Enrichment

Do not force every analysis result into the first upload.

Instead:

1. Create the sample with initial assets and analyses.
2. Allow later idempotent updates keyed by `source_session_id + local_sample_id`.
3. Append analyses and assets to the same sample record.

Recommended API direction:

- `POST /api/machine/upload`
  - create or upsert the initial sample
- `PATCH /api/machine/upload/{source_session_id}/{local_sample_id}`
  - attach new assets, analyses, or annotations

This solves the current problem where classification results often appear only after the first sample upload has already happened.

## Hive Storage Recommendation

Hive should keep both:

1. A canonical JSONB payload.
2. A small set of denormalized columns for filtering and cards.

Recommended new JSON column:

- `sample_payload`

Recommended denormalized columns to keep or add:

- `source_role`
- `capture_reason`
- `capture_scope`
- `captured_at`
- `primary_detection_provider`
- `primary_detection_found`
- `primary_detection_count`
- `primary_detection_score`
- `primary_classification_provider`
- `primary_part_id`
- `primary_color_id`
- `has_full_frame`
- `has_overlay`

The denormalized columns should be derived from `sample_payload`, not treated as the real source of truth.

## Mapping From Current Fields

| Current field | New path | Notes |
| --- | --- | --- |
| `source_session_id` | `sample.source_session_id` | unchanged |
| `local_sample_id` | `sample.local_sample_id` | unchanged |
| `source_role` | `sample.source_role` | unchanged |
| `capture_reason` | `sample.capture_reason` | unchanged |
| `detection_scope` | `sample.capture_scope` | rename for clarity |
| `source` | `provenance.source` | no longer a primary review field |
| `camera` | `sample.preferred_view` or asset `view` | prefer asset-local view when possible |
| `captured_at` | `sample.captured_at` | unchanged semantically |
| `piece_uuid` | `sample.piece_uuid` | unchanged |
| `machine_id` | `sample.machine_id` | unchanged |
| `run_id` | `sample.run_id` | unchanged |
| `preferred_camera` | `sample.preferred_view` | normalize naming |
| `input_image` | `assets.img_primary` | primary crop asset |
| `top_frame_path` | `assets.img_full_top` | full-frame asset |
| `bottom_frame_path` | `assets.img_full_bottom` | full-frame asset |
| `top_zone_path` | `assets.img_crop_top` | optional supporting crop asset |
| `bottom_zone_path` | `assets.img_crop_bottom` | optional supporting crop asset |
| `distill_result.overlay_image` | `assets.<overlay_asset_id>` | preferably referenced by analysis |
| `detection_algorithm` | `analyses[*].provider` | detector identity |
| `detection_openrouter_model` | `analyses[*].model` | detector model |
| `detection_found` | `analyses[*].outputs.found` | unified detection output |
| `detection_bbox` | `analyses[*].outputs.boxes[primary]` | normalize to `boxes[]` |
| `detection_bboxes` | `analyses[*].outputs.boxes[]` | normalize to `boxes[]` |
| `detection_candidate_bboxes` | `analyses[*].outputs.boxes[]` | same canonical shape |
| `detection_bbox_count` | derived from `analyses[*].outputs.boxes` | keep denormalized count in Hive |
| `detection_score` | `analyses[*].outputs.boxes[*].score` or summary | use denormalized summary only for UI/filtering |
| `detection_message` | `analyses[*].outputs.message` | unchanged semantically |
| `classification_result` | `analyses[*]` with `kind = classification` | no special-case payload |
| `manual_annotations` | `annotations.manual_regions` | move out of `extra_metadata` |
| `manual_classification` | `annotations.manual_classification` | move out of `extra_metadata` |
| `trigger_*` fields | `provenance.trigger.metadata.*` | keep grouped together |
| `teacher_capture` and related fields | `provenance.trigger` or `provenance.metadata` | depends on whether it caused the capture |
| `processor` | `provenance.processor` | implementation detail, still useful |
| `archive_mode` | `provenance.archive_mode` | implementation detail, still useful |
| `session_name` | `provenance.session_name` | unchanged |

## Rollout Plan

### Phase 1: Add the canonical payload without breaking current Hive

- Add `sample_payload` JSONB to Hive.
- Keep existing flat columns and `extra_metadata`.
- Teach the uploader to build `sample_payload` for all new uploads.

### Phase 2: Make new uploads payload-first

- Derive the old flat fields from `sample_payload` when saving the sample row.
- Continue filling old fields for UI and filtering.
- Stop inventing new top-level flat metadata fields.

### Phase 3: Support enrichment updates

- Add an idempotent sample update route keyed by session ID and local sample ID.
- Send later Brickognize or overlay artifacts as updates to the same sample.

### Phase 4: Backfill historical data

- Convert existing Hive samples into `sample_payload`.
- Preserve current `extra_metadata` contents under the canonical structure where possible.

### Phase 5: Retire ad-hoc metadata

- Update Hive frontend to read from `sample_payload` first.
- Reduce `extra_metadata` to temporary compatibility baggage or remove it entirely.

## Practical Day-0 Recommendation

If we want the smallest useful step right now, do this:

1. Add `sample_payload` to Hive.
2. Keep the current upload endpoint, but require new sorter uploads to send canonical payload metadata.
3. Model detection and classification through `analyses[]`.
4. Add a follow-up update path for delayed classification results.
5. Keep only a handful of denormalized top-level columns for filtering and review cards.

That gets us a stable foundation without needing to redesign the whole platform in one go.
