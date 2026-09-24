"""sorteros-network's decisions against a simulated Sorter: a clock, a cable,
routers, a radio that can (or can't) broadcast beside a connection, and
phones on the setup network. Run: python3 -m unittest test/test_network.py"""

import importlib.util
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "build/overlay/usr/local/sbin/sorteros-network.py"
_spec = importlib.util.spec_from_file_location("sorteros_network", _SRC)
net = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(net)

WALL = 1_790_000_000.0
AUTOCONNECT_S = 8  # NetworkManager joining a saved network on its own
JOIN_S = 4  # an explicit join, when it works
WRONG_PASSWORD_S = 11  # measured on the AP6275P


class Router:
    def __init__(self, password="right-password", *, security="WPA2", internet=True, dhcp=True,
                 up=lambda t: True, signal=70):
        self.password, self.security, self.internet, self.dhcp = password, security, internet, dhcp
        self.up, self.signal = up, signal


class World:
    """What outlives a restart of the service: the clock, the air, the cable,
    NetworkManager's saved profiles and the files under /var/lib/sorteros."""

    def __init__(self, *, routers=None, cable=None, radio="concurrent", ntp=True):
        self.t = 0.0
        self.routers = dict(routers or {})
        self.cable = cable  # None, or {"at": t, "internet": bool, "dhcp": bool}
        self.radio = radio  # "concurrent" (the AP6275P), "single", or None (no Wi-Fi at all)
        self.ntp = ntp
        self.clock_off = 0.0
        self.saved = {}  # ssid -> {"uuid", "password", "security"}
        self.wifi_on = None  # the network wlan0 is on
        self.possible_since = None  # when autoconnect became possible
        self.ap_on = None  # the SSID it broadcasts
        self.ap0 = False
        self.phones = 0  # on the setup network
        self.fenced = set()
        self.nm_on_top = False  # NetworkManager's sharing rules above the fence
        self.config = {}
        self.imported = ""
        self.join_record = None
        self.events = []
        self.status = None
        self.announce = None
        self.hive = {"pubkey": None, "sealed_to": None}
        self.software = None
        self.country = "CN"
        self.log = []

    def count(self, kind):
        return sum(1 for e in self.log if e[0] == kind)

    def texts(self):
        return [e["text"] for e in self.events]


