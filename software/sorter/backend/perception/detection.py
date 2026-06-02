"""Detection — a bbox wrapped with its zone provenance.

A raw model output is just ``(x1, y1, x2, y2)``. ``Detection`` annotates one
with where it landed relative to a channel's regions:

- ``in_primary``: the bbox center is inside this channel's primary polygon mask
  (the region the cascade/state machine acts on).
- ``secondary_zone_ids``: ids of any SECONDARY (foreign) zones whose polygon
  contains the bbox center — display/tag only, never acted on.

This is computed off the hot read path (the ``ChannelState`` slot and
``latest_raw`` stay primary-only and bbox-only), so adding it changes nothing
the subsystem reads.
"""

from __future__ import annotations

from dataclasses import dataclass

from .arcs import Bbox


@dataclass(frozen=True)
class Detection:
    bbox: Bbox
    in_primary: bool
    secondary_zone_ids: tuple[str, ...] = ()
