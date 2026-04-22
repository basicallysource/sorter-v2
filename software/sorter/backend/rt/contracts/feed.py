from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, Union


FeedPurpose = Literal["c2_feed", "c3_feed", "c4_feed", "aux"]


@dataclass(frozen=True, slots=True)
class FeedFrame:
    """One captured frame from a Feed, immutable and passed by reference."""

    feed_id: str
    camera_id: str
    raw: Any
    gray: Any | None
    timestamp: float
    monotonic_ts: float
    frame_seq: int


class Feed(Protocol):
    """A named, purpose-tagged source of FeedFrames for one camera."""

    feed_id: str
    purpose: FeedPurpose
    camera_id: str

    def latest(self) -> FeedFrame | None: ...

    def fps(self) -> float: ...


@dataclass(frozen=True, slots=True)
class RectZone:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True, slots=True)
class PolygonZone:
    vertices: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class PolarZone:
    center_xy: tuple[float, float]
    r_inner: float
    r_outer: float
    theta_start_rad: float
    theta_end_rad: float


Zone = Union[RectZone, PolygonZone, PolarZone]
