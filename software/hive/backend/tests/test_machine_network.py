"""Where to find a Sorter: the heartbeat's network block, stored and shown only
to the machine's owner and admins."""

from __future__ import annotations

import copy
from uuid import UUID

from app.machine_network import MAX_NETWORKS, normalize_network_block
from app.models.machine import Machine
from app.models.user import User
from tests.conftest import _auth_headers, _login_user, _register_user

BLOCK = {
    "version": 1,
    "at": 1790274659,
    "clock_ok": True,
    "hostname": "sorter",
    "mdns": "sorter.local",
    "ports": {"ui": 80, "backend": 8000},
    "networks": [
        {"kind": "wifi", "iface": "wlan0", "name": "HomeNet", "address": "192.168.1.68",
         "internet": True, "since": 1790274600},
        {"kind": "ethernet", "iface": "eth0", "name": "Ethernet", "address": "192.168.2.3",
         "internet": False, "since": 1790274000},
        {"kind": "tailscale", "iface": "tailscale0", "name": "Tailscale", "address": "100.64.1.2",
         "internet": None, "since": 1790274000},
    ],
    "setup_network": None,
}


def _beat(client, token: str, body: dict | None):
    return client.post("/api/machine/heartbeat", headers={"Authorization": f"Bearer {token}"}, json=body)


def _machine(db, machine_id: str) -> Machine:
    db.expire_all()
    return db.query(Machine).filter(Machine.id == UUID(machine_id)).one()


# --- storing it --------------------------------------------------------------


def test_heartbeat_stores_the_block_and_when_it_arrived(client, db, test_machine, machine_token):
    assert _beat(client, machine_token, {"network": BLOCK}).status_code == 200

    machine = _machine(db, test_machine["id"])
    assert machine.network_info == BLOCK
    assert machine.network_reported_at is not None
    assert machine.last_seen_at is not None


def test_owner_sees_it_on_the_overview(client, test_machine, machine_token):
    _beat(client, machine_token, {"network": BLOCK})

    body = client.get(f"/api/machines/{test_machine['id']}/overview").json()["machine"]
    assert body["network_info"] == BLOCK
    assert body["network_reported_at"] is not None
    assert "last_seen_ip" not in body
    assert "local_ui_port" not in body


def test_a_beat_without_the_key_keeps_the_block(client, db, test_machine, machine_token):
    # Older Sorter software, or a specs-only beat: nothing to change.
    _beat(client, machine_token, {"network": BLOCK})
    assert _beat(client, machine_token, {"hardware_info": {"cpu": "RPi5"}}).status_code == 200
    assert _beat(client, machine_token, None).status_code == 200
    assert _machine(db, test_machine["id"]).network_info == BLOCK


def test_null_forgets_the_block(client, db, test_machine, machine_token):
    _beat(client, machine_token, {"network": BLOCK})
    assert _beat(client, machine_token, {"network": None}).status_code == 200

    machine = _machine(db, test_machine["id"])
    assert machine.network_info is None
    assert machine.network_reported_at is None


def test_junk_never_fails_the_keep_alive(client, db, test_machine, machine_token):
    _beat(client, machine_token, {"network": BLOCK})
    for junk in ("sorter.local", 42, ["192.168.1.68"], True):
        assert _beat(client, machine_token, {"network": junk}).status_code == 200
    assert _machine(db, test_machine["id"]).network_info == BLOCK


# --- who sees it ---------------------------------------------------------------


def _second_member(client, db) -> User:
    _register_user(client, "other@test.com", "Password123!", "Other User")
    _login_user(client, "other@test.com", "Password123!")
    return db.query(User).filter(User.email == "other@test.com").one()


def test_scope_all_hides_other_peoples_addresses(client, db, test_machine, machine_token):
    _beat(client, machine_token, {"network": BLOCK})
    other = _second_member(client, db)
    own = client.post("/api/machines", json={"name": "Mine"}, headers=_auth_headers(client)).json()
    _beat(client, own["raw_token"], {"network": BLOCK})

    listed = {m["id"]: m for m in client.get("/api/machines?scope=all").json()}

    theirs = listed[test_machine["id"]]
    assert theirs["name"] == "Test Sorter"
    assert theirs["network_info"] is None
    assert theirs["network_reported_at"] is None
    # Never in a list response, for anyone.
    for machine in listed.values():
        assert "last_seen_ip" not in machine
        assert "hardware_info" not in machine
        assert "local_ui_port" not in machine
    assert listed[own["id"]]["network_info"] == BLOCK

    # An admin sees every machine's.
    other.role = "admin"
    db.commit()
    listed = {m["id"]: m for m in client.get("/api/machines?scope=all").json()}
    assert listed[test_machine["id"]]["network_info"] == BLOCK
    overview = client.get(f"/api/machines/{test_machine['id']}/overview").json()
    assert overview["machine"]["network_info"] == BLOCK


