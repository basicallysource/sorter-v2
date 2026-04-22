from __future__ import annotations

from machine_runtime.base import MachineRuntime
from machine_runtime.classification_channel import ClassificationChannelRuntime
from machine_runtime.standard_carousel import StandardCarouselRuntime
from machine_setup import (
    CLASSIFICATION_CHANNEL_SETUP,
    get_machine_setup_definition,
)


def build_machine_runtime(machine_setup_key: object) -> MachineRuntime:
    definition = get_machine_setup_definition(machine_setup_key)
    if definition.key == CLASSIFICATION_CHANNEL_SETUP:
        return ClassificationChannelRuntime(definition)
    return StandardCarouselRuntime(definition)
