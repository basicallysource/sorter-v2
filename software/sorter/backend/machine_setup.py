from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STANDARD_CAROUSEL_SETUP = "standard_carousel"
CLASSIFICATION_CHANNEL_SETUP = "classification_channel"
MANUAL_CAROUSEL_SETUP = "manual_carousel"

DEFAULT_MACHINE_SETUP = STANDARD_CAROUSEL_SETUP


@dataclass(frozen=True)
class MachineSetupDefinition:
    key: str
    label: str
    description: str
    feeding_mode: str
    automatic_feeder: bool
    uses_carousel_transport: bool
    uses_classification_chamber: bool
    uses_classification_channel: bool
    runs_reverse_pulse_calibration: bool
    homes_carousel: bool
    homes_chute: bool
    requires_carousel_endstop: bool
    runtime_supported: bool

    @property
    def manual_feed_mode(self) -> bool:
        return not self.automatic_feeder

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "feeding_mode": self.feeding_mode,
            "automatic_feeder": self.automatic_feeder,
            "uses_carousel_transport": self.uses_carousel_transport,
            "uses_classification_chamber": self.uses_classification_chamber,
            "uses_classification_channel": self.uses_classification_channel,
            "runs_reverse_pulse_calibration": self.runs_reverse_pulse_calibration,
            "homes_carousel": self.homes_carousel,
            "homes_chute": self.homes_chute,
            "requires_carousel_endstop": self.requires_carousel_endstop,
            "runtime_supported": self.runtime_supported,
        }


MACHINE_SETUPS: dict[str, MachineSetupDefinition] = {
    STANDARD_CAROUSEL_SETUP: MachineSetupDefinition(
        key=STANDARD_CAROUSEL_SETUP,
        label="FIDA + Carousel + Classification Chamber",
        description=(
            "Standard automatic path: bulk feed through the C-channels, carousel handoff, "
            "then classification in the chamber."
        ),
        feeding_mode="auto_channels",
        automatic_feeder=True,
        uses_carousel_transport=True,
        uses_classification_chamber=True,
        uses_classification_channel=False,
        runs_reverse_pulse_calibration=True,
        homes_carousel=True,
        homes_chute=True,
        requires_carousel_endstop=True,
        runtime_supported=True,
    ),
    CLASSIFICATION_CHANNEL_SETUP: MachineSetupDefinition(
        key=CLASSIFICATION_CHANNEL_SETUP,
        label="C-Channels + Classification Channel",
        description=(
            "Experimental topology: replaces the carousel/chamber handoff with a dedicated "
            "classification C-channel that carries its own camera and lighting hood."
        ),
        feeding_mode="auto_channels",
        automatic_feeder=True,
        uses_carousel_transport=False,
        uses_classification_chamber=False,
        uses_classification_channel=True,
        runs_reverse_pulse_calibration=False,
        homes_carousel=False,
        homes_chute=True,
        requires_carousel_endstop=False,
        runtime_supported=True,
    ),
    MANUAL_CAROUSEL_SETUP: MachineSetupDefinition(
        key=MANUAL_CAROUSEL_SETUP,
        label="Manual Carousel Feed",
        description=(
            "Operators place parts directly into the carousel while the downstream "
            "classification and distribution path stays unchanged."
        ),
        feeding_mode="manual_carousel",
        automatic_feeder=False,
        uses_carousel_transport=True,
        uses_classification_chamber=True,
        uses_classification_channel=False,
        runs_reverse_pulse_calibration=False,
        homes_carousel=True,
        homes_chute=True,
        requires_carousel_endstop=True,
        runtime_supported=True,
    ),
}

VALID_MACHINE_SETUPS = frozenset(MACHINE_SETUPS)


def normalize_machine_setup_key(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if normalized in MACHINE_SETUPS:
        return normalized
    return None


def machine_setup_key_from_feeding_mode(mode: object) -> str:
    if mode == "manual_carousel":
        return MANUAL_CAROUSEL_SETUP
    return DEFAULT_MACHINE_SETUP


def get_machine_setup_definition(key: object) -> MachineSetupDefinition:
    normalized = normalize_machine_setup_key(key)
    if normalized is None:
        normalized = DEFAULT_MACHINE_SETUP
    return MACHINE_SETUPS[normalized]


def get_machine_setup_options() -> list[dict[str, Any]]:
    return [definition.to_dict() for definition in MACHINE_SETUPS.values()]
