from __future__ import annotations

from machine_runtime.base import MachineRuntime
from machine_runtime.classification_channel import ClassificationChannelRuntime
from machine_runtime.standard_carousel import StandardCarouselRuntime
from machine_setup import get_machine_setup_definition


def build_machine_runtime(machine_setup_key: object) -> MachineRuntime:
    definition = get_machine_setup_definition(machine_setup_key)
    # Capability, not key: belt_feeder also runs the classification C-channel.
    if definition.uses_classification_channel:
        return ClassificationChannelRuntime(definition)
    return StandardCarouselRuntime(definition)