class Fake(net.System):
    def __init__(self, w: World):
        self.w = w

    def _run(self, *cmd, timeout=20):
        raise AssertionError(f"ran {cmd}")

    def _log(self, *entry):
        self.w.log.append(entry)

    # clock
    def now(self):
        return self.w.t

    def sleep(self, s):
        self.w.t += s
        self._autoconnect()

    def wall_now(self):
        return WALL + self.w.t - self.w.clock_off

    def boot_id(self):
        return "boot"

    def clock_synced(self):
        return self.w.ntp

    def http_date(self):
        return WALL + self.w.t

    def set_clock(self, t):
        self._log("set_clock", t)
        self.w.clock_off = 0.0

    # the world
    def _router_ok(self, ssid):
        r = self.w.routers.get(ssid)
        return r is not None and r.up(self.w.t)

    def _radio_free(self):
        return self.w.radio == "concurrent" or not self.w.ap_on

    def _autoconnect(self):
        w = self.w
        if w.radio is None or w.wifi_on or not self._radio_free():
            w.possible_since = None
            return
        ok = [s for s, p in w.saved.items()
              if self._router_ok(s) and w.routers[s].password == p["password"] and w.routers[s].dhcp]
        if not ok:
            w.possible_since = None
        elif w.possible_since is None:
            w.possible_since = w.t
        elif w.t - w.possible_since >= AUTOCONNECT_S:
            w.wifi_on = ok[0]
            self._log("autoconnect", ok[0], w.t)

    def _cable_state(self):
        c = self.w.cable
        if c is None or self.w.t < c["at"]:
            return "unavailable"
        return "connected" if c.get("dhcp", True) and self.w.t >= c["at"] + 2 else "connecting"

    def devices(self):
        w = self.w
        out = [{"iface": "eth0", "kind": "ethernet", "state": self._cable_state()}]
        if w.radio:
            wlan_connected = w.wifi_on or (w.radio == "single" and w.ap_on)
            out.append({"iface": "wlan0", "kind": "wifi", "state": "connected" if wlan_connected else "disconnected"})
        if w.ap0:
            out.append({"iface": "ap0", "kind": "wifi", "state": "connected" if w.ap_on else "disconnected"})
        return out

    def device_info(self, iface):
        w = self.w
        if iface == "eth0" and self._cable_state() == "connected":
            return {"address": "192.168.2.3", "internet": "full" if w.cable.get("internet") else "limited", "uuid": "eth"}
        if iface == "wlan0" and w.wifi_on:
            internet = "full" if w.routers[w.wifi_on].internet else "portal"
            return {"address": "192.168.1.68", "internet": internet, "uuid": w.saved[w.wifi_on]["uuid"]}
        if iface == "wlan0" and w.ap_on:
            return {"address": net.AP_ADDR, "internet": "limited", "uuid": "ap"}
        return {"address": None, "internet": "unknown", "uuid": None}

    def check_internet(self):
        pass

    def ssid_of(self, con_uuid):
        return next((s for s, p in self.w.saved.items() if p["uuid"] == con_uuid), None)

    def carrier(self, iface):
        return self._cable_state() != "unavailable"

    def tailscale_ip(self):
        return None

    def hostname(self):
        return self.w.config.get("hostname") or "sorter"

    def mdns_name(self):
        return f"{self.hostname()}.local"

    def mac(self, iface):
        return "02:11:22:ab:cd:ef"

    # profiles
    def saved_wifi(self):
        return list(self.w.saved)

    def write_wifi(self, ssid, password, hidden=False, security=""):
        replaced = {ssid: dict(self.w.saved[ssid])} if ssid in self.w.saved else {}
        con_uuid = f"uuid-{len(self.w.log)}"
        self.w.saved[ssid] = {"uuid": con_uuid, "password": password, "security": security}
        self._log("write", ssid, password, security)
        return con_uuid, replaced

    def forget_wifi(self, con_uuid, replaced):
        ssid = self.ssid_of(con_uuid)
        self.w.saved.pop(ssid, None)
        self.w.saved.update(replaced)
        if self.w.wifi_on == ssid and ssid not in self.w.saved:
            self.w.wifi_on = None
        self._log("forget", ssid)

    def join(self, con_uuid, iface):
        w = self.w
        ssid = self.ssid_of(con_uuid)
        self._log("join", ssid, w.t)
        assert iface == "wlan0"
        if not self._radio_free():
            return "device is busy"
        if not self._router_ok(ssid):
            w.t += 15
            return "Connection activation failed: The Wi-Fi network could not be found"
        r = w.routers[ssid]
        if r.password != w.saved[ssid]["password"]:
            w.t += WRONG_PASSWORD_S
            return "Connection activation failed: (7) Secrets were required, but not provided."
        if not r.dhcp:
            w.t += 45
            return "Connection activation failed: IP configuration could not be reserved (no available address, timeout, etc.)."
        w.t += JOIN_S
        w.wifi_on = ssid
        return None

    def join_saved(self, ssid, iface):
        return self.join(self.w.saved[ssid]["uuid"], iface)

    def scan(self, iface):
        w = self.w
        self._log("scan", w.t)
        if w.radio == "single" and w.ap_on:
            return []
        w.t += 4
        return sorted(({"ssid": s, "signal": r.signal, "security": r.security}
                       for s, r in w.routers.items() if r.up(w.t)), key=lambda n: -n["signal"])

    # the setup network
    def add_ap_iface(self, wifi_iface):
        if self.w.radio != "concurrent":
            return None
        self.w.ap0 = True
        return net.AP_IFACE

    def ap_up(self, iface, ssid):
        w = self.w
        w.ap_on = ssid
        w.nm_on_top = True
        if w.radio == "single":
            w.wifi_on = None
        self._log("ap_up", iface, w.t)
        return None

    def ap_down(self):
        if self.w.ap_on:
            self._log("ap_down", self.w.t)
        self.w.ap_on = None

    def ap_clients(self, iface):
        return self.w.phones if self.w.ap_on else 0

    def fence(self, iface):
        self.w.fenced.add(iface)
        self.w.nm_on_top = False

    def fenced(self, iface):
        return iface in self.w.fenced and not self.w.nm_on_top

    def unfence(self, iface):
        self.w.fenced.discard(iface)

    # files
    def config(self):
        return dict(self.w.config)

    def update_config(self, **values):
        self.w.config.update({k: v for k, v in values.items() if v})
        self._log("config", dict(self.w.config))

    def zone_tab(self):
        return "US\t+404251-0740023\tAmerica/New_York\nDE\t+5230+01322\tEurope/Berlin\n"

    def set_wifi_country(self, country):
        changed = country != self.w.country
        self.w.country = country
        return changed

    def imported(self):
        return self.w.imported

    def mark_imported(self, digest):
        self.w.imported = digest

    def load_join(self):
        return dict(self.w.join_record) if self.w.join_record else None

    def save_join(self, join):
        self.w.join_record = dict(join) if join else None

    def load_events(self):
        return list(self.w.events)

    def save_event(self, event, keep):
        self.w.events.append(event)

    def software(self):
        return self.w.software

    def write_status(self, status):
        self.w.status = status

    def announce_state(self):
        return self.w.announce

    def set_announce(self, rendezvous_id):
        self.w.announce = {"rendezvous_id": rendezvous_id, "hive_url": "https://hive.example"}

    def clear_announce(self):
        self.w.announce = None

    def rendezvous(self, state):
        if isinstance(self.w.hive, Exception):
            raise self.w.hive
        return self.w.hive["pubkey"], self.w.hive["sealed_to"] == self.w.hive["pubkey"]

    def publish_address(self, state, pubkey, payload):
        self._log("announced", pubkey, payload["ssid"], payload["ip"], self.w.t)
        self.w.hive["sealed_to"] = pubkey


