from dataclasses import dataclass, field, fields
from typing import Any, List, Optional, Tuple
from enum import Enum
import uuid
import time


class PieceStage(str, Enum):
    created = "created"
    distributing = "distributing"
    distributed = "distributed"


class ClassificationStatus(str, Enum):
    pending = "pending"
    classifying = "classifying"
    classified = "classified"
    unknown = "unknown"
    not_found = "not_found"
    multi_drop_fail = "multi_drop_fail"


@dataclass
class CarouselMotionSample:
    observed_at: float
    piece_angle_deg: float
    carousel_angle_deg: float
    piece_speed_deg_per_s: float
    carousel_speed_deg_per_s: float
    sync_ratio: float


@dataclass
class KnownObject:
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    stage: PieceStage = PieceStage.created
    classification_status: ClassificationStatus = ClassificationStatus.pending
    part_id: Optional[str] = None
    part_name: Optional[str] = None
    part_category: Optional[str] = None
    color_id: str = "any_color"
    color_name: str = "Any Color"
    category_id: Optional[str] = None
    confidence: Optional[float] = None
    destination_bin: Optional[Tuple[int, int, int]] = None
    thumbnail: Optional[str] = None
    top_image: Optional[str] = None
    bottom_image: Optional[str] = None
    preview_jpeg_path: Optional[str] = None
    # Full classification chamber (carousel) frame captured at the instant
    # this piece was locked for drop — base64 JPEG, max 1024 px wide so the
    # event payload stays bounded. Used on the detail page to visually verify
    # the classification against the Brickognize reference image.
    drop_snapshot: Optional[str] = None
    brickognize_preview_url: Optional[str] = None
    brickognize_source_view: Optional[str] = None
    bin_id: Optional[str] = None
    distribution_reason: Optional[str] = None
    # Captured timestamps of the crops actually shipped to Brickognize for
    # classification (subset of the tracker's sector snapshots). The frontend
    # uses these to highlight which crops participated in the final call.
    recognition_used_crop_ts: List[float] = field(default_factory=list)
    tracked_global_id: Optional[int] = None
    classification_channel_size_class: Optional[str] = None
    classification_channel_zone_state: Optional[str] = None
    classification_channel_zone_center_deg: Optional[float] = None
    classification_channel_exit_deg: Optional[float] = None
    classification_channel_zone_half_width_deg: Optional[float] = None
    classification_channel_soft_guard_deg: Optional[float] = None
    classification_channel_hard_guard_deg: Optional[float] = None
    carousel_motion_sync_ratio: Optional[float] = None
    carousel_motion_sync_ratio_avg: Optional[float] = None
    carousel_motion_sync_ratio_min: Optional[float] = None
    carousel_motion_sync_ratio_max: Optional[float] = None
    carousel_motion_piece_speed_deg_per_s: Optional[float] = None
    carousel_motion_platter_speed_deg_per_s: Optional[float] = None
    carousel_motion_sample_count: int = 0
    carousel_motion_under_sync_sample_count: int = 0
    carousel_motion_over_sync_sample_count: int = 0
    carousel_motion_samples: List[CarouselMotionSample] = field(default_factory=list)
    feeding_started_at: Optional[float] = None
    carousel_detected_confirmed_at: Optional[float] = None
    first_carousel_seen_ts: Optional[float] = None
    # Polar angle on the carousel (degrees) at the instant the piece was
    # first observed in a carousel-source zone. Used by the classification
    # channel recognizer to gate firing until the piece has traversed a
    # minimum angular distance, guaranteeing viewing-angle diversity for
    # the accumulated crops independent of rotation speed.
    first_carousel_seen_angle_deg: Optional[float] = None
    carousel_rotate_started_at: Optional[float] = None
    carousel_rotated_at: Optional[float] = None
    carousel_snapping_started_at: Optional[float] = None
    carousel_snapping_completed_at: Optional[float] = None
    carousel_next_baseline_captured_at: Optional[float] = None
    carousel_next_ready_at: Optional[float] = None
    classified_at: Optional[float] = None
    distributing_at: Optional[float] = None
    distribution_target_selected_at: Optional[float] = None
    distribution_motion_started_at: Optional[float] = None
    distribution_positioned_at: Optional[float] = None
    distributed_at: Optional[float] = None
    _carousel_motion_last_piece_angle_deg: Optional[float] = None
    _carousel_motion_last_carousel_angle_deg: Optional[float] = None
    _carousel_motion_last_observed_at: Optional[float] = None
    _carousel_motion_piece_delta_sum_deg: float = 0.0
    _carousel_motion_platter_delta_sum_deg: float = 0.0

    @classmethod
    def from_dossier(cls, payload: dict[str, Any]) -> "KnownObject":
        """Reciprocal of ``utils.event.knownObjectToEvent`` — rehydrate a
        ``KnownObject`` from a persisted dossier dict (SQLite
        ``piece_dossiers.payload_json`` or a WS ``KnownObjectData`` payload).

        Unknown keys are ignored; missing keys fall back to dataclass defaults.
        ``stage`` / ``classification_status`` strings are coerced to enums.
        ``carousel_motion_samples`` entries accept either dicts or existing
        ``CarouselMotionSample`` instances.
        """
        if not isinstance(payload, dict):
            raise TypeError("KnownObject.from_dossier requires a dict payload")

        field_names = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {}

        piece_uuid = payload.get("uuid")
        if isinstance(piece_uuid, str) and piece_uuid.strip():
            kwargs["uuid"] = piece_uuid

        def _maybe(key: str) -> None:
            if key in payload and key in field_names:
                kwargs[key] = payload[key]

        for key in (
            "created_at",
            "updated_at",
            "part_id",
            "part_name",
            "part_category",
            "color_id",
            "color_name",
            "category_id",
            "confidence",
            "tracked_global_id",
            "thumbnail",
            "top_image",
            "bottom_image",
            "preview_jpeg_path",
            "drop_snapshot",
            "brickognize_preview_url",
            "brickognize_source_view",
            "bin_id",
            "distribution_reason",
            "feeding_started_at",
            "carousel_detected_confirmed_at",
            "first_carousel_seen_ts",
            "first_carousel_seen_angle_deg",
            "classification_channel_size_class",
            "classification_channel_zone_state",
            "classification_channel_zone_center_deg",
            "classification_channel_exit_deg",
            "classification_channel_zone_half_width_deg",
            "classification_channel_soft_guard_deg",
            "classification_channel_hard_guard_deg",
            "carousel_motion_sync_ratio",
            "carousel_motion_sync_ratio_avg",
            "carousel_motion_sync_ratio_min",
            "carousel_motion_sync_ratio_max",
            "carousel_motion_piece_speed_deg_per_s",
            "carousel_motion_platter_speed_deg_per_s",
            "carousel_motion_sample_count",
            "carousel_motion_under_sync_sample_count",
            "carousel_motion_over_sync_sample_count",
            "carousel_rotate_started_at",
            "carousel_rotated_at",
            "carousel_snapping_started_at",
            "carousel_snapping_completed_at",
            "carousel_next_baseline_captured_at",
            "carousel_next_ready_at",
            "classified_at",
            "distributing_at",
            "distribution_target_selected_at",
            "distribution_motion_started_at",
            "distribution_positioned_at",
            "distributed_at",
        ):
            _maybe(key)

        # destination_bin may arrive as list from JSON — coerce to tuple.
        if "destination_bin" in payload:
            raw_bin = payload["destination_bin"]
            if isinstance(raw_bin, (list, tuple)) and len(raw_bin) == 3:
                try:
                    kwargs["destination_bin"] = (
                        int(raw_bin[0]),
                        int(raw_bin[1]),
                        int(raw_bin[2]),
                    )
                except (TypeError, ValueError):
                    pass
            elif raw_bin is None:
                kwargs["destination_bin"] = None

        # recognition_used_crop_ts — list of floats.
        raw_used = payload.get("recognition_used_crop_ts")
        if isinstance(raw_used, list):
            coerced_used: list[float] = []
            for item in raw_used:
                if isinstance(item, (int, float)):
                    coerced_used.append(float(item))
            kwargs["recognition_used_crop_ts"] = coerced_used

        # stage / classification_status — string -> enum.
        stage_raw = payload.get("stage")
        if isinstance(stage_raw, PieceStage):
            kwargs["stage"] = stage_raw
        elif isinstance(stage_raw, str):
            try:
                kwargs["stage"] = PieceStage(stage_raw)
            except ValueError:
                pass

        status_raw = payload.get("classification_status")
        if isinstance(status_raw, ClassificationStatus):
            kwargs["classification_status"] = status_raw
        elif isinstance(status_raw, str):
            try:
                kwargs["classification_status"] = ClassificationStatus(status_raw)
            except ValueError:
                pass

        # carousel_motion_samples — list of dicts or instances.
        raw_samples = payload.get("carousel_motion_samples")
        if isinstance(raw_samples, list):
            coerced_samples: list[CarouselMotionSample] = []
            for sample in raw_samples:
                if isinstance(sample, CarouselMotionSample):
                    coerced_samples.append(sample)
                    continue
                if not isinstance(sample, dict):
                    continue
                try:
                    coerced_samples.append(
                        CarouselMotionSample(
                            observed_at=float(sample.get("observed_at", 0.0)),
                            piece_angle_deg=float(sample.get("piece_angle_deg", 0.0)),
                            carousel_angle_deg=float(sample.get("carousel_angle_deg", 0.0)),
                            piece_speed_deg_per_s=float(
                                sample.get("piece_speed_deg_per_s", 0.0)
                            ),
                            carousel_speed_deg_per_s=float(
                                sample.get("carousel_speed_deg_per_s", 0.0)
                            ),
                            sync_ratio=float(sample.get("sync_ratio", 0.0)),
                        )
                    )
                except (TypeError, ValueError):
                    continue
            kwargs["carousel_motion_samples"] = coerced_samples

        return cls(**kwargs)
