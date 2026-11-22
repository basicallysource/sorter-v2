"""Which Sorter this machine is, said once in machine.toml:

    [machine]
    generation = "v3"

A generation is not a setting of its own: it is where the built-in defaults of
every setting that differs between the Sorters come from. No generation saved
is the Sorter V2, whose defaults are the ones every setting had before there
was a second Sorter, so a machine that never names one runs as it always has.

A setting saved in machine.toml always wins over its generation's default, and
so does what a control board says it is made for (its kind of chute, its
feeder's drive). To add a setting that differs by generation, give it a field
here and have its reader ask `machineGeneration()` for its default.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

import machine_toml

MACHINE = "machine"
KEY = "generation"
V2 = "v2"
V3 = "v3"


def plateDiagonalMm(studs: int) -> float:
    """Across the diagonal of a square plate this many studs a side."""
    return round(studs * 8.0 * math.sqrt(2.0), 1)


@dataclass(frozen=True)
class Generation:
    key: str
    label: str
    summary: str
    # The kind of chute (a key of subsystems/distribution/chute_variants.VARIANTS).
    # Its homing, travel, first section and layers follow from the kind.
    chute_variant: str
    # How the C-channels' motors turn their channels (a key of
    # hardware_settings/feeder.DRIVES).
    feeder_drive: str
    # The classification channel's rotor and how the channel is run, as
    # settings of subsystems/classification_channel/two_piece/rev01_config.
    classification_channel: Mapping[str, Any] = field(default_factory=dict)
    # Shrink the camera picture for the detector by averaging areas, the way
    # its training pictures were made. A plain linear shrink of a large picture
    # leaves thin bright things (a rotor's fins) as jagged bars, which a
    # detector that never saw them boxes as pieces.
    smooth_shrink: bool = False
    # Watch every stepper driver while the hardware runs (driver_watch.py):
    # keep its readings, warn when it runs hot, and restart one that has
    # switched itself off.
    driver_watch: bool = False
    # The largest piece a layer takes unless the layer says otherwise, in mm
    # across the piece's diagonal, by how many bins the layer has to a section.
    # Bins per section not listed take any piece.
    layer_max_dimension_mm: Mapping[int, float] = field(default_factory=dict)
    # The classification channel has an exit margin like the feeder channels':
    # a band past its rim over the exit, where boxes are not pieces on the
    # channel but tell the channel that the piece it drops has not fallen.
    classification_exit_margin: bool = False
    # A bin door that meets something (a piece lodged in its way) backs off a
    # little and tries again before anyone is called (subsystems/distribution/
    # positioning.py, DOOR_RETRIES).
    door_retry: bool = False
    # C1 to C3 never shake a piece: their exits only push (never back off or
    # shake the piece at the exit to part it from the one behind, whatever the
    # exit's keep-back setting says), and freeing a piece held where pieces land
    # turns them without shaking (recovery LANDING_HELD_STILL).
    feeder_push_only: bool = False
    # When C1 is asked to feed and gives nothing, the feeder shakes C1 and turns
    # it half round to get the pieces in the bucket moving again before it takes
    # the bucket as empty (subsystems/feeder/pulse_perception/bucket_unjam.py).
    bucket_unjam: bool = False
    # A piece box touching the edge of the picture where pieces land is watched
    # for being held too: a piece hanging off the channel above reaches in from
    # outside the picture (subsystems/feeder/pulse_perception/held.py).
    held_at_landing_edge: bool = False
    # A piece that did not ride the classification channel never holds the
    # machine past its recovery: when every step has been tried, its incident
    # closes as if Done had been pressed (recovery/__init__.py).
    held_gives_up_goes_on: bool = False
    # A piece on C2 or C3 that still does not ride after its recovery ended is
    # taken up again, each time one move further into the recovery
    # (subsystems/feeder/pulse_perception/held.py).
    held_keeps_trying: bool = False
    # When nothing has come off C1 for long and C1 was hardly asked for pieces,
    # the pause says which channel below is not passing pieces on instead of
    # blaming C1 (sorter_controller.py).
    feed_pause_says_why: bool = False

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "summary": self.summary,
            "chute_variant": self.chute_variant,
            "feeder_drive": self.feeder_drive,
            "classification_channel": dict(self.classification_channel),
            "smooth_shrink": self.smooth_shrink,
            "driver_watch": self.driver_watch,
            "layer_max_dimension_mm": dict(self.layer_max_dimension_mm),
        }


GENERATIONS: dict[str, Generation] = {
    V2: Generation(
        key=V2,
        label="Sorter V2",
        summary=(
            "A cable cage chute homed on a switch, geared C-channels, and a five-fin "
            "classification rotor that holds two pieces."
        ),
        chute_variant="cable_cage",
        feeder_drive="geared",
    ),
    V3: Generation(
        key=V3,
        label="Sorter V3",
        summary=(
            "A slip ring chute homed on a magnet, direct-drive C-channels, and a four-fin "
            "classification rotor run pocket by pocket."
        ),
        chute_variant="slip_ring",
        feeder_drive="direct",
        # Four fins make four pockets; the rotor rests with a fin walling the
        # pocket that receives pieces off from the exit, and the channel is run
        # by the pocket flow (subsystems/classification_channel/pocket).
        classification_channel={"fin_count": 4, "fin_at_exit": True},
        smooth_shrink=True,
        classification_exit_margin=True,
        door_retry=True,
        feeder_push_only=True,
        bucket_unjam=True,
        held_at_landing_edge=True,
        held_gives_up_goes_on=True,
        held_keeps_trying=True,
        feed_pause_says_why=True,
        driver_watch=True,
        # Quarter bins take up to a 3x3 plate, thirds a 4x4, halves a 6x6; a
        # full bin takes anything.
        layer_max_dimension_mm={4: plateDiagonalMm(3), 3: plateDiagonalMm(4), 2: plateDiagonalMm(6)},
    ),
}
DEFAULT_GENERATION = GENERATIONS[V2]


def generationSaved(config: Mapping[str, Any] | None = None) -> bool:
    """Whether machine.toml names the machine's generation."""
    if config is None:
        config = machine_toml.read()
    table = config.get(MACHINE)
    return isinstance(table, dict) and KEY in table


def machineGeneration(config: Mapping[str, Any] | None = None, logger: Any = None) -> Generation:
    """The machine's generation. None saved, or an unknown one, is the Sorter V2."""
    if config is None:
        try:
            config = machine_toml.read()
        except machine_toml.MachineTomlError:
            return DEFAULT_GENERATION
    table = config.get(MACHINE)
    name = table.get(KEY) if isinstance(table, dict) else None
    if name is None:
        return DEFAULT_GENERATION
    generation = GENERATIONS.get(name.strip().lower()) if isinstance(name, str) else None
    if generation is None:
        if logger is not None:
            logger.warning(
                f"Ignoring {MACHINE}.{KEY} = {name!r}: expected one of {', '.join(sorted(GENERATIONS))}. "
                f"Taking the machine as a {DEFAULT_GENERATION.label}."
            )
        return DEFAULT_GENERATION
    return generation


def saveMachineGeneration(name: str) -> Generation:
    """Write down the machine's generation. Raises ValueError for an unknown one."""
    key = name.strip().lower() if isinstance(name, str) else ""
    if key not in GENERATIONS:
        raise ValueError(f"A machine's generation is one of {', '.join(sorted(GENERATIONS))}, not {name!r}.")
    with machine_toml.edit() as config:
        table = config.get(MACHINE)
        if not isinstance(table, dict):
            table = {}
            config[MACHINE] = table
        table[KEY] = key
    return GENERATIONS[key]
