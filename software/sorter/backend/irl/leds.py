from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from global_config import GlobalConfig
from hardware.sorter_interface import DIGITAL_OUTPUT_DUTY_MAX
from local_state import (
    LED_CONTROL_DEFAULTS,
    get_led_control_state,
    set_led_control_state,
)
from machine_platform.control_board import BoardIdentity

if TYPE_CHECKING:
    from hardware.sorter_interface import DigitalOutputPin

    from .parse_user_toml import GpioLedConfig


class DigitalOutputHost(Protocol):
    @property
    def digital_outputs(self) -> "Sequence[DigitalOutputPin]": ...


class LedCapableBoard(Protocol):
    # Structural rather than the ControlBoard ABC: binding LEDs only ever reads
    # the board's name/role and its digital outputs.
    @property
    def identity(self) -> BoardIdentity: ...

    @property
    def interface(self) -> DigitalOutputHost: ...


def brightnessPercentToDuty(brightness_percent: int) -> int:
    clamped = max(0, min(100, int(brightness_percent)))
    return round(clamped * DIGITAL_OUTPUT_DUTY_MAX / 100)


@dataclass
class BoundLed:
    board_role: str
    board_name: str
    channel: int
    pin: "DigitalOutputPin"


class LedController:
    def __init__(self, gc: GlobalConfig, leds: Sequence[BoundLed]) -> None:
        self._gc = gc
        self._leds = leds
        self._state = get_led_control_state()

    @property
    def state(self) -> dict[str, Any]:
        return dict(self._state)

    def applyBootState(self) -> dict[str, Any]:
        # Probe PWM support here so the first bus round-trip happens during
        # hardware init rather than inside whichever request thread polls
        # /api/leds first.
        self._pwmSupported()
        # "Come on at boot" is the only thing that decides whether the LEDs are
        # lit after a restart — the persisted on/off is overwritten to match it
        # so the two settings can never disagree about what just happened.
        self._state["enabled"] = bool(self._state["on_at_boot"])
        self._state = set_led_control_state(self._state)
        self._drive()
        return self.state

    def update(self, updates: dict[str, Any]) -> dict[str, Any]:
        # Merge onto what is on disk, not onto the cached copy: the API also
        # writes settings straight to local state while hardware is down.
        self._state = set_led_control_state({**get_led_control_state(), **updates})
        self._drive()
        return self.state

    def allOff(self) -> None:
        for led in self._leds:
            try:
                led.pin.value = False
            except Exception as exc:
                self._gc.logger.warning(
                    f"LED {led.board_role} ch{led.channel}: failed to turn off: {exc}"
                )

    def status(self) -> dict[str, Any]:
        return {
            **self.state,
            "defaults": dict(LED_CONTROL_DEFAULTS),
            "configured": len(self._leds) > 0,
            "pwm_supported": self._pwmSupported(),
            "leds": [
                {
                    "board_role": led.board_role,
                    "board_name": led.board_name,
                    "channel": led.channel,
                    "duty": led.pin.duty,
                }
                for led in self._leds
            ],
        }

    def _pwmSupported(self) -> bool:
        if not self._leds:
            return False
        return all(led.pin.pwm_supported for led in self._leds)

    def _drive(self) -> None:
        duty = (
            brightnessPercentToDuty(int(self._state["brightness_percent"]))
            if self._state["enabled"]
            else 0
        )
        for led in self._leds:
            try:
                led.pin.setDuty(duty)
            except Exception as exc:
                self._gc.logger.warning(
                    f"LED {led.board_role} ch{led.channel}: failed to set duty {duty}: {exc}"
                )
        self._gc.logger.info(
            f"LEDs: enabled={self._state['enabled']} "
            f"brightness={self._state['brightness_percent']}% duty={duty} "
            f"across {len(self._leds)} output(s)"
        )


def bindGpioLeds(
    gc: GlobalConfig,
    control_boards: Sequence[LedCapableBoard],
    led_configs: "Sequence[GpioLedConfig]",
) -> list[BoundLed]:
    bound: list[BoundLed] = []
    for cfg in led_configs:
        matched = [
            b for b in control_boards
            if cfg.board == "any" or b.identity.role == cfg.board
        ]
        for board in matched:
            outputs = board.interface.digital_outputs
            if cfg.pin >= len(outputs):
                gc.logger.warning(
                    f"gpio_leds: board {board.identity.role} ({board.identity.device_name}) "
                    f"has no digital output at pin {cfg.pin} (only {len(outputs)} outputs). Skipping."
                )
                continue
            bound.append(
                BoundLed(
                    board_role=board.identity.role,
                    board_name=board.identity.device_name,
                    channel=cfg.pin,
                    pin=outputs[cfg.pin],
                )
            )
    return bound
