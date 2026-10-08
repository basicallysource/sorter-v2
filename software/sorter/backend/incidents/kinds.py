"""Every kind of incident the machine raises, as data.

A kind says what happened in a few words (``title``), what the operator does
about it in one sentence (``todo``, filled in from the incident's own fields),
and which buttons its card offers (``actions``, keys into ``actions.ACTIONS``).
Kinds the Incidents settings page lets you switch off or handle automatically
also carry that page's wording and their default handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Union

OFF = "off"
MANUAL = "manual"
AUTOMATIC = "automatic"

Actions = Union[tuple[str, ...], Callable[[dict[str, Any]], tuple[str, ...]]]


@dataclass(frozen=True)
class IncidentKind:
    kind: str
    title: str
    todo: str
    actions: Actions
    # The settings page: kinds with a default handling can be set off, manual
    # or (where automatic_label is set) automatic.
    scope: str = ""
    description: str = ""
    default_handling: str | None = None
    automatic_label: str | None = None
    manual_label: str = "Call the operator"
    off_label: str = "Do not raise it"

    def actionsFor(self, incident: dict[str, Any]) -> tuple[str, ...]:
        return self.actions(incident) if callable(self.actions) else self.actions


def _stallActions(incident: dict[str, Any]) -> tuple[str, ...]:
    # A chute stall loses its home: clearing the latch alone would leave it
    # needing a home, so its one button does both.
    return ("rehome_chute",) if incident.get("requires_rehome") else ("clear_stall",)


KINDS: dict[str, IncidentKind] = {
    k.kind: k
    for k in (
        IncidentKind(
            "exit_stuck",
            title="Stuck on the classification channel",
            todo="A piece is not leaving the classification channel. Take it off and press Done, or let the channel turn to clear it.",
            actions=("clear_c4", "done"),
            scope="Classification",
            description="The classification channel stopped making progress with a piece on it.",
            default_handling=AUTOMATIC,
            automatic_label="Turn the channel forward until it clears",
        ),
        IncidentKind(
            "feeder_jam",
            title="Feeder jam",
            todo="A piece on {channel} does not move when {channel} turns. Free it, then press Done.",
            actions=("done",),
            scope="Feeder",
            description="A piece does not move when its feeder channel turns: it straddles the rim, hangs on the channel above, or sticks at the exit.",
            default_handling=OFF,
            automatic_label="Shake the channel (and nudge the one above) to free it, then call the operator",
        ),
        IncidentKind(
            "stepper_stall",
            title="Motor stalled",
            todo="{motor} stalled. Check it can turn freely, then press Done.",
            actions=_stallActions,
        ),
        IncidentKind(
            "chute_needs_homing",
            title="Chute needs homing",
            todo="The chute lost its position after a stall. Press Home chute.",
            actions=("rehome_chute",),
        ),
        IncidentKind(
            "distribution_chute_jam",
            title="Chute jammed",
            todo="The chute did not reach its bin. Clear what blocks it, then press Done.",
            actions=("done",),
            scope="Distribution",
            description="The chute did not finish a move in time.",
            default_handling=OFF,
            off_label="Leave it to the motor's stall detection",
        ),
        IncidentKind(
            "distribution_servo_bus_offline",
            title="Bin doors not answering",
            todo="The door servos are not responding. Check their cable and power, then press Done.",
            actions=("done",),
            scope="Distribution",
            description="The bin door servos stopped answering.",
            default_handling=OFF,
            off_label="Leave it to the hardware alert",
        ),
        IncidentKind(
            "distribution_no_bin_available",
            title="No bin for this piece",
            todo="No bin takes this piece. Assign a bin or free one up, or send it to the bucket.",
            actions=("pass_through",),
            scope="Distribution",
            description="No bin is assigned for a piece, or every one that fits is full.",
            default_handling=OFF,
            off_label="Send such pieces to the bucket",
        ),
    )
}

# Names older machine.toml files used for a kind.
ALIASES: dict[str, str] = {
    "classification_exit_release": "exit_stuck",
    "channel_exit_stuck": "exit_stuck",
    "classification_exit_stuck": "exit_stuck",
}
