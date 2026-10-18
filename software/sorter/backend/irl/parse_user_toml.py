"""Reads machine.toml for start-up: the file itself and the layer servos' wiring.

Settings a person changes from the UI (stepper drivers, the chute, servo
speeds) are read and saved through hardware_settings instead."""

from dataclasses import dataclass

from global_config import GlobalConfig
import machine_toml


def loadMachineSpecificParams(gc: GlobalConfig) -> dict[str, object]:
    if not machine_toml.machine_toml_path().exists():
        gc.logger.warning(
            f"No machine config at {machine_toml.machine_toml_path()}; using default stepper currents and servo angles."
        )
    return machine_toml.read()


@dataclass
class ServoChannelConfig:
    id: int | None
    invert: bool = False


@dataclass
class WaveshareServoConfig:
    port: str | None  # None = auto-detect
    channels: list[ServoChannelConfig]


def loadServoChannelConfig(
    gc: GlobalConfig,
    machine_specific_params: dict[str, object] | None = None,
    *,
    backend: str | None = None,
) -> list[ServoChannelConfig]:
    raw = machine_specific_params
    if raw is None:
        raw = loadMachineSpecificParams(gc)

    if not isinstance(raw, dict):
        return []

    servo_params = raw.get("servo")
    if not isinstance(servo_params, dict):
        return []

    channels_raw = servo_params.get("channels", [])
    if not isinstance(channels_raw, list):
        gc.logger.warning("servo.channels must be a list of {id, invert} objects.")
        return []

    backend_name = backend
    if backend_name is None:
        raw_backend = servo_params.get("backend", "pca9685")
        backend_name = raw_backend if isinstance(raw_backend, str) else "pca9685"

    channels: list[ServoChannelConfig] = []
    for i, ch in enumerate(channels_raw):
        if not isinstance(ch, dict):
            gc.logger.warning(f"Ignoring invalid servo.channels[{i}]: expected object.")
            continue

        ch_id = ch.get("id")
        if ch_id is None:
            channels.append(ServoChannelConfig(id=None, invert=bool(ch.get("invert", False))))
            continue

        if not isinstance(ch_id, int) or isinstance(ch_id, bool):
            gc.logger.warning(f"Ignoring servo.channels[{i}]: id must be an integer or null, got {ch_id!r}")
            channels.append(ServoChannelConfig(id=None, invert=bool(ch.get("invert", False))))
            continue

        if backend_name == "waveshare":
            valid = 1 <= ch_id <= 253
            valid_text = "int 1-253"
        else:
            valid = ch_id >= 0
            valid_text = "non-negative int"

        if not valid:
            gc.logger.warning(
                f"Ignoring servo.channels[{i}]: id must be {valid_text}, got {ch_id!r}"
            )
            continue

        channels.append(ServoChannelConfig(id=ch_id, invert=bool(ch.get("invert", False))))

    return channels


def loadWaveshareServoConfig(
    gc: GlobalConfig,
    machine_specific_params: dict[str, object] | None = None,
) -> WaveshareServoConfig | None:
    """Parse waveshare servo config from TOML. Returns None if backend is not 'waveshare'."""
    raw = machine_specific_params
    if raw is None:
        raw = loadMachineSpecificParams(gc)

    if not isinstance(raw, dict):
        return None

    servo_params = raw.get("servo")
    if not isinstance(servo_params, dict):
        return None

    backend = servo_params.get("backend", "pca9685")
    if backend != "waveshare":
        return None

    port = servo_params.get("port")  # None = auto-detect
    if port is not None and not isinstance(port, str):
        gc.logger.warning(f"Invalid servo.port={port!r}; expected string. Will auto-detect.")
        port = None

    return WaveshareServoConfig(
        port=port,
        channels=loadServoChannelConfig(gc, raw, backend="waveshare"),
    )
