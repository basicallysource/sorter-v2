"""Access helpers for the active or configured Waveshare servo bus."""

from __future__ import annotations

from typing import Any, Dict

from server import shared_state
from server.config_helpers import read_machine_params_config
from server.waveshare_inventory import get_waveshare_inventory_manager


def active_waveshare_service() -> Any | None:
    active_irl = shared_state.getActiveIRL()
    if active_irl is None:
        return None
    servo_controller = getattr(active_irl, "servo_controller", None)
    return getattr(servo_controller, "bus_service", None)


def configured_waveshare_service(
    config: Dict[str, Any],
    *,
    timeout: float = 0.02,
) -> Any | None:
    servo = config.get("servo", {})
    port = servo.get("port") if isinstance(servo, dict) else None
    if not isinstance(port, str) or not port.strip():
        return None

    from hardware.waveshare_bus_service import get_waveshare_bus_service

    return get_waveshare_bus_service(port.strip(), timeout=timeout)


def waveshare_service(*, timeout: float = 0.02) -> Any | None:
    service = active_waveshare_service()
    if service is not None:
        return service

    _, config = read_machine_params_config()
    return configured_waveshare_service(config, timeout=timeout)


def waveshare_inventory_status(
    *,
    port: str | None = None,
    refresh: bool = False,
) -> Dict[str, Any]:
    manager = get_waveshare_inventory_manager()
    if refresh:
        return manager.refresh(port=port)
    return manager.get_status(port=port)
