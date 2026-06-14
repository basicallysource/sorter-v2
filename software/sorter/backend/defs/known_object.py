from dataclasses import dataclass, field
from typing import List, Optional, Tuple
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


class ClassificationAttemptStrategy(str, Enum):
    # The full set we'd normally send: the used C4 burst frames plus any upstream
    # (C2/C3) match crops the embedding search injected.
    initial = "initial"
    # Re-send only the C4 burst, with the upstream match crops removed — the
    # first retry when ``initial`` recognized nothing and upstream was injected.
    drop_upstream = "drop_upstream"
    # Fan-out: submit the last burst frame and the single top-similarity upstream
    # crop as two parallel single-image queries, then keep the higher-confidence
    # result of whichever come back.
    split_singles = "split_singles"
    # Reserved for upcoming subset experiments (drop the burst, add more upstream
    # or more burst frames, …). Add the enum value here and a builder in the
    # classify retry runner; the rest of the plumbing is strategy-agnostic.


@dataclass
class RecognitionImage:
    # One image gathered for recognizing a piece. ``source`` is "c4_burst" for a
    # classification-channel capture or "upstream" for a C2/C3 match crop fused
    # in by the embedding search. ``used`` is True only when this exact image was
    # actually submitted to Brickognize in the attempt whose result was applied.
    # ``excluded_from_result`` is True when this image WAS submitted in an earlier
    # attempt that recognized nothing and was then deliberately removed for the
    # retry that won — distinct from ``used=False`` (kept for review, never sent).
    image: str
    source: str
    used: bool = False
    ts: Optional[float] = None
    score: Optional[float] = None
    excluded_from_result: bool = False
    # Physical channel the image came from: 4 for a C4 burst capture, 2 or 3 for
    # an upstream match crop. None when unknown (older records).
    channel: Optional[int] = None


@dataclass
class ClassificationAttempt:
    # One Brickognize call for a piece. More than one of these on a KnownObject
    # means an earlier attempt recognized nothing and a retry strategy (e.g.
    # dropping the upstream crops) was applied. The last entry is the attempt
    # whose result was applied to the piece.
    strategy: "ClassificationAttemptStrategy"
    n_burst: int
    n_upstream: int
    found: bool
    # Distinguishes the parallel sub-calls of a fan-out strategy (e.g.
    # "last_burst" vs "top_upstream" under split_singles). For single-call
    # strategies this equals the strategy name.
    label: Optional[str] = None
    # True for the one attempt whose result was applied to the piece (the
    # highest-confidence found attempt, or attempt 0 when nothing was found).
    applied: bool = False
    part_id: Optional[str] = None
    confidence: Optional[float] = None
    error: Optional[str] = None
    duration_s: Optional[float] = None


@dataclass
class KnownObject:
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    stage: PieceStage = PieceStage.created
    classification_status: ClassificationStatus = ClassificationStatus.pending
    # Set when a piece's classification cycle was torn down before it ever
    # produced a result (machine stop / reset mid-capture). The object was
    # already emitted to the UI with a crop but will never be classified or
    # distributed; the UI drops aborted pieces rather than leaving them stuck
    # in the "capturing" phase forever.
    aborted: bool = False
    part_id: Optional[str] = None
    part_name: Optional[str] = None
    part_category: Optional[str] = None
    color_id: str = "any_color"
    color_name: str = "Any Color"
    category_id: Optional[str] = None
    confidence: Optional[float] = None
    # Largest single physical dimension (bbox x/y/z) in mm, resolved from Hive
    # part metadata at classification time. None when unknown.
    max_dimension_mm: Optional[float] = None
    # Set when the piece exceeds the global oversize limit: sent down the
    # center of the chute to the misc bottom bin instead of a real bin.
    too_big: bool = False
    # Set when the piece fit no real bin because it was larger than its
    # intended layer's max-dimension limit, so it was rerouted to misc.
    too_big_for_layer: bool = False
    # The layer this piece would have been distributed to before being
    # rejected for size (when too_big_for_layer is set).
    intended_layer_index: Optional[int] = None
    destination_bin: Optional[Tuple[int, int, int]] = None
    thumbnail: Optional[str] = None
    latest_captured_crop: Optional[str] = None
    latest_captured_crop_ts: Optional[float] = None
    top_image: Optional[str] = None
    bottom_image: Optional[str] = None
    # Full classification chamber (carousel) frame captured at the instant
    # this piece was locked for drop — base64 JPEG, max 1024 px wide so the
    # event payload stays bounded. Used on the detail page to visually verify
    # the classification against the Brickognize reference image.
    drop_snapshot: Optional[str] = None
    brickognize_preview_url: Optional[str] = None
    brickognize_source_view: Optional[str] = None
    # Every image gathered for recognition — C4 burst captures plus any upstream
    # (C2/C3) match crops fused in by the embedding search — each flagged with
    # whether it was actually submitted to Brickognize. The burst keeps all its
    # frames; only the entries with used=True drove the classification.
    recognition_image_set: List["RecognitionImage"] = field(default_factory=list)
    # Ordered record of each Brickognize attempt for this piece. Length > 1 means
    # the first attempt(s) recognized nothing and a retry with a reduced image
    # set was made; the last entry is the one whose result was applied.
    classification_attempts: List["ClassificationAttempt"] = field(default_factory=list)
    # Strategy of the attempt whose result was applied (the last attempt's
    # strategy). None until classification runs. ``initial`` = first try won;
    # anything else = a retry was needed.
    classification_strategy: Optional["ClassificationAttemptStrategy"] = None
    # Captured timestamps of the crops actually shipped to Brickognize for
    # classification (subset of the tracker's sector snapshots). The frontend
    # uses these to highlight which crops participated in the final call.
    recognition_used_crop_ts: List[float] = field(default_factory=list)
    tracked_global_id: Optional[int] = None
    classification_channel_size_class: Optional[str] = None
    classification_channel_zone_state: Optional[str] = None
    classification_channel_zone_center_deg: Optional[float] = None
    classification_channel_zone_half_width_deg: Optional[float] = None
    classification_channel_exit_offset_deg: Optional[float] = None
    classification_channel_soft_guard_deg: Optional[float] = None
    classification_channel_hard_guard_deg: Optional[float] = None
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
