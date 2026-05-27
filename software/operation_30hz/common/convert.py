"""Per-role detection→ChannelDetection conversion.

Faithful to the live `_channelDetectionsFromDynamicResult` shape:
  1. Look up channel info (dict get).
  2. Filter the detection's bboxes through a polygon contains-point test
     (mirrors `_filterFeederDetectionResultToChannel`).
  3. List-comp the surviving bboxes into ChannelDetection objects.

The polygon and bbox counts are sized to match what the live system processes
per call. The work here is *pure Python*, which is the property that makes
the live code GIL-starved when other threads hold the GIL doing inference."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple


@dataclass(frozen=True)
class ChannelInfo:
    channel_id: int
    role: str
    polygon: Tuple[Tuple[float, float], ...]


@dataclass(frozen=True)
class ChannelDetection:
    bbox: Tuple[int, int, int, int]
    channel_id: int
    channel: ChannelInfo


# Per-role rectangle-ish "channel polygon". 6 vertices — the live polygons
# are 4-8 vertices. Used in the contains-point filter.
_CHANNELS: dict[str, ChannelInfo] = {
    "c_channel_2": ChannelInfo(
        channel_id=2, role="c_channel_2",
        polygon=((100.0, 50.0), (540.0, 50.0), (560.0, 200.0),
                 (540.0, 430.0), (100.0, 430.0), (80.0, 200.0)),
    ),
    "c_channel_3": ChannelInfo(
        channel_id=3, role="c_channel_3",
        polygon=((110.0, 60.0), (530.0, 60.0), (550.0, 210.0),
                 (530.0, 420.0), (110.0, 420.0), (90.0, 210.0)),
    ),
    "carousel": ChannelInfo(
        channel_id=4, role="carousel",
        polygon=((90.0, 40.0), (550.0, 40.0), (570.0, 240.0),
                 (550.0, 440.0), (90.0, 440.0), (70.0, 240.0)),
    ),
}


def _point_in_polygon(x: float, y: float, poly: Sequence[Tuple[float, float]]) -> bool:
    # Standard ray-cast point-in-polygon. ~6 vertices = small but non-trivial
    # pure-Python work per call.
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def channel_detections_from_result(
    role: str, bboxes: Sequence[Sequence[float]]
) -> List[ChannelDetection]:
    """Convert raw detector bboxes into ChannelDetection objects for `role`.

    Mirrors the live function: polygon filter per bbox, then list comp.
    Returns empty list if role is unknown or bboxes is empty.
    """
    channel = _CHANNELS.get(role)
    if channel is None or not bboxes:
        return []
    poly = channel.polygon
    out: List[ChannelDetection] = []
    for bbox in bboxes:
        # bbox is (x1, y1, x2, y2). Test center point against the polygon.
        cx = (float(bbox[0]) + float(bbox[2])) / 2.0
        cy = (float(bbox[1]) + float(bbox[3])) / 2.0
        if not _point_in_polygon(cx, cy, poly):
            continue
        out.append(ChannelDetection(
            bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
            channel_id=channel.channel_id,
            channel=channel,
        ))
    return out


# Live YOLO at the conf thresholds we use returns 30-60 raw candidates per
# 320 crop. Default to 50 — middle of the real range.
def synthetic_bboxes(count: int = 50) -> List[Tuple[int, int, int, int]]:
    return [
        (i * 30, (i * 17) % 400 + 20, i * 30 + 80, (i * 17) % 400 + 100)
        for i in range(count)
    ]


def full_filter_pipeline(role: str, bboxes: Sequence[Sequence[float]]) -> List[ChannelDetection]:
    """The multi-stage filter pipeline the live code runs per role per call.

    Live dispatcher tree: raw detector output -> NMS-ish dedupe ->
    score-threshold filter -> ignored-region polygon filter -> channel-region
    polygon filter -> ChannelDetection list comp. The work is the same shape
    here: multiple Python passes over the bbox list, each doing a contains-
    point test or similar O(n) per-bbox work.
    """
    # Pass 1: score filter (drop low-conf; live uses a per-role threshold).
    stage1 = [b for b in bboxes if (b[2] - b[0]) * (b[3] - b[1]) > 100]
    # Pass 2: ignored-region filter (a separate polygon — live IgnoredRegionOverlay).
    ignored = ((0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 50.0))
    stage2 = []
    for b in stage1:
        cx = (b[0] + b[2]) / 2.0
        cy = (b[1] + b[3]) / 2.0
        if not _point_in_polygon(cx, cy, ignored):
            stage2.append(b)
    # Pass 3: NMS-ish dedupe (live runs IoU dedupe — O(n²) on a small list).
    stage3 = []
    for b in stage2:
        keep = True
        for k in stage3:
            if abs(b[0] - k[0]) < 10 and abs(b[1] - k[1]) < 10:
                keep = False
                break
        if keep:
            stage3.append(b)
    # Pass 4: channel polygon filter + ChannelDetection list comp.
    return channel_detections_from_result(role, stage3)
