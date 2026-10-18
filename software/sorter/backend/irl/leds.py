from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from global_config import GlobalConfig
from hardware.bus import MCUBusError
from hardware.sorter_interface import DIGITAL_OUTPUT_DUTY_MAX
from local_state import LED_DEFAULT_BRIGHTNESS_PERCENT, get_led_state, set_led_state
from machine_platform.control_board import BoardIdentity

if TYPE_CHECKING:
    from hardware.sorter_interface import DigitalOutputPin


class LedOutputHost(Protocol):
    @property
    def digital_outputs(self) -> "Sequence[DigitalOutputPin]": ...

    def get_observability_info(self, *, force_refresh: bool = False) -> dict: ...


class LedCapableBoard(Protocol):
    # Structural rather than the ControlBoard ABC: LEDs only ever read the
    # board's identity and its digital outputs.
    @property
    def identity(self) -> BoardIdentity: ...

    @property
    def interface(self) -> LedOutputHost: ...


@dataclass
class LedOutput:
    output_id: str
    board_role: str
    gpio: int
    pin: "DigitalOutputPin"


def brightnessPercentToDuty(brightness_percent: int) -> int:
    clamped = max(0, min(100, int(brightness_percent)))
    return round(clamped * DIGITAL_OUTPUT_DUTY_MAX / 100)


def discoverLedOutputs(
    gc: GlobalConfig, control_boards: "Sequence[LedCapableBoard]"
) -> list[LedOutput]:
    # Firmware declares its LED drivers as the first N digital outputs of the
    # board, so led_gpios[i] is the GPIO behind digital output channel i.
    outputs: list[LedOutput] = []
    for board in control_boards:
        role = board.identity.role
        try:
            gpios = board.interface.get_observability_info().get("led_gpios") or []
        except MCUBusError as exc:
            # Firmware predating GET_OBSERVABILITY NACKs the query. LEDs are an
            # optional convenience; an old board must not take the whole
            # hardware bring-up down with it.
            gc.logger.warning(
                f"LED outputs unavailable on {role} board (firmware does not report "
                f"observability info, update it to use LEDs): {exc}"
            )
            continue
        for channel, gpio in enumerate(gpios):
            outputs.append(
                LedOutput(
                    output_id=f"{role}:{gpio}",
                    board_role=role,
                    gpio=int(gpio),
                    pin=board.interface.digital_outputs[channel],
                )
            )
    gc.logger.info(f"LED outputs: {[o.output_id for o in outputs]}")
    return outputs


def assignChannelLed(
    channel_key: str, output_id: str | None, brightness_percent: int
) -> dict[str, Any]:
    state = get_led_state()
    state["assignments"][channel_key] = output_id
    if output_id is not None:
        state["brightness"][output_id] = brightness_percent
    return set_led_state(state)


class LedController:
    def __init__(self, gc: GlobalConfig, outputs: Sequence[LedOutput]) -> None:
        self._gc = gc
        self._outputs = outputs

    @property
    def outputs(self) -> list[dict[str, Any]]:
        return [
            {"output_id": o.output_id, "board_role": o.board_role, "gpio": o.gpio}
            for o in self._outputs
        ]

    def apply(self, state: dict[str, Any]) -> None:
        claimed = set(state["assignments"].values())
        for output in self._outputs:
            percent = (
                state["brightness"].get(output.output_id, LED_DEFAULT_BRIGHTNESS_PERCENT)
                if output.output_id in claimed
                else 0
            )
            output.pin.setDuty(brightnessPercentToDuty(percent))
            self._gc.logger.info(f"LED {output.output_id}: {percent}%")

    def allOff(self) -> None:
        for output in self._outputs:
            output.pin.setDuty(0)

    def allOn(self) -> None:
        for output in self._outputs:
            output.pin.setDuty(DIGITAL_OUTPUT_DUTY_MAX)
