"""The kinds of chute a Sorter can have, and everything the software does
differently for each, said once.

The chute is the rotating column that drops each piece into its bin. How the
wiring to its doors crosses the rotating joint decides how it can turn:

- **Cable Cage Chute**: a ribbon cable coiled in a cage. The chute turns a
  little under one full turn between two hard stops and never crosses its home
  switch. Whatever no door catches falls out of the bottom into a tray.
- **Slip Ring Chute**: a slip ring. The chute turns without limit, so it always
  takes the short way round, and it finds home on a magnet that passes a sensor
  once a turn. Its bottom layer has no servo: that door is fixed shut, so
  nothing falls out of the bottom and the pieces no bin wants need a bin of
  their own.

Code that behaves differently per chute reads the facts below. It never tests
which chute this is by name.
"""

from __future__ import annotations

from dataclasses import dataclass

HOME_ON_SWITCH = "switch"
HOME_ON_MAGNET = "magnet"


@dataclass(frozen=True)
class ChuteVariant:
    key: str
    label: str
    summary: str
    # Motor turns for one turn of the chute, as built. A machine's own measured
    # ratio ([chute] gear_ratio) is used instead when it has one.
    gear_ratio: float
    # How far the chute can turn from home, in degrees. None: it turns without limit.
    travel_deg: float | None
    # What marks home: a switch at one end of the travel, or a magnet it passes.
    home_on: str
    # A piece no door catches falls out of the bottom, into a tray. Otherwise the
    # bottom layer catches it, wherever the chute happens to point.
    falls_through: bool
    # The bottom layer's door has no servo and is always shut.
    fixed_bottom_door: bool
    # The bins on each layer of a machine built with this chute, the top layer
    # first: what a machine starts with until its own layout is saved.
    layer_bins: tuple[int, ...]

    @property
    def turns_freely(self) -> bool:
        return self.travel_deg is None


CABLE_CAGE = ChuteVariant(
    key="cable_cage",
    label="Cable Cage Chute",
    summary="A ribbon cable in a cage carries the wiring. The chute turns just under one full turn.",
    gear_ratio=120 / 25,  # 25T motor gear -> 25T idle gear -> 120T chute gear
    travel_deg=350.0,
    home_on=HOME_ON_SWITCH,
    falls_through=True,
    fixed_bottom_door=False,
    layer_bins=(12, 12, 12, 12),
)

SLIP_RING = ChuteVariant(
    key="slip_ring",
    label="Slip Ring Chute",
    summary="A slip ring carries the wiring. The chute turns all the way round, without limit.",
    gear_ratio=6.0,
    travel_deg=None,
    home_on=HOME_ON_MAGNET,
    falls_through=False,
    fixed_bottom_door=True,
    # Quarters at the top, two layers of thirds, halves, and whole bins at the bottom.
    layer_bins=(24, 18, 18, 12, 6),
)

VARIANTS: dict[str, ChuteVariant] = {variant.key: variant for variant in (CABLE_CAGE, SLIP_RING)}
DEFAULT_VARIANT = CABLE_CAGE


def variantFor(key: str | None) -> ChuteVariant:
    return VARIANTS.get(key or "", DEFAULT_VARIANT)
