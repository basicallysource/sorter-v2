from subsystems.classification_channel.states import ClassificationChannelState

from .classifying import Classifying
from .context import SimpleStateMachineRev01Context
from .discharging import Discharging
from .idle import Idle
from .rotating_and_capturing import RotatingAndCapturing


def buildRev01StatesMap(
    *,
    irl,
    irl_config,
    gc,
    shared,
    transport,
    vision,
    event_queue,
):
    """Construct the rev01 state map. All states share one run context."""
    context = SimpleStateMachineRev01Context()
    args = (irl, irl_config, gc, shared, transport, vision, event_queue, context)
    return {
        ClassificationChannelState.IDLE: Idle(*args),
        ClassificationChannelState.REV01_ROTATING_AND_CAPTURING: RotatingAndCapturing(*args),
        ClassificationChannelState.REV01_CLASSIFYING: Classifying(*args),
        ClassificationChannelState.REV01_DISCHARGING: Discharging(*args),
    }


__all__ = [
    "buildRev01StatesMap",
    "SimpleStateMachineRev01Context",
    "Idle",
    "RotatingAndCapturing",
    "Classifying",
    "Discharging",
]