def test_owner_lists_their_own(client, test_machine, machine_token):
    _beat(client, machine_token, {"network": BLOCK})
    (mine,) = client.get("/api/machines").json()
    assert mine["network_info"] == BLOCK
    assert mine["network_reported_at"] is not None


def test_other_member_cannot_open_the_overview(client, db, test_machine, machine_token):
    _beat(client, machine_token, {"network": BLOCK})
    _second_member(client, db)
    assert client.get(f"/api/machines/{test_machine['id']}/overview").status_code == 404


def test_admin_fleet_list_has_no_ui_port(client, db, test_machine):
    user = db.query(User).filter(User.email == "member@test.com").one()
    user.role = "admin"
    db.commit()
    (row,) = client.get("/api/admin/machines").json()
    assert "local_ui_port" not in row
    assert "last_seen_ip" in row


# --- validating it ---------------------------------------------------------------


def test_a_well_formed_block_passes_through_unchanged():
    assert normalize_network_block(copy.deepcopy(BLOCK)) == BLOCK


def test_not_a_block():
    for raw in (None, "x", 1, [], True):
        assert normalize_network_block(raw) is None


def test_empty_block_has_every_key():
    assert normalize_network_block({}) == {
        "version": None,
        "at": None,
        "clock_ok": None,
        "hostname": None,
        "mdns": None,
        "ports": {"ui": None, "backend": None},
        "networks": [],
        "setup_network": None,
    }


def test_addresses_must_be_something_another_device_can_open():
    def address(value):
        networks = normalize_network_block({"networks": [{"kind": "wifi", "address": value}]})["networks"]
        return networks[0]["address"] if networks else None

    assert address("192.168.1.68") == "192.168.1.68"
    assert address(" 10.0.0.7 ") == "10.0.0.7"
    assert address("2001:db8::1") == "2001:db8::1"
    for bad in (
        "127.0.0.1", "0.0.0.0", "224.0.0.1", "::1", "fe80::1", "fe80::1%wlan0",
        "sorter.local", "192.168.1.68:80", "http://192.168.1.68/", "192.168.1.68/24",
        "1" * 100, 1921681068, None,
    ):
        assert address(bad) is None, bad


def test_names_that_become_link_hosts_are_dns_names():
    def mdns(value):
        return normalize_network_block({"mdns": value})["mdns"]

    assert mdns("sorter.local") == "sorter.local"
    assert mdns("Sorter-2.LOCAL.") == "sorter-2.local"
    for bad in ("sorter", "sorter.lan", "a b.local", "sorter.local/x", "<b>.local", "-x.local", "x" * 70 + ".local", 7):
        assert mdns(bad) is None, bad
    assert normalize_network_block({"hostname": "evil\"><script>"})["hostname"] is None


def test_fields_are_typed_and_bounded():
    block = normalize_network_block(
        {
            "version": "1",
            "at": float("inf"),
            "clock_ok": "yes",
            "ports": {"ui": 0, "backend": 70000},
            "networks": [
                {"kind": "satellite", "iface": "wlan0; rm -rf /", "name": "Home\x00Net\n" + "x" * 500,
                 "address": "192.168.1.68", "internet": "true", "since": -5},
                {"kind": ["wifi"], "address": "192.168.1.69"},
                "not a network",
                {"kind": "wifi", "name": "no address"},
            ],
            "setup_network": {"ssid": "SorterOS-Setup-ABCDEF", "clients": -1, "since": 1790274000},
        }
    )
    assert block["version"] is None
    assert block["at"] is None
    assert block["clock_ok"] is None
    assert block["ports"] == {"ui": None, "backend": None}
    first, second = block["networks"]
    assert first["kind"] == "other"
    assert first["iface"] is None
    assert first["name"] == ("HomeNet" + "x" * 500)[:64]
    assert first["internet"] is None
    assert first["since"] is None
    assert second["kind"] == "other"
    assert block["setup_network"] == {"ssid": "SorterOS-Setup-ABCDEF", "clients": None, "since": 1790274000}


def test_networks_are_capped():
    many = [{"kind": "ethernet", "address": f"10.0.0.{i}"} for i in range(1, 200)]
    networks = normalize_network_block({"networks": many})["networks"]
    assert len(networks) == MAX_NETWORKS
    assert networks[0]["address"] == "10.0.0.1"


def test_setup_network_needs_a_name():
    assert normalize_network_block({"setup_network": {"clients": 1}})["setup_network"] is None
    assert normalize_network_block({"setup_network": "on"})["setup_network"] is None