def boot(w: World, cfg=None, **kw):
    """The service starting (the machine, or just the service, restarting)."""
    if cfg is not None:
        w.config = dict(cfg)
    n = net.Network(Fake(w), **kw)
    n.spawn = lambda target: None  # the clock and Find my sorter threads are tested on their own
    net.start(n, w.config)
    return n


def run_for(n, seconds):
    end = n.sys.now() + seconds
    while n.sys.now() < end:
        n.tick()
        n.sys.sleep(net.TICK_S)


def until(n, done, limit=900):
    end = n.sys.now() + limit
    while not done():
        if n.sys.now() >= end:
            raise AssertionError(f"not after {limit} s: {n.sys.w.texts()[-6:]}")
        n.tick()
        n.sys.sleep(net.TICK_S)


def phone_join(n, ssid, password="right-password", **extra):
    n.request_join({"ssid": ssid, "password": password, **extra})


def home():
    return {"HomeNet": Router()}


def saved(w, ssid="HomeNet", password="right-password"):
    w.saved[ssid] = {"uuid": f"saved-{ssid}", "password": password, "security": "WPA2"}


class Boot(unittest.TestCase):
    def test_nothing_saved_no_cable_opens_the_setup_network_at_once(self):
        w = World(routers=home())
        n = boot(w)
        until(n, lambda: w.ap_on)
        self.assertLessEqual(w.t, 10)
        self.assertEqual(w.ap_on, "SorterOS-Setup-ABCDEF")
        self.assertIn("Opened the setup network SorterOS-Setup-ABCDEF: no cable, no saved Wi-Fi", w.texts())

    def test_it_scans_before_it_broadcasts(self):
        w = World(routers=home())
        n = boot(w)
        until(n, lambda: w.ap_on)
        kinds = [e[0] for e in w.log]
        self.assertLess(kinds.index("scan"), kinds.index("ap_up"))
        self.assertEqual([s["ssid"] for s in n.page_state()["scan"]["networks"]], ["HomeNet"])

    def test_a_cable_with_internet_means_no_setup_network(self):
        w = World(routers=home(), cable={"at": 0, "internet": True})
        n = boot(w)
        run_for(n, 120)
        self.assertEqual(w.count("ap_up"), 0)
        self.assertIn("Online by cable at 192.168.2.3", w.texts())

    def test_a_cable_without_internet_doesnt_fool_it(self):
        w = World(routers=home(), cable={"at": 0, "internet": False})
        n = boot(w)
        until(n, lambda: w.ap_on)
        self.assertLessEqual(w.t, net.WIRED_GRACE_S + 10)
        self.assertIn("Connected by cable at 192.168.2.3, but no internet", w.texts())
        self.assertIn("the cable has no internet", w.texts()[-1])

    def test_a_cable_plugged_into_nothing_gets_a_grace_then_the_setup_network(self):
        w = World(routers=home(), cable={"at": 0, "dhcp": False})
        n = boot(w)
        until(n, lambda: w.ap_on)
        self.assertGreaterEqual(w.t, net.WIRED_GRACE_S)

    def test_saved_wifi_joins_on_its_own(self):
        w = World(routers=home())
        saved(w)
        n = boot(w)
        run_for(n, 120)
        self.assertEqual(w.wifi_on, "HomeNet")
        self.assertEqual(w.count("ap_up"), 0)

    def test_no_wifi_hardware_waits_for_a_cable(self):
        w = World(radio=None, cable={"at": 300, "internet": True})
        n = boot(w)
        run_for(n, 200)
        self.assertEqual(w.count("ap_up"), 0)
        until(n, lambda: n.online)


