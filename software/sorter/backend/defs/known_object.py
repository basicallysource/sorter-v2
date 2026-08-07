from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
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
    # The identification request itself failed (Brickognize timeout / DNS /
    # connection error) — distinct from not_found (service answered, no match)
    # and unknown (local pipeline never produced a result to send).
    failed = "failed"


class ClassificationAttemptStrategy(str, Enum):
    # Which parallel request produced the applied result. All requests for a
    # piece are submitted at once (redundant, NOT sequential retries); the
    # highest-confidence one wins and its label is recorded here.
    # The full set of used C4 burst frames.
    combined = "combined"
    # Only the last (most-settled) C4 burst frame, sent alone.
    single_burst = "single_burst"
    # Add a new parallel variant by adding the enum value here and a request in
    # _buildClassifyRequests; the rest of the plumbing is strategy-agnostic.


@dataclass
class RecognitionImage:
    # One image gathered for recognizing a piece. ``source`` is "c4_burst" for a
    # classification-channel capture. ``used`` is True only when this exact image
    # was actually submitted to Brickognize in the request whose result was applied.
    # ``excluded_from_result`` is True when this image WAS submitted in a parallel
    # request that lost (a different request scored higher) and was thus thrown
    # out — distinct from ``used=False`` (kept for review, never sent).
    image: str
    source: str
    used: bool = False
    ts: Optional[float] = None
    score: Optional[float] = None
    excluded_from_result: bool = False
    # Motion-blur / focus measure of this image: the variance of its Laplacian
    # (higher = sharper, lower = blurrier). Computed for C4 burst crops at capture
    # time so anything downstream can judge the image's validity without redecoding
    # the JPEG. None when not measured (older records).
    sharpness: Optional[float] = None
    # Physical channel the image came from: 4 for a C4 burst capture. None when
    # unknown (older records).
    channel: Optional[int] = None
    # Wall-clock capture time of this image (epoch seconds) — the frame timestamp.
    # The UI ages each pic against the owning KnownObject.created_at. None for
    # older records.
    created_at: Optional[float] = None


@dataclass
class ClassificationAttempt:
    # One Brickognize call for a piece. A piece fans out several of these in
    # parallel (combined, single_burst); they are redundant, not retries. The
    # ``applied`` one is the highest-confidence call that recognized the piece.
    strategy: "ClassificationAttemptStrategy"
    n_burst: int
    found: bool
    # Human-facing name of the parallel request; equals the strategy value
    # (combined / single_burst).
    label: Optional[str] = None
    # True for the one attempt whose result was applied to the piece (the
    # highest-confidence found attempt, or the first call when nothing was found).
    applied: bool = False
    part_id: Optional[str] = None
    # Brickognize's human name for the top item and its reference (stock) image
    # URL, so the UI can show what this request thought it saw without re-querying.
    part_name: Optional[str] = None
    preview_url: Optional[str] = None
    confidence: Optional[float] = None
    # Top color this request returned (Brickognize reports colors per request).
    color_id: Optional[str] = None
    color_name: Optional[str] = None
    error: Optional[str] = None
    duration_s: Optional[float] = None
    # Capture timestamps of the exact images submitted in this request. The UI
    # resolves these against the recognition image set to show which crops went
    # into each parallel call when a request row is expanded.
    image_ts: List[float] = field(default_factory=list)
    # Brickognize's per-request search id, needed to submit a correction for this
    # request's result (the feedback API keys on it). None on error/older records.
    listing_id: Optional[str] = None
    # Zero-based rank of this request's top item/color in Brickognize's original
    # response (the item_rank/color_rank the feedback API expects). ``item_type``
    # is Brickognize's type for the top item ("part"/"set"/"fig"/"sticker").
    item_rank: Optional[int] = None
    item_type: Optional[str] = None
    color_rank: Optional[int] = None


