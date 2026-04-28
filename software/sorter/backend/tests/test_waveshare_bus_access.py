from __future__ import annotations

from server.services import waveshare_bus_access as access


class _ServoController:
    def __init__(self, bus_service: object) -> None:
        self.bus_service = bus_service


class _Irl:
    def __init__(self, bus_service: object) -> None:
        self.servo_controller = _ServoController(bus_service)


def test_active_waveshare_service_returns_live_bus(monkeypatch) -> None:
    bus_service = object()
    monkeypatch.setattr(access.shared_state, "getActiveIRL", lambda: _Irl(bus_service))

    assert access.active_waveshare_service() is bus_service


def test_configured_waveshare_service_uses_trimmed_port(monkeypatch) -> None:
    calls: list[tuple[str, float]] = []
    service = object()

    def fake_get_waveshare_bus_service(port: str, *, timeout: float):
        calls.append((port, timeout))
        return service

    monkeypatch.setattr(
        "hardware.waveshare_bus_service.get_waveshare_bus_service",
        fake_get_waveshare_bus_service,
    )

    result = access.configured_waveshare_service(
        {"servo": {"port": "  /dev/ttyUSB0  "}},
        timeout=0.15,
    )

    assert result is service
    assert calls == [("/dev/ttyUSB0", 0.15)]


def test_waveshare_service_prefers_live_bus(monkeypatch) -> None:
    bus_service = object()
    monkeypatch.setattr(access, "active_waveshare_service", lambda: bus_service)

    def fail_read_config():
        raise AssertionError("configured fallback should not be read")

    monkeypatch.setattr(access, "read_machine_params_config", fail_read_config)

    assert access.waveshare_service() is bus_service
