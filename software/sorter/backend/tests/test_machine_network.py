"""The heartbeat's network block: SorterOS's file when fresh, else the kernel."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import machine_network
from defs.consts import BACKEND_PORT

IP_ADDR_JSON = json.dumps(
    [
        {"ifname": "lo", "flags": ["LOOPBACK", "UP", "LOWER_UP"],
         "addr_info": [{"family": "inet", "local": "127.0.0.1", "scope": "host"}]},
        # An interface without an IPv4 address, as some iproute2 versions print it.
        {},
        {"ifname": "eth0", "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"],
         "addr_info": [{"family": "inet", "local": "192.168.2.3", "scope": "global"}]},
        {"ifname": "wlan0", "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"],
         "addr_info": [
             {"family": "inet", "local": "169.254.10.20", "scope": "link"},
             {"family": "inet", "local": "192.168.1.68", "scope": "global"},
         ]},
        # Configured but no cable: not a way to reach the Sorter.
        {"ifname": "eth1", "flags": ["NO-CARRIER", "BROADCAST", "MULTICAST", "UP"],
         "addr_info": [{"family": "inet", "local": "10.0.0.5", "scope": "global"}]},
        {"ifname": "docker0", "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"],
         "addr_info": [{"family": "inet", "local": "172.17.0.1", "scope": "global"}]},
        {"ifname": "veth1a2b", "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"],
         "addr_info": [{"family": "inet", "local": "172.18.0.1", "scope": "global"}]},
        {"ifname": "tailscale0", "flags": ["POINTOPOINT", "MULTICAST", "NOARP", "UP", "LOWER_UP"],
         "addr_info": [{"family": "inet", "local": "100.64.1.2", "scope": "global"}]},
        {"ifname": "wg0", "flags": ["POINTOPOINT", "NOARP", "UP", "LOWER_UP"],
         "addr_info": [{"family": "inet", "local": "10.8.0.2", "scope": "global"}]},
    ]
)
# nmcli terse output: `:` inside a value is escaped as `\:`.
NMCLI_WIFI = "no:Neighbour:wlan0\nyes:Home\\:Net:wlan0\n"


@pytest.fixture()
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake machine: /sys/class/net, systemd units, the SorterOS file, and
    the two commands the fallback runs."""
    sys_net = tmp_path / "sys-class-net"
    for iface, marker in (("eth0", "device"), ("eth1", "device"), ("wlan0", "wireless"), ("wlan0", "device")):
        (sys_net / iface / marker).mkdir(parents=True, exist_ok=True)
    (sys_net / "docker0" / "bridge").mkdir(parents=True)
    (sys_net / "tailscale0").mkdir(parents=True)
    (sys_net / "wg0").mkdir(parents=True)
    monkeypatch.setattr(machine_network, "SYS_CLASS_NET", sys_net)
    monkeypatch.setattr(machine_network, "SYSTEMD_DIR", tmp_path / "systemd")
    monkeypatch.setattr(machine_network, "SORTEROS_NETWORK_FILE", tmp_path / "run" / "network.json")
    monkeypatch.setattr(machine_network.socket, "gethostname", lambda: "sorter")
    monkeypatch.delenv("SORTER_UI_PORT", raising=False)

    def fake_run(command: list[str], env: dict[str, str] | None = None) -> str | None:
        if command[0] == "ip":
            return IP_ADDR_JSON
        if command[0] == "nmcli":
            return NMCLI_WIFI
        return None

    monkeypatch.setattr(machine_network, "_run", fake_run)
    return tmp_path


def _write_sorteros_file(host: Path, **overrides) -> dict:
    block = {
        "version": 1,
        "at": int(time.time()),
        "clock_ok": True,
        "hostname": "sorter",
        "mdns": "sorter-2.local",
        "ports": {"ui": 80, "backend": 8000},
        "networks": [
            {"kind": "wifi", "iface": "wlan0", "name": "HomeNet", "address": "192.168.1.68",
             "internet": True, "since": 1790274600},
        ],
        "setup_network": None,
        "something_new": "ignored",
    }
    block.update(overrides)
    path = host / "run" / "network.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(block))
    return block


def _enable_ui_unit(host: Path, unit: str, exec_start: str) -> None:
    systemd = host / "systemd"
    (systemd / "multi-user.target.wants").mkdir(parents=True, exist_ok=True)
    (systemd / unit).write_text(
        "[Service]\n"
        "# `--port 5173` in a comment is not the port.\n"
        f"ExecStart={exec_start}\n"
    )
    (systemd / "multi-user.target.wants" / unit).write_text("")