@dataclass
class KnownObject:
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    stage: PieceStage = PieceStage.created
    classification_status: ClassificationStatus = ClassificationStatus.pending
    # Set when the Brickognize request itself failed (timeout / DNS / connection
    # error on a flaky network) rather than succeeding with no match. The piece
    # still routes as ``unknown`` (no part_id -> misc); this only changes the UI
    # card label to "Request failed" so a network blip isn't read as a bad piece.
    request_failed: bool = False
    # Set when a piece's classification cycle was torn down before it ever
    # produced a result (machine stop / reset mid-capture). The object was
    # already emitted to the UI with a crop but will never be classified or
    # distributed; the UI drops aborted pieces rather than leaving them stuck
    # in the "capturing" phase forever.
    aborted: bool = False
    # Set by the broadcaster's stuck-piece reaper when a piece goes silent for
    # longer than STUCK_PIECE_TIMEOUT_S without reaching the distributed stage
    # while the machine is running (e.g. stuck "classified" but never
    # distributed). Like ``aborted`` but time-based rather than teardown-driven;
    # the UI drops dead pieces from the recent list. Self-clears if the piece
    # later progresses and re-emits.
    dead: bool = False
    part_id: Optional[str] = None
    part_name: Optional[str] = None
    part_category: Optional[str] = None
    color_id: str = "any_color"
    color_name: str = "Any Color"
    category_id: Optional[str] = None
    # Two independent scores, because color and mold can come from different
    # providers (see color_provider/mold_provider). ``confidence`` is the MOLD
    # score only — Brickognize's top-item score. ``color_confidence`` is the
    # applied color's own score: Brickognize's top-color score, or the hosted
    # color model's softmax probability when that provider answered. Never
    # collapse the two into one number; a 53% mold match says nothing about how
    # sure we are of the color.
    confidence: Optional[float] = None
    color_confidence: Optional[float] = None
    # Largest single physical dimension (bbox x/y/z) in mm, resolved from Hive
    # part metadata at classification time. None when unknown.
    max_dimension_mm: Optional[float] = None
    # Headline BrickLink "moving average" price (USD) for this part+color, resolved
    # at classification time from Hive (hive_metadata, served via the persistent
    # metadata cache). None when Hive is unreachable and the cache is cold, or the
    # part has no price. This is the only metadata field the Recent Pieces card
    # renders.
    moving_avg_price: Optional[float] = None
    # Full metadata blob from Hive (part info, BrickLink item, the four price
    # buckets, dimensions, etc.). Kept for the detail view; the card shows only
    # moving_avg_price. None when unavailable.
    piece_metadata: Optional[Dict[str, Any]] = None
    # Set by the distributor when the profile's high_value_routing override fired
    # for this piece (moving_avg_price cleared the threshold), so it was rerouted
    # into the high-value category's bin. Surfaced as a chip on the UI card.
    high_value_routed: bool = False
    # Live membership check against the active .bsx inventory, resolved at
    # classification time. None = no active inventory / undecidable; True = the
    # part+color is stocked; False = NOT in inventory (drives the badge and, when
    # the profile's inventory_routing is on, reroutes to the not-in-inventory bin).
    not_in_inventory: Optional[bool] = None
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
    # Correction-submission provenance, copied from the APPLIED Brickognize
    # request so a user correction can be sent back to Brickognize's feedback API
    # without re-querying. ``brickognize_listing_id`` is the applied request's
    # search id; ``brickognize_item_rank``/``brickognize_item_type`` describe the
    # applied top item's position/type in that response; ``brickognize_color_rank``
    # is the applied top color's position. Brickognize's feedback API only
    # accepts/rejects a specific ranked result, so these scalars are all a
    # part-or-color correction needs. None until a request is applied / on error.
    brickognize_listing_id: Optional[str] = None
    brickognize_item_rank: Optional[int] = None
    brickognize_item_type: Optional[str] = None
    brickognize_color_rank: Optional[int] = None
    # Which service actually produced the applied color / mold (see
    # classification.providers). These record what ANSWERED, not what was
    # configured: a hosted provider that times out leaves color_provider as
    # "brickognize", since that is whose color the piece was sorted on. None
    # until classification runs.
    color_provider: Optional[str] = None
    mold_provider: Optional[str] = None
    # Every image gathered for recognition — the C4 burst captures — each flagged
    # with whether it was actually submitted to Brickognize. The burst keeps all
    # its frames; only the entries with used=True drove the classification.
    recognition_image_set: List["RecognitionImage"] = field(default_factory=list)
    # Upstream C2/C3 crops the piece-link model scored as this same physical
    # piece. DELIBERATELY a separate list from recognition_image_set: that set
    # is ground truth ("these pixels ARE the piece", the C4 burst) and feeds
    # piece_images -> Hive -> training data. Link matches are model GUESSES and
    # must never travel that pipeline — they persist to their own table/files
    # and are never uploaded as piece images.
    link_match_image_set: List["RecognitionImage"] = field(default_factory=list)
    # Record of each parallel Brickognize request for this piece (combined plus
    # any single-image calls). They run concurrently, not as retries; the one
    # flagged applied=True is the highest-confidence call that recognized it.
    classification_attempts: List["ClassificationAttempt"] = field(default_factory=list)
    # Which parallel request produced the applied result. None until
    # classification runs. ``combined`` = the full burst set won;
    # ``single_burst`` = the lone-image call beat it.
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