class SetupSite(unittest.TestCase):
    def cfg(self, password="right-password"):
        return {"wifi": {"ssid": "HomeNet", "password": password}}

    def test_its_wifi_is_saved_and_joined(self):
        w = World(routers=home())
        n = boot(w, self.cfg())
        run_for(n, 60)
        self.assertEqual(w.wifi_on, "HomeNet")
        self.assertEqual(n.page_state()["join"]["state"], "joined")
        self.assertEqual(w.count("ap_up"), 0)

    def test_its_wifi_is_imported_once(self):
        w = World(routers=home())
        boot(w, self.cfg()).tick()
        boot(w, self.cfg()).tick()
        self.assertEqual(w.count("write"), 1)

    def test_a_wrong_password_is_forgotten_and_the_setup_page_says_why(self):
        w = World(routers=home())
        n = boot(w, self.cfg("wrong-password"))
        until(n, lambda: w.ap_on)
        join = n.page_state()["join"]
        self.assertEqual((join["state"], join["reason"], join["source"]), ("failed", "password", "setup_site"))
        self.assertNotIn("HomeNet", w.saved)

    def test_a_network_not_up_yet_is_kept_and_joined_when_it_is(self):
        w = World(routers={"HomeNet": Router(up=lambda t: t > 300)})
        n = boot(w, self.cfg())
        until(n, lambda: w.ap_on)
        self.assertEqual(n.page_state()["join"]["reason"], "not_found")
        self.assertIn("HomeNet", w.saved)
        until(n, lambda: w.wifi_on == "HomeNet", limit=900)
        until(n, lambda: not w.ap_on)

    def test_wpa3_only_is_saved_as_sae(self):
        w = World(routers={"HomeNet": Router(security="WPA3")})
        boot(w, self.cfg()).tick()
        self.assertEqual(w.saved["HomeNet"]["security"], "WPA3")


class JoinFromThePhone(unittest.TestCase):
    def setup_network(self, routers=None, **kw):
        w = World(routers=routers or home(), **kw)
        n = boot(w)
        until(n, lambda: w.ap_on)
        w.phones = 1
        run_for(n, 4)
        return w, n

    def test_the_right_password_joins_while_the_phone_watches(self):
        w, n = self.setup_network()
        phone_join(n, "HomeNet")
        self.assertEqual(n.page_state()["join"]["state"], "joining")  # at once, before the next tick
        run_for(n, 10)
        join = n.page_state()["join"]
        self.assertEqual((join["state"], join["address"], join["internet"]), ("joined", "192.168.1.68", True))
        self.assertTrue(w.ap_on)  # still up: the phone reads the result on it
        self.assertEqual(w.count("ap_down"), 0)

    def test_a_wrong_password_says_so_and_the_setup_network_stays(self):
        w, n = self.setup_network()
        phone_join(n, "HomeNet", "wrong-password")
        run_for(n, 20)
        join = n.page_state()["join"]
        self.assertEqual((join["state"], join["reason"]), ("failed", "password"))
        self.assertEqual(w.count("ap_down"), 0)
        self.assertNotIn("HomeNet", w.saved)
        phone_join(n, "HomeNet")
        run_for(n, 10)
        self.assertEqual(n.page_state()["join"]["state"], "joined")

    def test_a_network_out_of_range(self):
        w, n = self.setup_network()
        phone_join(n, "Faraway", hidden=True)
        run_for(n, 30)
        self.assertEqual(n.page_state()["join"]["reason"], "not_found")

    def test_a_router_that_gives_no_address(self):
        w, n = self.setup_network(routers={"HomeNet": Router(dhcp=False)})
        phone_join(n, "HomeNet")
        run_for(n, 60)
        self.assertEqual(n.page_state()["join"]["reason"], "no_address")

    def test_joined_but_no_internet_is_joined_and_says_so(self):
        w, n = self.setup_network(routers={"Cafe": Router(internet=False)})
        phone_join(n, "Cafe")
        run_for(n, 10)
        join = n.page_state()["join"]
        self.assertEqual((join["state"], join["internet"]), ("joined", False))
        self.assertIn("Joined Cafe at 192.168.1.68, but no internet", w.texts())

    def test_the_page_shows_the_internet_arriving_after_the_join(self):
        w, n = self.setup_network(routers={"HomeNet": Router(internet=False)})
        phone_join(n, "HomeNet")
        run_for(n, 10)
        self.assertIs(n.page_state()["join"]["internet"], False)
        w.routers["HomeNet"].internet = True  # the router's uplink comes up
        run_for(n, 4)
        self.assertIs(n.page_state()["join"]["internet"], True)

    def test_a_failed_join_puts_back_the_profile_it_replaced(self):
        w = World(routers=home())
        saved(w, password="old-password")
        n = boot(w)
        until(n, lambda: w.ap_on)
        phone_join(n, "HomeNet", "wrong-password")
        run_for(n, 20)
        self.assertEqual(w.saved["HomeNet"]["password"], "old-password")

    def test_the_setup_network_closes_once_the_phone_has_left(self):
        w, n = self.setup_network()
        phone_join(n, "HomeNet")
        run_for(n, 60)
        self.assertTrue(w.ap_on)  # the phone is still reading
        w.phones = 0
        until(n, lambda: not w.ap_on)
        self.assertIn("Closed the setup network (online)", w.texts())

    def test_done_closes_it_in_seconds(self):
        w, n = self.setup_network()
        phone_join(n, "HomeNet")
        run_for(n, 10)
        n.request_done()
        run_for(n, net.DONE_CLOSE_S + 4)
        self.assertFalse(w.ap_on)

    def test_done_on_a_network_without_internet_doesnt_bring_it_back(self):
        w, n = self.setup_network(routers={"Cafe": Router(internet=False)})
        phone_join(n, "Cafe")
        run_for(n, 10)
        n.request_done()
        run_for(n, 300)
        self.assertFalse(w.ap_on)

    def test_the_phone_brings_its_time_zone_and_a_name(self):
        w, n = self.setup_network()
        phone_join(n, "HomeNet", timezone="America/New_York", name="sorter-3")
        run_for(n, 10)
        self.assertEqual(w.config["hostname"], "sorter-3")
        self.assertEqual(w.country, "US")

    def test_a_second_join_while_joining_is_refused(self):
        w, n = self.setup_network()
        phone_join(n, "HomeNet")
        with self.assertRaises(net.BadRequest):
            phone_join(n, "HomeNet")

    def test_a_failure_from_an_earlier_boot_is_not_shown_once_online(self):
        w = World(routers=home(), cable={"at": 0, "internet": True})
        w.join_record = {"ssid": "HomeNet", "state": "failed", "reason": "password", "boot": "before", "at": 1}
        n = boot(w)
        run_for(n, 10)
        self.assertIsNone(n.page_state()["join"])

    def test_a_join_cut_off_by_a_power_cut_reads_as_interrupted(self):
        w = World(routers=home())
        w.join_record = {"ssid": "HomeNet", "state": "joining", "boot": "before", "at": 1}
        n = boot(w)
        self.assertEqual(n.page_state()["join"]["detail"], "interrupted")