def test_fresh_sorteros_file_is_the_source(host: Path) -> None:
    written = _write_sorteros_file(host)

    block = machine_network.buildNetworkBlock()

    assert block["mdns"] == "sorter-2.local"
    assert block["networks"] == written["networks"]
    assert block["clock_ok"] is True
    assert "something_new" not in block


def test_sorteros_file_with_an_unsynced_clock_is_still_fresh(host: Path) -> None:
    # Before the clock is set, `at` and this process's clock agree with each
    # other even though both are wrong.
    _write_sorteros_file(host, clock_ok=False)
    assert machine_network.buildNetworkBlock()["clock_ok"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"at": int(time.time()) - 600},  # the service stopped writing
        {"version": 2},  # a shape this backend does not know
        {"at": "yesterday"},
    ],
)
def test_stale_or_unknown_file_falls_back_to_interfaces(host: Path, overrides: dict) -> None:
    _write_sorteros_file(host, **overrides)
    block = machine_network.buildNetworkBlock()
    assert block["mdns"] == "sorter.local"
    assert [n["iface"] for n in block["networks"]] == ["eth0", "wlan0", "tailscale0", "wg0"]


def test_unreadable_file_falls_back_to_interfaces(host: Path) -> None:
    path = host / "run" / "network.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    assert machine_network.buildNetworkBlock()["hostname"] == "sorter"


def test_interfaces_fallback_shape(host: Path) -> None:
    block = machine_network.buildNetworkBlock()

    assert block["version"] == 1
    assert abs(block["at"] - time.time()) < 5
    assert block["clock_ok"] is None
    assert block["hostname"] == "sorter"
    assert block["mdns"] == "sorter.local"
    assert block["ports"] == {"ui": machine_network.DEV_UI_PORT, "backend": BACKEND_PORT}
    assert block["setup_network"] is None
    assert block["networks"] == [
        {"kind": "ethernet", "iface": "eth0", "name": "Ethernet", "address": "192.168.2.3",
         "internet": None, "since": None},
        # The global address, and the SSID the interface is joined to.
        {"kind": "wifi", "iface": "wlan0", "name": "Home:Net", "address": "192.168.1.68",
         "internet": None, "since": None},
        {"kind": "tailscale", "iface": "tailscale0", "name": "Tailscale", "address": "100.64.1.2",
         "internet": None, "since": None},
        {"kind": "other", "iface": "wg0", "name": "wg0", "address": "10.8.0.2",
         "internet": None, "since": None},
    ]


def test_no_ip_command_means_no_networks(host: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(machine_network, "_run", lambda command, env=None: None)
    block = machine_network.buildNetworkBlock()
    assert block["networks"] == []
    assert block["mdns"] == "sorter.local"


def test_wifi_without_nmcli_is_named_by_interface(host: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        machine_network, "_run", lambda command, env=None: IP_ADDR_JSON if command[0] == "ip" else None
    )
    wifi = [n for n in machine_network.buildNetworkBlock()["networks"] if n["kind"] == "wifi"]
    assert wifi[0]["name"] == "wlan0"


def test_fqdn_hostname_gives_its_first_label_as_mdns(host: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(machine_network.socket, "gethostname", lambda: "Sorter-01.home.example")
    assert machine_network.buildNetworkBlock()["mdns"] == "sorter-01.local"


def test_ui_port_comes_from_the_enabled_ui_unit(host: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SORTER_UI_PORT", "5173")
    _enable_ui_unit(host, "sorter-ui-dev.service", "/usr/bin/pnpm dev --host 0.0.0.0 --port 80 --strictPort")
    assert machine_network.buildNetworkBlock()["ports"]["ui"] == 80


def test_ui_port_from_a_unit_that_is_not_enabled_is_ignored(host: Path) -> None:
    _enable_ui_unit(host, "sorter-ui.service", "/usr/bin/pnpm preview --host 0.0.0.0 --port=8080")
    (host / "systemd" / "multi-user.target.wants" / "sorter-ui.service").unlink()
    assert machine_network.buildNetworkBlock()["ports"]["ui"] == machine_network.DEV_UI_PORT


def test_ui_port_falls_back_to_the_configured_port(host: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SORTER_UI_PORT", "4173")
    assert machine_network.buildNetworkBlock()["ports"]["ui"] == 4173


def test_nonsense_configured_port_is_ignored(host: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SORTER_UI_PORT", "99999")
    assert machine_network.buildNetworkBlock()["ports"]["ui"] == machine_network.DEV_UI_PORT
