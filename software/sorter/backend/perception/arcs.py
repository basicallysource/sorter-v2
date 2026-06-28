"""Bbox → (in_drop, in_exit) attribution.

Pure functions. Called by ``InferenceWorker`` on each frame to convert
raw YOLO output into the boolean channel state the coordinator consumes.

The "section" math matches the legacy ``subsystems.feeder.analysis`` logic
(360 single-degree sections around the channel center). The legacy module
is not imported here — perception stands on its own — but the saved-arc
data format is shared, and the function below is regression-tested against
the legacy ``getBboxSections`` to confirm equivalence at the bbox level.
"""

from __future__ import annotations

from typing import Iterable, Tuple

import numpy as np

from .channel import ChannelDef, SECTION_COUNT, SECTION_DEG


Bbox = Tuple[int, int, int, int]


def bboxCenter(bbox: Bbox) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def mergeNearbyBboxes(
    bboxes: Iterable[Bbox], gap_px: float
) -> list[tuple[Bbox, list[Bbox]]]:
    """Collapse boxes that belong to ONE physical piece into a single box.

    The detector over-segments a single piece — drawing a separate box per
    colour region of a multi-coloured brick, or briefly splitting one piece into
    two — so several overlapping / adjacent boxes really describe one object.
    This clusters boxes that overlap OR sit within ``gap_px`` of each other
    (transitively, via union-find) and returns, per cluster, the union box plus
    its member boxes. ``gap_px <= 0`` merges only boxes that actually overlap.

    Returns ``[(merged_union_bbox, [member_bbox, ...]), ...]``. A lone box comes
    back as a single-member cluster (merged == itself). Order is not guaranteed.
    """
    boxes: list[Bbox] = [
        (int(b[0]), int(b[1]), int(b[2]), int(b[3])) for b in bboxes
    ]
    n = len(boxes)
    if n <= 1:
        return [(b, [b]) for b in boxes]

    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def near(a: Bbox, b: Bbox) -> bool:
        # True if the boxes overlap or come within gap_px on both axes (i.e. the
        # gap between them is < gap_px in x AND y — touching/overlapping corners
        # count). Axis-separated boxes never merge.
        return (
            a[0] - gap_px <= b[2]
            and b[0] - gap_px <= a[2]
            and a[1] - gap_px <= b[3]
            and b[1] - gap_px <= a[3]
        )

    for i in range(n):
        for j in range(i + 1, n):
            if near(boxes[i], boxes[j]):
                parent[find(i)] = find(j)

    clusters: dict[int, list[Bbox]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(boxes[i])

    out: list[tuple[Bbox, list[Bbox]]] = []
    for members in clusters.values():
        x1 = min(m[0] for m in members)
        y1 = min(m[1] for m in members)
        x2 = max(m[2] for m in members)
        y2 = max(m[3] for m in members)
        out.append(((x1, y1, x2, y2), members))
    return out


def bboxArea(bbox: Bbox) -> int:
    x1, y1, x2, y2 = bbox
    w = x2 - x1
    h = y2 - y1
    if w <= 0 or h <= 0:
        return 0
    return w * h


def bboxWithinAreaFraction(bbox: Bbox, mask_area_px: float, max_fraction: float) -> bool:
    """True if the bbox area is at or below ``max_fraction`` of the channel mask
    area. Drops implausibly massive detections (a hand, a shadow, the model
    latching onto the whole channel) before they reach the state machine.
    ``mask_area_px`` is precomputed once by the caller (the mask is immutable),
    so this stays cheap on the hot path."""
    if mask_area_px <= 0:
        return True
    return bboxArea(bbox) <= max_fraction * mask_area_px


def bboxWithinMaskExtent(
    bbox: Bbox,
    mask_w_extent: float,
    mask_h_extent: float,
    max_fraction: float,
) -> bool:
    """True if the bbox width AND height are each at or below ``max_fraction`` of
    the channel mask's bounding extent. Catches long, skinny detections that span
    most of the channel in one dimension (e.g. 80% of the width but only 20% of
    the height) — these stay under an area-fraction limit while still being
    implausibly large. Extents are precomputed once by the caller."""
    x1, y1, x2, y2 = bbox
    w = x2 - x1
    h = y2 - y1
    if mask_w_extent > 0 and w > max_fraction * mask_w_extent:
        return False
    if mask_h_extent > 0 and h > max_fraction * mask_h_extent:
        return False
    return True


def bboxInsideChannelMask(bbox: Bbox, channel: ChannelDef) -> bool:
    cx, cy = bboxCenter(bbox)
    h, w = channel.mask.shape[:2]
    ix, iy = int(cx), int(cy)
    if not (0 <= ix < w and 0 <= iy < h):
        return False
    return bool(channel.mask[iy, ix])


def bboxInsideMask(bbox: Bbox, mask: np.ndarray) -> bool:
    """Center-in-mask test against an arbitrary filled mask — the same membership
    rule as ``bboxInsideChannelMask`` but for a secondary-zone mask. Used to tag
    detections with the foreign zones they fall in (display/tag only)."""
    cx, cy = bboxCenter(bbox)
    h, w = mask.shape[:2]
    ix, iy = int(cx), int(cy)
    if not (0 <= ix < w and 0 <= iy < h):
        return False
    return bool(mask[iy, ix])


def bboxSections(bbox: Bbox, channel: ChannelDef) -> frozenset[int]:
    """Section ids touched by a small set of sample points on the bbox.

    Nine samples (corners + edge midpoints + center) — enough to catch a
    bbox that straddles a section boundary without paying for a per-pixel
    scan.
    """
    x1, y1, x2, y2 = bbox
    mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    points = (
        (x1, y1), (x2, y1), (x1, y2), (x2, y2),
        (mx, y1), (mx, y2), (x1, my), (x2, my),
        (mx, my),
    )
    cx0, cy0 = channel.center
    r1 = channel.radius1_angle_image
    sections: set[int] = set()
    for px, py in points:
        angle = float(np.degrees(np.arctan2(py - cy0, px - cx0)))
        relative = (angle - r1) % 360.0
        sections.add(int(relative / SECTION_DEG) % SECTION_COUNT)
    return frozenset(sections)


def attributeBbox(bbox: Bbox, channel: ChannelDef) -> tuple[bool, bool]:
    """Return ``(in_drop, in_exit)`` for a single bbox on this channel.

    A bbox is "on" the channel only if its center lies inside the saved
    polygon mask. Off-channel bboxes attribute to neither region (they
    were noise leaking outside the channel polygon).
    """
    if not bboxInsideChannelMask(bbox, channel):
        return False, False
    sections = bboxSections(bbox, channel)
    in_drop = bool(sections & channel.drop_sections)
    in_exit = bool(sections & channel.exit_sections)
    return in_drop, in_exit


def _orderedCircularSections(sections: frozenset[int]) -> list[int]:
    """Sections walked in forward order, starting after the largest gap, so the
    first entry is the rear (entry) edge and the last is the forward edge.
    Mirrors ``subsystems.feeder.analysis._orderedCircularSections`` but stays
    standalone — perception does not import the legacy stack."""
    if not sections:
        return []
    normalized = sorted(int(s) % SECTION_COUNT for s in sections)
    if len(normalized) <= 1 or len(normalized) >= SECTION_COUNT:
        return normalized
    largest_gap_index = 0
    largest_gap = -1
    for index, section in enumerate(normalized):
        next_section = normalized[(index + 1) % len(normalized)]
        gap = (next_section - section) % SECTION_COUNT
        if gap > largest_gap:
            largest_gap = gap
            largest_gap_index = index
    start = normalized[(largest_gap_index + 1) % len(normalized)]
    return sorted(normalized, key=lambda s: (s - start) % SECTION_COUNT)


def exitNearEdgeSection(channel: ChannelDef) -> int | None:
    ordered = _orderedCircularSections(channel.exit_sections)
    return ordered[0] if ordered else None


def forwardClearanceToExitDeg(
    bboxes: Iterable[Bbox], channel: ChannelDef
) -> float | None:
    """Smallest forward distance (output degrees) from any on-channel piece to
    the near edge of the exit zone, i.e. how far the rotor can advance before
    the most-forward piece enters the exit zone. ``None`` when no piece is on
    the channel or the channel has no exit arc.

    Forward is the increasing-relative-angle direction (same convention as the
    section math and the forward motor sign). With 1°-wide sections the
    section-index delta is already the angle in degrees.
    """
    near = exitNearEdgeSection(channel)
    if near is None:
        return None
    best: int | None = None
    for bbox in bboxes:
        if not bboxInsideChannelMask(bbox, channel):
            continue
        for section in bboxSections(bbox, channel):
            dist = (near - section) % SECTION_COUNT
            if best is None or dist < best:
                best = dist
    if best is None:
        return None
    return float(best) * SECTION_DEG


def exitOnlySections(channel: ChannelDef) -> frozenset[int]:
    """The REAL exit (fall-off) region: the exit arc with the precise arc removed.

    ``ChannelDef.exit_sections`` is the union of the exit and precise arcs (what
    the cascade reads as ``in_exit``). But the precise zone is a separate,
    independently-drawn arc the piece passes through BEFORE the fall-off region.
    The eject must act on the fall-off region only, so it works against this set.
    Falls back to the full ``exit_sections`` when no separate exit arc was drawn
    (i.e. exit == precise), so a single-arc channel still has a target.
    """
    exit_only = channel.exit_sections - channel.precise_sections
    return exit_only if exit_only else channel.exit_sections


def exitComForwardDeg(
    bboxes: Iterable[Bbox], channel: ChannelDef
) -> float | None:
    """Signed forward distance (output/channel degrees) from the LEADING
    on-channel piece's bbox center-of-mass to the entry (near) edge of the REAL
    exit region (``exitOnlySections`` — exit arc minus precise arc).

    > 0  : the COM is still this many channel-degrees SHORT of the exit zone —
           advance the rotor forward this much to bring the COM onto the edge.
    <= 0 : the COM has crossed the exit-zone entry edge. Because the COM is the
           bbox centroid, crossing the edge means the piece is >= 50% inside the
           exit region. Magnitude = degrees past the entry edge.

    The "leading" piece is the one with the smallest such value — either the
    piece closest to the exit from behind, or the piece furthest into the exit.
    ``None`` when there is no on-channel piece or the channel has no exit arc.

    Sign convention / branch cut (this is the subtle part): the forward distance
    behind the entry edge is ``(near - relative) % 360`` in ``[0, 360)``. A piece
    on the FAR/rear arc of the channel therefore reads as a large POSITIVE value
    (e.g. ~200°), NOT a negative one — it must never be mistaken for "already at
    the exit." Only a piece whose COM section actually lands inside the exit-only
    region is folded to a small negative (its degrees past the entry edge). The
    branch cut thus sits at the exit-only zone, not at ±180° from the edge.

    Cheap — one ``arctan2`` per bbox center (no grid sampling), so it is safe to
    compute every frame on the inference worker thread alongside the existing
    attribution.
    """
    best = _leadingExitApproach(bboxes, channel)
    return None if best is None else best[0]


def _leadingExitApproach(
    bboxes: Iterable[Bbox], channel: ChannelDef
) -> tuple[float, int] | None:
    """``(travel_gap_deg, com_section)`` for the LEADING on-channel piece — the
    one with the smallest gap to the exit-only entry edge measured along the
    channel's travel direction. ``None`` when there is no on-channel piece or the
    channel has no exit arc. Shared by ``exitComForwardDeg`` and
    ``comInPreciseZone`` so they agree on which piece is 'leading'.

    The gap is always returned with the SAME sign semantics regardless of travel
    direction (> 0 = advance toward the exit this many degrees; <= 0 = the COM is
    already past the entry edge). Only the physical move direction differs.

    Direction (``channel.reverse``):
    - forward (default): the piece moves in increasing relative angle, so it
      enters the exit-only arc at the NEAR edge (``ordered[0]``); the gap is
      ``(near - relative) % 360``.
    - reverse (C4 carousel): the piece moves in decreasing relative angle, so it
      enters the exit-only arc at the FAR edge (``ordered[-1]``); the gap is
      ``(relative - far) % 360``.
    In both cases a COM genuinely inside the exit-only arc folds to a small
    negative value; the ``> 180`` guard keeps a COM exactly on the entry edge at
    0 rather than folding it to -360.
    """
    exit_only = exitOnlySections(channel)
    ordered = _orderedCircularSections(exit_only)
    if not ordered:
        return None
    reverse = bool(getattr(channel, "reverse", False))
    entry = ordered[-1] if reverse else ordered[0]
    entry_angle = float(entry) * SECTION_DEG
    cx0, cy0 = channel.center
    r1 = channel.radius1_angle_image
    best: tuple[float, int] | None = None
    for bbox in bboxes:
        if not bboxInsideChannelMask(bbox, channel):
            continue
        mx, my = bboxCenter(bbox)
        angle = float(np.degrees(np.arctan2(my - cy0, mx - cx0)))
        relative = (angle - r1) % 360.0
        sec = int(relative / SECTION_DEG) % SECTION_COUNT
        # Degrees the COM sits BEHIND the entry edge along the travel direction,
        # in [0, 360).
        if reverse:
            gap = (relative - entry_angle) % 360.0
        else:
            gap = (entry_angle - relative) % 360.0
        if sec in exit_only and gap > 180.0:
            gap -= 360.0
        if best is None or gap < best[0]:
            best = (gap, sec)
    return best


def _arcEntryRelativeDeg(sections: frozenset[int], reverse: bool) -> float | None:
    """Relative angle (output degrees) of the arc's ENTRY edge in the travel
    direction — the edge the piece reaches FIRST. Reverse travel enters at the
    high-relative edge (``ordered[-1]``); forward at the low-relative edge
    (``ordered[0]``). ``None`` for an empty arc."""
    ordered = _orderedCircularSections(sections)
    if not ordered:
        return None
    entry = ordered[-1] if reverse else ordered[0]
    return float(entry) * SECTION_DEG


def comForwardToPreciseEntryDeg(
    bboxes: Iterable[Bbox], channel: ChannelDef
) -> float | None:
    """Signed travel-direction distance (output degrees) from the LEADING
    on-channel piece's COM to the BEGINNING (entry edge) of the PRECISE (staging)
    arc — the edge the piece reaches first. The C4 reverse flow drives this toward
    0 in MOVING_TO_PRECISE so the piece parks at the START of the precise band,
    not its centre (which overshot), while classification runs.

    Same leading-piece selection and sign convention as ``exitComForwardToCenterDeg``
    (> 0 = advance toward the precise entry; <= 0 = at/past it). ``None`` when there
    is no on-channel piece or the channel has no precise arc."""
    best = _leadingExitApproach(bboxes, channel)
    reverse = bool(getattr(channel, "reverse", False))
    entry_rel = _arcEntryRelativeDeg(channel.precise_sections, reverse)
    if best is None or entry_rel is None:
        return None
    com_rel = float(best[1]) * SECTION_DEG
    if reverse:
        gap = (com_rel - entry_rel) % 360.0
    else:
        gap = (entry_rel - com_rel) % 360.0
    if gap > 180.0:
        gap -= 360.0
    return gap


def comInPreciseZone(bboxes: Iterable[Bbox], channel: ChannelDef) -> bool:
    """True when the LEADING piece's center-of-mass section lies in the precise
    zone — the exact trigger for starting a C3 eject. The precise zone is the
    staging band the piece passes through right before the exit; the eject must
    only START once the piece's COM is actually in it, not on a distance
    heuristic that can fire while the piece is still short of it."""
    best = _leadingExitApproach(bboxes, channel)
    if best is None:
        return False
    return best[1] in channel.precise_sections


def exitOnlyCenterOffsetDeg(channel: ChannelDef) -> float | None:
    """Forward distance (output degrees) from the exit-only entry (near) edge to
    the CENTER of the exit-only (fall-off) arc. Static per-channel geometry;
    ``None`` when the channel has no exit-only arc."""
    ordered = _orderedCircularSections(exitOnlySections(channel))
    if not ordered:
        return None
    return float(len(ordered) // 2) * SECTION_DEG


def exitComForwardToCenterDeg(
    bboxes: Iterable[Bbox], channel: ChannelDef
) -> float | None:
    """Signed forward distance (output degrees) from the LEADING on-channel
    piece's COM to the CENTER of the REAL exit (fall-off) region — the exit arc
    MINUS the precise arc. Same leading-piece selection and sign convention as
    ``exitComForwardDeg`` (which targets the near edge); this just shifts the
    target forward to the arc midpoint so a closed-loop discharge can park the
    piece in the middle of the fall-off zone instead of on its leading lip.

    > 0 : COM is short of the center — advance forward this much.
    <= 0: COM is at/past the center.
    ``None`` when there is no on-channel piece or the channel has no exit arc."""
    best = _leadingExitApproach(bboxes, channel)
    center_offset = exitOnlyCenterOffsetDeg(channel)
    if best is None or center_offset is None:
        return None
    return best[0] + center_offset


_AREA_GRID_N = 12  # 12x12 = 144 sample points per bbox; ample for area majority

# Per-channel cached region lookup: section_id → 0=none 1=drop 2=exit_only 3=precise.
# Keyed by channel_id; built once on first call and reused. The section sets are
# immutable after ChannelDef construction so this never goes stale.
_region_lookup_cache: dict[int, np.ndarray] = {}


def _region_lookup(channel: ChannelDef) -> np.ndarray:
    cached = _region_lookup_cache.get(channel.channel_id)
    if cached is not None:
        return cached
    exit_only = channel.exit_sections - channel.precise_sections
    lut = np.zeros(SECTION_COUNT, dtype=np.int8)
    for s in channel.drop_sections:
        lut[int(s) % SECTION_COUNT] = 1
    for s in exit_only:
        lut[int(s) % SECTION_COUNT] = 2
    for s in channel.precise_sections:
        lut[int(s) % SECTION_COUNT] = 3
    _region_lookup_cache[channel.channel_id] = lut
    return lut


def _bboxRegionCounts(
    bbox: Bbox, channel: ChannelDef
) -> tuple[int, int, int, int]:
    """``(n_drop, n_exit_only, n_precise, n_on_channel)`` — count of grid sample
    points whose section falls in each region. Samples a uniform NxN grid
    across the bbox AREA (not just its boundary) so counts reflect true area
    overlap. Off-channel-mask points are skipped. Fully vectorized via numpy:
    ~0.1 ms per call vs ~10 ms for the old Python for-loop.
    """
    x1, y1, x2, y2 = bbox
    cx0, cy0 = channel.center
    r1 = channel.radius1_angle_image
    h, w = channel.mask.shape[:2]

    dx = (x2 - x1) / float(_AREA_GRID_N)
    dy = (y2 - y1) / float(_AREA_GRID_N)
    xs = x1 + (np.arange(_AREA_GRID_N, dtype=np.float64) + 0.5) * dx
    ys = y1 + (np.arange(_AREA_GRID_N, dtype=np.float64) + 0.5) * dy
    xx, yy = np.meshgrid(xs, ys)  # (N, N)

    ix = xx.astype(np.int32)
    iy = yy.astype(np.int32)
    in_bounds = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
    ix_safe = np.clip(ix, 0, w - 1)
    iy_safe = np.clip(iy, 0, h - 1)
    on_mask = in_bounds & (channel.mask[iy_safe, ix_safe] > 0)

    n_on_channel = int(on_mask.sum())
    if n_on_channel == 0:
        return 0, 0, 0, 0

    angles = np.degrees(np.arctan2(yy - cy0, xx - cx0))
    relative = (angles - r1) % 360.0
    sec = (relative / SECTION_DEG).astype(np.int32) % SECTION_COUNT

    codes = _region_lookup(channel)[sec[on_mask]]
    n_drop = int((codes == 1).sum())
    n_exit_only = int((codes == 2).sum())
    n_precise = int((codes == 3).sum())
    return n_drop, n_exit_only, n_precise, n_on_channel


def orderedPieceObservations(
    bboxes: Iterable[Bbox], channel: ChannelDef
) -> list[tuple[float, int, int, Bbox]]:
    """Per-piece ``(com_forward_to_exit_deg, com_section, region_code, bbox)`` for EVERY
    on-channel piece, ordered leading-first (ascending gap to the exit-only entry
    edge). Uses the identical gap math and sign convention as
    ``_leadingExitApproach`` — whose single result is exactly this list's head —
    so the leading piece agrees across both. ``region_code`` is the
    ``_region_lookup`` code at the COM section (0 none, 1 drop, 2 exit_only,
    3 precise). ``[]`` when the channel has no exit arc (no travel reference) or
    no on-channel piece.

    The scalar ``exit_com_*`` helpers collapse the channel to its single leading
    piece; this exposes the whole channel so a multi-piece holding flow can tell
    leading from trailing and ask which named zone each piece's centre sits in,
    without any cross-frame tracking.
    """
    exit_only = exitOnlySections(channel)
    ordered = _orderedCircularSections(exit_only)
    if not ordered:
        return []
    reverse = bool(getattr(channel, "reverse", False))
    entry = ordered[-1] if reverse else ordered[0]
    entry_angle = float(entry) * SECTION_DEG
    cx0, cy0 = channel.center
    r1 = channel.radius1_angle_image
    lut = _region_lookup(channel)
    out: list[tuple[float, int, int, Bbox]] = []
    for bbox in bboxes:
        if not bboxInsideChannelMask(bbox, channel):
            continue
        mx, my = bboxCenter(bbox)
        angle = float(np.degrees(np.arctan2(my - cy0, mx - cx0)))
        relative = (angle - r1) % 360.0
        sec = int(relative / SECTION_DEG) % SECTION_COUNT
        if reverse:
            gap = (relative - entry_angle) % 360.0
        else:
            gap = (entry_angle - relative) % 360.0
        if sec in exit_only and gap > 180.0:
            gap -= 360.0
        out.append((gap, sec, int(lut[sec]), (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))))
    out.sort(key=lambda t: t[0])
    return out


def holdingSlotSections(
    channel: ChannelDef, count: int
) -> list[frozenset[int]]:
    """Subdivide the drawn precise (holding) band into ``count`` contiguous
    holding slots, ordered ENTRY-FIRST in the travel direction: slot 0 is the
    edge a piece reaches FIRST coming from the drop zone; the last slot is the
    edge adjacent to the fall-off (the piece's final hold before discharge).

    ``count == 1`` returns the whole precise band as one slot — exactly today's
    single holding region. ``count`` is clamped to ``[1, len(band sections)]`` so
    a slot is never empty (an empty section-set could never read as occupied and
    would wedge the scheduler); callers should treat ``len(result)`` as the
    effective slot count rather than assuming their requested ``count``. Returns
    ``[]`` when the channel has no precise band.

    The UI exposes ONE draggable precise/holding band (width + position); this is
    where ``Rev01Config.holding_region_count`` turns that single band into N
    slots, so adding holding regions needs no UI change.
    """
    ordered = _orderedCircularSections(channel.precise_sections)
    if not ordered:
        return []
    # Entry-first: the edge the piece reaches first. _orderedCircularSections
    # returns rear-edge-first (forward-travel entry); reverse travel (C4) enters
    # at the far edge, so flip to keep slot 0 == entry in both directions.
    if bool(getattr(channel, "reverse", False)):
        ordered = list(reversed(ordered))
    n = len(ordered)
    count = max(1, min(int(count), n))
    base, rem = divmod(n, count)
    slots: list[frozenset[int]] = []
    i = 0
    for s in range(count):
        size = base + (1 if s < rem else 0)
        slots.append(frozenset(ordered[i : i + size]))
        i += size
    return slots


def attributeBboxes(
    bboxes: Iterable[Bbox], channel: ChannelDef
) -> tuple[bool, bool, bool, bool, int, list[tuple[int, int, int, int, Bbox]]]:
    """Aggregate over multiple bboxes. Returns
    ``(any_in_drop, any_in_exit, any_in_precise, any_exit_majority,
       n_on_channel, per_bbox_counts)``.

    - ``any_in_exit`` keeps the union semantics (exit + precise arcs).
    - ``any_in_precise`` is precise-arc-only.
    - ``any_exit_majority`` is True when at least one on-channel bbox has
      strictly more grid-area points in the exit-only sub-arc than in the
      precise arc. Trigger for jitter unstick.
    - ``per_bbox_counts`` is a list of
      ``(n_drop, n_exit_only, n_precise, n_in_mask, bbox)`` tuples for each
      on-channel bbox, for diagnostics/logging. Only on-channel bboxes are
      included.
    """
    any_drop = False
    any_exit = False
    any_precise = False
    any_exit_majority = False
    n_on_channel = 0
    per_bbox_counts: list[tuple[int, int, int, int, Bbox]] = []
    for bbox in bboxes:
        if not bboxInsideChannelMask(bbox, channel):
            continue
        n_on_channel += 1
        sections = bboxSections(bbox, channel)
        if not any_drop and sections & channel.drop_sections:
            any_drop = True
        if not any_exit and sections & channel.exit_sections:
            any_exit = True
        if not any_precise and sections & channel.precise_sections:
            any_precise = True
        nd, ne, np_, nm = _bboxRegionCounts(bbox, channel)
        per_bbox_counts.append((nd, ne, np_, nm, bbox))
        if not any_exit_majority and ne > np_ and ne > 0:
            any_exit_majority = True
    return any_drop, any_exit, any_precise, any_exit_majority, n_on_channel, per_bbox_counts