class SingleRadio(unittest.TestCase):
    def test_it_steps_off_the_air_to_join(self):
        w = World(routers=home(), radio="single")
        n = boot(w)
        until(n, lambda: w.ap_on)
        self.assertFalse(n.page_state()["setup_network"]["live_join"])
        phone_join(n, "HomeNet")
        run_for(n, 10)
        self.assertEqual(w.wifi_on, "HomeNet")
        self.assertFalse(w.ap_on)

    def test_a_wrong_password_brings_the_setup_network_back(self):
        w = World(routers=home(), radio="single")
        n = boot(w)
        until(n, lambda: w.ap_on)
        phone_join(n, "HomeNet", "wrong-password")
        until(n, lambda: w.count("ap_up") == 2)
        self.assertEqual(n.page_state()["join"]["reason"], "password")

    def test_saved_networks_are_retried_off_the_air_when_nobody_is_on_it(self):
        w = World(routers={"HomeNet": Router(up=lambda t: t > 200)}, radio="single")
        saved(w)
        n = boot(w)
        until(n, lambda: w.ap_on)
        until(n, lambda: w.wifi_on == "HomeNet", limit=1200)
        self.assertFalse(w.ap_on)


class Recovery(unittest.TestCase):
    def test_a_router_slower_than_the_pi_after_a_power_cut(self):
        w = World(routers={"HomeNet": Router(up=lambda t: t > 150)})
        saved(w)
        n = boot(w)
        until(n, lambda: w.ap_on)
        self.assertGreaterEqual(w.t, net.SAVED_GRACE_S)
        until(n, lambda: w.wifi_on == "HomeNet")
        until(n, lambda: not w.ap_on)
        self.assertLess(w.t, 150 + net.SCAN_EVERY_S + net.IDLE_CLOSE_S + 20)

    def test_a_cable_plugged_in_during_setup_closes_it(self):
        w = World(routers=home(), cable={"at": 100, "internet": True})
        n = boot(w)
        until(n, lambda: w.ap_on)
        until(n, lambda: not w.ap_on)
        self.assertLess(w.t, 100 + net.IDLE_CLOSE_S + 10)

    def test_a_cable_pulled_opens_the_setup_network_after_a_grace(self):
        w = World(routers=home(), cable={"at": 0, "internet": True})
        n = boot(w)
        run_for(n, 30)
        w.cable = None
        pulled = w.t
        until(n, lambda: w.ap_on)
        self.assertGreaterEqual(w.t - pulled, net.LOST_GRACE_S)
        self.assertIn("Cable unplugged", w.texts())

    def test_a_restarted_service_takes_its_old_setup_network_down(self):
        w = World(routers=home(), cable={"at": 0, "internet": True})
        w.ap_on = "SorterOS-Setup-ABCDEF"
        boot(w)
        self.assertIsNone(w.ap_on)

    def test_the_fence_goes_back_on_top_of_networkmanagers_rules(self):
        w = World(routers=home())
        n = boot(w)
        until(n, lambda: w.ap_on)
        self.assertTrue(n.sys.fenced("ap0"))
        w.nm_on_top = True  # NetworkManager restarted the network
        run_for(n, 4)
        self.assertTrue(n.sys.fenced("ap0"))


