from subsystems.classification_channel.states import ClassificationChannelState

from .awaiting_distribution import AwaitingDistribution
from .capturing import Capturing
from .context import SimpleStateMachineRev01Context
from .discharging import Discharging
from .idle import Idle
from .moving_to_precise import MovingToPrecise


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
        ClassificationChannelState.REV01_CAPTURING: Capturing(*args),
        ClassificationChannelState.REV01_MOVING_TO_PRECISE: MovingToPrecise(*args),
        ClassificationChannelState.REV01_AWAITING_DISTRIBUTION: AwaitingDistribution(*args),
        ClassificationChannelState.REV01_DISCHARGING: Discharging(*args),
    }


__all__ = [
    "buildRev01StatesMap",
    "SimpleStateMachineRev01Context",
    "Idle",
    "Capturing",
    "MovingToPrecise",
    "AwaitingDistribution",
    "Discharging",
]