class Status(unittest.TestCase):
    def test_every_network_with_its_address_and_internet(self):
        w = World(routers=home(), cable={"at": 0, "internet": False})
        saved(w)
        n = boot(w)
        run_for(n, 30)
        s = w.status
        self.assertEqual(s["ports"], {"ui": 80, "backend": 8000})
        self.assertEqual(s["mdns"], "sorter.local")
        by_kind = {x["kind"]: x for x in s["networks"]}
        self.assertEqual((by_kind["wifi"]["name"], by_kind["wifi"]["address"], by_kind["wifi"]["internet"]),
                         ("HomeNet", "192.168.1.68", True))
        self.assertEqual((by_kind["ethernet"]["address"], by_kind["ethernet"]["internet"]), ("192.168.2.3", False))

    def test_the_page_state_matches_the_contract(self):
        w = World(routers=home())
        w.software = {"state": "installing", "step": "Installing packages", "done": 3, "total": 11}
        n = boot(w)
        until(n, lambda: w.ap_on)
        s = n.page_state()
        self.assertEqual(set(s), {"now", "clock_ok", "sorter", "setup_network", "networks", "cable", "join",
                                  "scan", "events"})
        self.assertEqual(s["sorter"]["software"]["done"], 3)
        self.assertEqual(s["setup_network"], {"ssid": "SorterOS-Setup-ABCDEF", "live_join": True})
        self.assertEqual(s["cable"], "none")
        self.assertEqual(s["events"][0]["text"], "Started")

    def test_events_outlive_a_restart(self):
        w = World(routers=home())
        n = boot(w)
        until(n, lambda: w.ap_on)
        n2 = boot(w)
        self.assertEqual([e["text"] for e in n2.page_state()["events"]][:2],
                         ["Started", "Opened the setup network SorterOS-Setup-ABCDEF: no cable, no saved Wi-Fi"])


class Validation(unittest.TestCase):
    scanned = [{"ssid": "HomeNet", "security": "WPA2"}, {"ssid": "Office", "security": "WPA2 802.1X"},
               {"ssid": "Old", "security": "WEP"}, {"ssid": "Cafe", "security": ""}]

    def check(self, body):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "America").mkdir()
            (Path(d) / "America/New_York").write_text("")
            return net.validate_join(body, self.scanned, zoneinfo=Path(d))

    def test_rejects_what_cant_work(self):
        for body in ({"ssid": ""}, {"ssid": "HomeNet", "password": "short"}, {"ssid": "HomeNet", "password": ""},
                     {"ssid": "Office", "password": "long-enough"}, {"ssid": "Old", "password": "long-enough"},
                     {"ssid": "x" * 33}, {"ssid": "HomeNet", "password": "p" * 64},
                     {"ssid": "HomeNet", "password": "long-enough", "name": "Not A Name"}):
            with self.assertRaises(net.BadRequest, msg=body):
                self.check(body)

    def test_keeps_the_ssid_exact_and_drops_unknown_time_zones(self):
        req = self.check({"ssid": " HomeNet ", "password": "long-enough", "timezone": "Mars/Base",
                          "rendezvous_id": "short"})
        self.assertEqual((req["ssid"], req["timezone"], req["rendezvous"]), (" HomeNet ", None, None))
        req = self.check({"ssid": "Cafe", "timezone": "America/New_York", "name": "Sorter-3", "rendezvous_id": "a" * 22})
        self.assertEqual((req["timezone"], req["name"], req["rendezvous"]), ("America/New_York", "sorter-3", "a" * 22))


class Page(unittest.TestCase):
    """The setup page's HTTP side, served for real on localhost."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        static = Path(self.tmp.name)
        (static / "index.html").write_text("<!doctype html><title>setup</title>")
        (static / "_app/immutable").mkdir(parents=True)
        (static / "_app/immutable/app.js").write_text("console.log(1)")
        self.w = World(routers=home())
        self.n = boot(self.w)
        until(self.n, lambda: self.w.ap_on)
        self.server = net.serve_portal(self.n, "127.0.0.1", 0, static, only_on=None)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def get(self, path):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        try:
            r = urllib.request.build_opener(NoRedirect).open(self.base + path, timeout=5)
            return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            r = urllib.request.urlopen(req, timeout=5)
            return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_state_and_files(self):
        code, _, body = self.get("/api/state")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["setup_network"]["ssid"], "SorterOS-Setup-ABCDEF")
        code, headers, body = self.get("/_app/immutable/app.js")
        self.assertEqual((code, body), (200, b"console.log(1)"))
        self.assertIn("immutable", headers["Cache-Control"])
        self.assertEqual(self.get("/")[0], 200)

    def test_captive_portal_checks_land_on_the_page(self):
        for path in ("/hotspot-detect.html", "/generate_204", "/connecttest.txt", "/anything/else", "/../etc/passwd"):
            code, headers, _ = self.get(path)
            self.assertEqual((code, headers["Location"]), (302, "/"), path)

    def test_join_is_accepted_or_says_why_not(self):
        self.assertEqual(self.post("/api/join", {"ssid": "HomeNet", "password": "x"}),
                         (400, {"detail": "Wi-Fi passwords are at least 8 characters."}))
        self.assertEqual(self.post("/api/join", {"ssid": "HomeNet", "password": "right-password"}), (202, {"ok": True}))
        self.assertEqual(json.loads(self.get("/api/state")[2])["join"]["state"], "joining")
        self.assertEqual(self.post("/api/nope", {})[0], 404)

    def test_only_the_setup_network_is_served(self):
        server = net.serve_portal(self.n, "127.0.0.1", 0, Path(self.tmp.name), only_on="10.42.0.1")
        try:
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/state", timeout=5)
            self.assertEqual(e.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()


class Announce(unittest.TestCase):
    def world(self, **kw):
        w = World(routers=home(), **kw)
        saved(w)
        n = boot(w)
        run_for(n, 30)
        w.announce = {"rendezvous_id": "r" * 22, "hive_url": "https://hive.example"}
        return w, n

    def test_gives_the_address_and_the_network_once_the_page_has_a_key(self):
        w, n = self.world()
        w.hive["pubkey"] = "key-1"
        net.announce_address(n)
        self.assertEqual([e[1:4] for e in w.log if e[0] == "announced"], [("key-1", "HomeNet", "192.168.1.68")])
        self.assertIsNone(w.announce)

    def test_on_wifi_with_a_cable_in_it_gives_the_wifi_address(self):
        w, n = self.world(cable={"at": 0, "internet": True})
        w.hive["pubkey"] = "key-1"
        net.announce_address(n)
        self.assertEqual([e[2:4] for e in w.log if e[0] == "announced"], [("HomeNet", "192.168.1.68")])

    def test_sends_again_when_the_page_is_reloaded(self):
        w, n = self.world()
        w.hive["pubkey"] = "key-1"
        orig = Fake.sleep

        def sleep(fake, s):
            orig(fake, s)
            if fake.w.count("announced") == 1:
                fake.w.hive["pubkey"] = "key-2"
        Fake.sleep = sleep
        try:
            net.announce_address(n)
        finally:
            Fake.sleep = orig
        self.assertEqual([e[1] for e in w.log if e[0] == "announced"], ["key-1", "key-2"])

    def test_gives_up_when_the_window_closes_and_can_start_again(self):
        w, n = self.world()
        start = w.t
        n.announcing = True
        net.announce_address(n)  # the page never opened
        self.assertLessEqual(w.t - start, net.ANNOUNCE_WINDOW_S + net.ANNOUNCE_EVERY_S)
        self.assertIsNone(w.announce)
        self.assertFalse(n.announcing)

    def test_an_unreachable_hive_does_not_stop_it(self):
        w, n = self.world()
        w.hive = urllib.error.URLError("Forbidden")
        net.announce_address(n)
        self.assertIsNone(w.announce)


class Clock(unittest.TestCase):
    def test_ntp_answers_so_the_clock_is_left_alone(self):
        w = World(routers=home())
        self.assertEqual(net.settle_clock(Fake(w)), 0.0)
        self.assertEqual(w.count("set_clock"), 0)

    def test_blocked_ntp_takes_the_time_from_a_web_server(self):
        w = World(routers=home(), ntp=False)
        w.clock_off = 3 * 86400
        self.assertAlmostEqual(net.settle_clock(Fake(w)), 3 * 86400, delta=1)
        self.assertEqual(w.count("set_clock"), 1)

    def test_events_stamped_by_the_wrong_clock_are_moved(self):
        w = World(routers=home(), ntp=False, cable={"at": 0, "internet": True})
        w.clock_off = 3 * 86400
        n = boot(w)
        before = n.page_state()["events"][0]["at"]
        n._settle_clock()
        after = n.page_state()["events"][0]["at"]
        self.assertAlmostEqual(after - before, 3 * 86400, delta=1)
        self.assertTrue(n.page_state()["clock_ok"])


class Country(unittest.TestCase):
    tab = "US\t+404251-0740023\tAmerica/New_York\nDE\t+5230+01322\tEurope/Berlin\n"

    def test_the_time_zone_names_the_country(self):
        self.assertEqual(net.wifi_country({"timezone": "Europe/Berlin"}, self.tab), "DE")
        self.assertEqual(net.wifi_country({}, self.tab), "XZ")
        self.assertEqual(net.wifi_country({"timezone": "Mars/Base"}, self.tab), "XZ")

    def test_the_config_line_is_replaced_not_piled_up(self):
        text = net.with_country(net.with_country("nv_by_chip=1\nccode=CN\nregrev=38\n", "US"), "DE")
        self.assertEqual(text, "nv_by_chip=1\nccode=DE\nregrev=0\n")


class Keyfile(unittest.TestCase):
    def test_passwords_keep_backslashes_and_edge_spaces(self):
        self.assertEqual(net.keyfile_value("a\\b"), "a\\\\b")
        self.assertEqual(net.keyfile_value(" pad "), "\\spad\\s")
        self.assertEqual(net.keyfile_value("tab\there"), "tab\\there")

    def test_the_ssid_is_written_as_bytes(self):
        self.assertIn("ssid=67;97;102;195;169;47;78;101;116;\n", net.nm_keyfile("Café/Net", "password1", "u"))

    def test_wpa3_only_takes_sae_and_mixed_mode_takes_psk(self):
        self.assertIn("key-mgmt=sae", net.nm_keyfile("n", "password1", "u", security="WPA3"))
        self.assertIn("key-mgmt=wpa-psk", net.nm_keyfile("n", "password1", "u", security="WPA2 WPA3"))
        self.assertNotIn("wifi-security", net.nm_keyfile("n", "", "u"))

    def test_profile_file_names_are_safe(self):
        for ssid in ("a/b", ".hidden", "..", "x" * 32, "Café"):
            p = net.profile_path(ssid)
            self.assertEqual(p.parent, net.NM_DIR, ssid)
            self.assertFalse(p.name.startswith("."), ssid)
        self.assertNotEqual(net.profile_path("a/b"), net.profile_path("a_b"))

    def test_nmcli_errors_map_to_what_the_page_says(self):
        cases = {"Connection activation failed: (7) Secrets were required, but not provided.": "password",
                 "Connection activation failed: The Wi-Fi network could not be found": "not_found",
                 "IP configuration could not be reserved (no available address, timeout, etc.)": "no_address",
                 "timed out": "timeout", "Something else": "other"}
        for error, reason in cases.items():
            self.assertEqual(net.join_failure_reason(error), reason, error)


class Nmcli(unittest.TestCase):
    def test_terse_fields_undo_both_escapes(self):
        self.assertEqual(net.nmcli_fields(r"a\:b:c\\d:"), ["a:b", "c\\d", ""])

    def test_the_scan_keeps_names_exact_and_drops_hidden_and_setup_networks(self):
        text = " Home :30:WPA2\n Home :70:WPA2\n:90:WPA2\nSorterOS-Setup-ABCDEF:99:\nCafe:40:\n"
        self.assertEqual([n["ssid"] for n in net.parse_scan(text)], [" Home ", "Cafe"])

    def test_connectivity_words(self):
        self.assertEqual(net.connectivity("4 (full)"), "full")
        self.assertEqual(net.connectivity("3 (limited)"), "limited")
        self.assertEqual(net.connectivity(""), "unknown")


class Config(unittest.TestCase):
    def test_placeholder_padding_is_cut_before_parsing(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text('hostname = "a"\n' + net.CFG_END_MARKER + "\n" + "#" * 100 + "\n[[[not toml")
            self.assertEqual(net.read_config(p), {"hostname": "a"})

    def test_written_config_reads_back(self):
        cfg = {"hostname": "sorter-3", "timezone": "Europe/Berlin", "wifi": {"ssid": 'He said "hi"', "password": "p\\w"}}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text(net.config_toml(cfg))
            self.assertEqual(net.read_config(p), cfg)


if __name__ == "__main__":
    unittest.main()
