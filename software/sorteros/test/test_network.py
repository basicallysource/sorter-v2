"""The boot-time network decisions in sorteros-network, against a simulated
clock and a fake NetworkManager, across restarts. Run:
python3 -m unittest test/test_network.py"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "build/overlay/usr/local/sbin/sorteros-network.py"
_spec = importlib.util.spec_from_file_location("sorteros_network", _SRC)
net = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(net)

HOUR = 3600.0
BOOT_S = 60  # a restart, power-on to this service starting


class Restart(Exception):
    pass


class World:
    """What outlives a restart: the clock, the routers, NetworkManager's saved
    profiles, the files under /var/lib/sorteros, and what was said to Hive."""

    def __init__(self, *, routers=None, up=lambda ssid, t: True, cable_at=None, iface="wlan0", ui_running=False):
        self.t = 0.0
        self.routers = dict(routers or {})  # ssid -> the password it takes
        self.up = up  # is that router on at time t
        self.cable_at = cable_at
        self.iface = iface
        self.ui_running = ui_running
        self.saved = {}  # ssid -> (uuid, password)
        self.imported = ""
        self.pending = None
        self.failed = None
        self.retry = 0
        self.announce = None
        self.hive = {"pubkey": None, "sealed_to": None}
        self.config = {}
        self.country = "CN"  # what the vendor image ships
        self.ntp = True  # does NTP answer
        self.clock_off = 0.0  # how far behind the wall clock is
        self.http_date_works = True
        self.mdns = "sorter.local"
        self.boots = 0
        self.log = []

    def count(self, kind):
        return sum(1 for e in self.log if e[0] == kind)

    def boot(self, cfg=None, **kw):
        """Run the service for one boot. "restart" when it (or the setup page)
        restarted the machine, else what bring_up returned."""
        self.boots += 1
        if self.boots > 1:
            self.t += BOOT_S
        if cfg is not None:
            self.config = cfg
        try:
            return net.bring_up(Fake(self, **kw), self.config)
        except Restart:
            return "restart"

    def run(self, cfg=None, max_boots=20, **kw):
        """Boot until the service finishes without a restart."""
        for _ in range(max_boots):
            result = self.boot(cfg, **kw)
            if result != "restart":
                return result
        raise AssertionError(f"still restarting after {max_boots} boots: {self.log[-8:]}")


class Fake:
    """NetworkManager and the rest of the machine for one boot. A saved
    network joins on its own (autoconnect) a few seconds into the boot when
    its router is on, the password matches and the radio isn't broadcasting.

    `phone` is a list of (t, ssid, password[, timezone]): at time t, while
    the setup network is up, someone submits that on the setup page, which
    leaves it for the service and writes the time zone into the config."""

    def __init__(self, world, *, phone=(), clients=lambda t: False, page_active=lambda t: False,
                 portal_dies_at=None):
        self.w = world
        self.started = world.t
        self.phone = sorted(phone)
        self.clients, self.page_active, self.portal_dies_at = clients, page_active, portal_dies_at
        self.ap = False
        self.portal = False

    def _log(self, *e):
        self.w.log.append(e)

    # clock
    def now(self):
        return self.w.t

    def sleep(self, s):
        self.w.t += s
        t = self.w.t
        if self.portal and self.portal_dies_at is not None and t >= self.portal_dies_at:
            self.portal, self.portal_dies_at = False, None
        if self.ap and self.portal and self.phone and t >= self.phone[0][0]:
            _, ssid, password, *timezone = self.phone.pop(0)
            self._log("phone", ssid, t)
            self.w.pending = {"ssid": ssid, "password": password, "hidden": False, "security": "WPA2"}
            self.w.failed = None
            if timezone:
                self.w.config = {**self.w.config, "timezone": timezone[0]}

    # network
    def wifi_iface(self):
        return self.w.iface

    def _wifi(self):
        if self.ap or not self.w.iface or self.w.t - self.started < 5:
            return None
        for ssid, (_, password) in self.w.saved.items():
            if self.w.routers.get(ssid) == password and self.w.up(ssid, self.w.t):
                return ssid
        return None

    def online(self):
        return (self.w.cable_at is not None and self.w.t >= self.w.cable_at) or self._wifi() is not None

    def joined_ssid(self):
        return self._wifi()

    def mdns_name(self):
        return self.w.mdns

    def lan_ip(self):
        return "192.0.2.50"

    def saved_wifi(self):
        return list(self.w.saved)

    def write_wifi(self, ssid, password, hidden=False, security=""):
        self._log("write", ssid, password)
        replaced = {ssid: self.w.saved[ssid]} if ssid in self.w.saved else {}
        uuid = f"uuid-{len(self.w.log)}"
        self.w.saved[ssid] = (uuid, password)
        return uuid, replaced

    def join(self, uuid, iface):
        ssid = next(s for s, (u, _) in self.w.saved.items() if u == uuid)
        self._log("join", ssid, self.w.t)
        if ssid not in self.w.routers or not self.w.up(ssid, self.w.t):
            self.w.t += 20
            return "Connection activation failed: The Wi-Fi network could not be found"
        if self.w.routers[ssid] != self.w.saved[ssid][1]:
            self.w.t += 11
            return "Connection activation failed: Secrets were required, but not provided"
        self.w.t += 5
        return None

    def forget_wifi(self, uuid, replaced):
        ssid = next(s for s, (u, _) in self.w.saved.items() if u == uuid)
        self._log("forget", ssid)
        del self.w.saved[ssid]
        self.w.saved.update(replaced)

    def scan(self, iface):
        self._log("scan", self.w.t)
        return [{"ssid": s, "signal": 60, "security": "WPA2"}
                for s in self.w.routers if self.w.up(s, self.w.t)]

    def write_networks(self, networks):
        self._log("networks", tuple(n["ssid"] for n in networks))

    def ap_up(self, iface):
        self._log("ap_up", self.w.t)
        self.ap = True
        return "SorterOS-Setup-ABC123"

    def ap_down(self):
        self._log("ap_down", self.w.t)
        self.ap = False

    def ap_has_clients(self, iface):
        return self.clients(self.w.t)

    def reboot(self):
        self._log("reboot", self.w.t)
        raise Restart()

    # the Sorter UI
    def ui_stop(self):
        self._log("ui_stop", self.w.t)
        return ["sorter-ui-dev.service"] if self.w.ui_running else []

    def ui_start(self, units):
        self._log("ui_start", tuple(units), self.w.t)

    # setup page
    def start_portal(self):
        self._log("portal", self.w.t)
        self.portal = True

    def portal_alive(self):
        return self.portal

    def stop_portal(self):
        self.portal = False

    def portal_idle_s(self):
        return 0.0 if self.page_active(self.w.t) else float("inf")

    # state that survives the restart
    def imported(self):
        return self.w.imported

    def mark_imported(self, digest):
        self.w.imported = digest

    def pending(self):
        return self.w.pending

    def clear_pending(self):
        self.w.pending = None

    def record_failure(self, ssid, reason, detail):
        self._log("failed", ssid, reason)
        self.w.failed = {"ssid": ssid, "reason": reason}

    def clear_failure(self):
        self.w.failed = None

    def retry_count(self):
        return self.w.retry

    def set_retry_count(self, n):
        self.w.retry = n

    # the clock
    def wall_now(self):
        return 1_800_000_000 + self.w.t - self.w.clock_off

    def clock_synced(self):
        return self.w.ntp

    def http_date(self):
        return 1_800_000_000 + self.w.t if self.w.http_date_works else None

    def set_clock(self, t):
        self._log("set_clock", round(1_800_000_000 + self.w.t - self.w.clock_off - t))
        self.w.clock_off = 0.0

    # the radio's country
    def config(self):
        return self.w.config

    def zone_tab(self):
        return ZONE_TAB

    def set_wifi_country(self, country):
        if country == self.w.country:
            return False
        self._log("country", country)
        self.w.country = country
        return True

    # Hive
    def announce_state(self):
        return self.w.announce

    def clear_announce(self):
        self._log("announce_closed", self.w.t)
        self.w.announce = None

    def rendezvous(self, state):
        h = self.w.hive
        if isinstance(h, Exception):
            raise h
        return h["pubkey"], h["sealed_to"] == h["pubkey"] and h["pubkey"] is not None

    def publish_address(self, state, pubkey, payload):
        self._log("announced", pubkey, payload["ssid"], self.w.t)
        self.w.hive["sealed_to"] = pubkey


def cfg(ssid="HomeNet", password="right-password"):
    return {"wifi": {"ssid": ssid, "password": password}}


HOME = {"HomeNet": "right-password"}
ZONE_TAB = "# comment\nDE\t+5230+01322\tEurope/Berlin\tmost of Germany\nUS\t+404251-0740023\tAmerica/New_York\tEastern (most areas)\n"


class BringUp(unittest.TestCase):
    def test_cable_means_no_setup_network(self):
        w = World(cable_at=3)
        self.assertEqual(w.run(), 0)
        self.assertEqual(w.count("ap_up"), 0)

    def test_setup_site_wifi_is_saved_and_joined(self):
        w = World(routers=HOME)
        self.assertEqual(w.run(cfg()), 0)
        self.assertIn(("write", "HomeNet", "right-password"), w.log)
        self.assertEqual(w.count("ap_up"), 0)

    def test_setup_site_wifi_is_imported_once(self):
        w = World(routers=HOME)
        w.run(cfg())
        w.run(cfg())
        self.assertEqual(w.count("write"), 1)

    def test_changed_setup_site_wifi_is_imported_again(self):
        w = World(routers={"HomeNet": "new-password"})
        w.run(cfg(password="old-password"), phone=[(HOUR, "HomeNet", "new-password")])
        w.run(cfg(password="new-password"))
        self.assertIn(("write", "HomeNet", "new-password"), w.log)

    def test_no_wifi_given_no_cable_opens_the_setup_network_after_the_wired_wait(self):
        w = World(routers=HOME)
        w.boot(phone=[(5 * 60, "HomeNet", "right-password")])
        self.assertLessEqual(next(e for e in w.log if e[0] == "ap_up")[1], net.WIRED_WAIT_S + net.TICK_S)

    def test_wrong_setup_site_password_opens_the_setup_network_after_one_wait(self):
        w = World(routers=HOME)
        w.boot(cfg(password="wrong"), phone=[(HOUR, "HomeNet", "right-password")])
        first_ap = next(e for e in w.log if e[0] == "ap_up")
        self.assertLessEqual(first_ap[1], net.WIFI_WAIT_S + net.TICK_S)

    def test_a_wrong_setup_site_password_is_forgotten_and_the_page_says_why(self):
        w = World(routers=HOME)
        w.boot(cfg(password="wrong-password"), phone=[(HOUR, "HomeNet", "right-password")])
        self.assertIn(("failed", "HomeNet", "password"), w.log)
        self.assertNotIn(("reboot",), [e[:1] for e in w.log if e[0] == "reboot" and e[1] < HOUR])
        self.assertLessEqual(next(e for e in w.log if e[0] == "ap_up")[1], 11 + net.WIRED_WAIT_S + net.TICK_S)

    def test_a_setup_site_network_that_isnt_up_yet_is_kept(self):
        w = World(routers=HOME, up=lambda s, t: t > 5 * 60)
        w.run(cfg())
        self.assertIn(("failed", "HomeNet", "not_found"), w.log)
        self.assertNotIn(("forget", "HomeNet"), w.log)
        self.assertIsNone(w.failed)  # cleared once it joined

    def test_it_scans_before_it_broadcasts(self):
        w = World(routers={"HomeNet": "x" * 8, "Neighbour": "y" * 8})
        w.boot(phone=[(5 * 60, "HomeNet", "x" * 8)])
        kinds = [e[0] for e in w.log]
        self.assertLess(kinds.index("scan"), kinds.index("ap_up"))
        self.assertIn(("networks", ("HomeNet", "Neighbour")), w.log)


class JoinFromThePhone(unittest.TestCase):
    def test_right_password_restarts_and_joins(self):
        w = World(routers=HOME)
        self.assertEqual(w.run(phone=[(5 * 60, "HomeNet", "right-password")]), 0)
        self.assertEqual(w.count("reboot"), 1)
        self.assertEqual(w.boots, 2)
        self.assertEqual(w.count("ap_up"), 1)
        self.assertIsNone(w.pending)
        self.assertIsNone(w.failed)
        self.assertIn("HomeNet", w.saved)

    def test_wrong_password_brings_the_setup_network_back_and_says_why(self):
        w = World(routers=HOME)
        w.boot(phone=[(5 * 60, "HomeNet", "wrong-password")])
        w.boot(phone=[(w.t + 5 * 60, "HomeNet", "right-password")])
        self.assertIn(("failed", "HomeNet", "password"), w.log)
        self.assertEqual(w.count("ap_up"), 2)  # it came back for the phone
        self.assertEqual(w.run(), 0)  # then the right one works
        self.assertIsNone(w.failed)

    def test_a_network_out_of_range_is_reported_as_not_found(self):
        w = World(routers=HOME)
        w.boot(phone=[(5 * 60, "Elsewhere", "whatever1")])
        w.boot(phone=[(w.t + HOUR, "HomeNet", "right-password")])
        self.assertIn(("failed", "Elsewhere", "not_found"), w.log)
        self.assertNotIn("Elsewhere", w.saved)

    def test_a_failed_join_puts_back_the_profile_it_replaced(self):
        # The setup site's password worked until the router's was changed;
        # a typo on the phone must not lose the one that was there.
        w = World(routers=HOME)
        w.run(cfg())
        before = w.saved["HomeNet"]
        w.routers["HomeNet"] = "changed-password"
        self.assertEqual(w.boot(cfg(), phone=[(w.t + 5 * 60, "HomeNet", "typo-password")]), "restart")
        self.assertEqual(w.boot(cfg(), phone=[(w.t + 5 * 60, "HomeNet", "changed-password")]), "restart")
        self.assertIn(("forget", "HomeNet"), w.log)
        self.assertIn(("failed", "HomeNet", "password"), w.log)
        self.assertEqual(w.run(cfg()), 0)
        self.assertEqual(w.saved["HomeNet"][1], "changed-password")
        self.assertNotEqual(w.saved["HomeNet"], before)

    def test_the_replaced_profile_is_what_comes_back(self):
        w = World(routers=HOME)
        w.run(cfg())
        before = w.saved["HomeNet"]
        w.pending = {"ssid": "HomeNet", "password": "typo-password"}
        w.boot(cfg())
        self.assertEqual(w.saved["HomeNet"], before)

    def test_the_pending_choice_is_tried_once(self):
        # It holds the password; a crash mid-join must not replay it on every
        # restart of the service.
        w = World(routers=HOME)
        w.pending = {"ssid": "HomeNet", "password": "right-password"}
        orig = Fake.join
        Fake.join = lambda fake, uuid, iface: (_ for _ in ()).throw(RuntimeError("crashed"))
        try:
            with self.assertRaises(RuntimeError):
                w.boot()
        finally:
            Fake.join = orig
        self.assertIsNone(w.pending)

    def test_a_failed_join_on_a_machine_with_a_cable_still_comes_online(self):
        w = World(routers=HOME, cable_at=0)
        w.pending = {"ssid": "HomeNet", "password": "wrong-password"}
        self.assertEqual(w.boot(), 0)
        self.assertIn(("failed", "HomeNet", "password"), w.log)
        self.assertEqual(w.count("ap_up"), 0)


class Clock(unittest.TestCase):
    def test_ntp_answers_so_the_clock_is_left_alone(self):
        w = World(cable_at=3)
        w.clock_off = 3 * 86400
        w.run()
        self.assertEqual(w.count("set_clock"), 0)

    def test_blocked_ntp_takes_the_time_from_a_web_server(self):
        w = World(cable_at=3)
        w.ntp, w.clock_off = False, 3 * 86400
        started = w.t
        self.assertEqual(w.run(), 0)
        self.assertEqual([e[1] for e in w.log if e[0] == "set_clock"], [-3 * 86400])
        self.assertLessEqual(w.t - started, 3 + net.CLOCK_WAIT_S + net.TICK_S)

    def test_a_clock_already_right_isnt_touched_and_no_internet_is_survived(self):
        w = World(cable_at=3)
        w.ntp = False
        w.run()
        self.assertEqual(w.count("set_clock"), 0)
        w.clock_off, w.http_date_works = 86400, False
        self.assertEqual(w.run(), 0)
        self.assertEqual(w.count("set_clock"), 0)


class Country(unittest.TestCase):
    def test_the_time_zone_names_the_country(self):
        self.assertEqual(net.country_for_timezone("Europe/Berlin", ZONE_TAB), "DE")
        self.assertIsNone(net.country_for_timezone("Etc/UTC", ZONE_TAB))
        self.assertEqual(net.wifi_country({}, ZONE_TAB), "XZ")
        self.assertEqual(net.wifi_country({"timezone": "Mars/Base"}, ZONE_TAB), "XZ")

    def test_the_config_line_is_replaced_not_piled_up(self):
        text = "PM=0\nccode=CN\nregrev=4\n#ccode ==> a comment\n"
        once = net.with_country(text, "DE")
        self.assertEqual(once, "PM=0\n#ccode ==> a comment\nccode=DE\nregrev=0\n")
        self.assertEqual(net.with_country(once, "DE"), once)

    def test_worldwide_until_a_time_zone_is_known(self):
        w = World(cable_at=3)
        w.run()
        self.assertEqual(w.country, "XZ")

    def test_the_setup_sites_time_zone_sets_it(self):
        w = World(routers=HOME)
        w.run({**cfg(), "timezone": "Europe/Berlin"})
        self.assertEqual(w.country, "DE")

    def test_the_phones_time_zone_is_in_place_before_the_restart_to_join(self):
        w = World(routers=HOME)
        w.run(phone=[(5 * 60, "HomeNet", "right-password", "America/New_York")])
        kinds = [e[:2] for e in w.log if e[0] in ("country", "reboot")]
        self.assertEqual(kinds[-2:], [("country", "US"), ("reboot", kinds[-1][1])])


class Retry(unittest.TestCase):
    def test_router_slower_than_the_pi_after_a_power_cut(self):
        # Right password, but the router is down for the first 20 minutes and
        # nobody touches the setup network: it restarts to try again.
        w = World(routers=HOME, up=lambda s, t: t > 20 * 60)
        w.run(cfg())
        self.assertGreaterEqual(w.count("reboot"), 1)
        self.assertLess(w.t, 20 * 60 + 2 * net.RETRY_FIRST_S + 5 * BOOT_S)
        self.assertEqual(w.retry, 0)  # reset once online

    def test_retries_back_off_and_never_run_hot(self):
        w = World(routers=HOME, up=lambda s, t: False, cable_at=12 * HOUR)
        w.run(cfg(), max_boots=40)
        reboots = [e[1] for e in w.log if e[0] == "reboot"]
        gaps = [b - a for a, b in zip(reboots, reboots[1:])]
        self.assertTrue(all(b >= a for a, b in zip(gaps, gaps[1:])), gaps)
        self.assertLessEqual(max(gaps), net.RETRY_MAX_S + net.WIFI_WAIT_S + BOOT_S + 60)
        self.assertLessEqual(len(reboots), 12)

    def test_never_restarts_under_someone_using_the_setup_network(self):
        for kw in ({"clients": lambda t: True}, {"page_active": lambda t: True}):
            w = World(routers=HOME, up=lambda s, t: False, cable_at=HOUR)
            w.run(cfg(), **kw)
            self.assertEqual(w.count("reboot"), 0, kw)

    def test_no_saved_network_means_no_restarts(self):
        w = World(cable_at=5 * HOUR)
        w.run()
        self.assertEqual(w.count("reboot"), 0)


class SetupNetwork(unittest.TestCase):
    def test_cable_plugged_in_during_setup_closes_it(self):
        w = World(cable_at=15 * 60)
        self.assertEqual(w.run(), 0)
        self.assertGreaterEqual([e for e in w.log if e[0] == "ap_down"][-1][1], 15 * 60)

    def test_setup_page_is_restarted_if_it_dies(self):
        w = World(cable_at=20 * 60)
        w.run(portal_dies_at=6 * 60)
        self.assertGreaterEqual(w.count("portal"), 2)

    def test_the_sorter_ui_steps_aside_for_the_setup_page_and_comes_back(self):
        w = World(ui_running=True, cable_at=10 * 60)
        self.assertEqual(w.run(), 0)
        kinds = [e[0] for e in w.log]
        self.assertLess(kinds.index("ui_stop"), kinds.index("portal"))
        self.assertEqual(w.log[-1][:2], ("ui_start", ("sorter-ui-dev.service",)))

    def test_no_setup_network_no_ui_changes(self):
        w = World(cable_at=3, ui_running=True)
        w.run()
        self.assertEqual(w.count("ui_stop"), 0)

    def test_no_wifi_hardware_waits_for_a_cable(self):
        w = World(iface=None, cable_at=30 * 60)
        self.assertEqual(w.run(), 0)
        self.assertEqual(w.count("ap_up"), 0)


class Announce(unittest.TestCase):
    def world(self, **kw):
        w = World(routers=HOME, **kw)
        w.run(cfg())
        w.announce = {"rendezvous_id": "r" * 22, "hive_url": "https://hive.example"}
        return w

    def test_gives_the_address_and_the_network_once_the_page_has_a_key(self):
        w = self.world()
        w.hive["pubkey"] = "key-1"
        w.run(cfg())
        self.assertEqual([e[:3] for e in w.log if e[0] == "announced"], [("announced", "key-1", "HomeNet")])
        self.assertIsNone(w.announce)

    def test_sends_again_when_the_page_is_reloaded(self):
        w = self.world()
        w.hive["pubkey"] = "key-1"
        orig = Fake.sleep

        def sleep(fake, s):
            orig(fake, s)
            if fake.w.count("announced") == 1:
                fake.w.hive["pubkey"] = "key-2"  # a reload makes a new key pair
        Fake.sleep = sleep
        try:
            w.run(cfg())
        finally:
            Fake.sleep = orig
        self.assertEqual([e[1] for e in w.log if e[0] == "announced"], ["key-1", "key-2"])

    def test_sends_again_when_the_name_changes(self):
        # First boot applies the name from the setup page, or avahi renames
        # the machine because another one already has it.
        w = self.world()
        w.hive["pubkey"] = "key-1"
        orig = Fake.sleep

        def sleep(fake, s):
            orig(fake, s)
            if fake.w.count("announced") == 1:
                fake.w.mdns = "sorter-2.local"
        Fake.sleep = sleep
        try:
            w.run(cfg())
        finally:
            Fake.sleep = orig
        self.assertEqual(w.count("announced"), 2)

    def test_sends_again_after_hive_forgets(self):
        w = self.world()
        w.hive["pubkey"] = "key-1"
        orig = Fake.sleep

        def sleep(fake, s):
            orig(fake, s)
            if fake.w.count("announced") == 1:
                fake.w.hive["sealed_to"] = None  # Hive restarted; the page re-posted its key
        Fake.sleep = sleep
        try:
            w.run(cfg())
        finally:
            Fake.sleep = orig
        self.assertEqual([e[1] for e in w.log if e[0] == "announced"], ["key-1", "key-1"])

    def test_gives_up_when_the_window_closes(self):
        w = self.world()
        opened = w.t
        w.run(cfg())  # the page never opened
        self.assertEqual(w.count("announced"), 0)
        closed = [e[1] for e in w.log if e[0] == "announce_closed"][-1]
        self.assertLessEqual(closed - opened, net.ANNOUNCE_WINDOW_S + BOOT_S + net.ANNOUNCE_EVERY_S)
        self.assertIsNone(w.announce)

    def test_an_unreachable_hive_does_not_stop_it(self):
        import urllib.error
        w = self.world()
        w.hive = urllib.error.URLError("Forbidden")
        self.assertEqual(w.run(cfg()), 0)
        self.assertIsNone(w.announce)


class Keyfile(unittest.TestCase):
    def test_passwords_keep_backslashes_and_edge_spaces(self):
        self.assertEqual(net.keyfile_value("a\\b"), "a\\\\b")
        self.assertEqual(net.keyfile_value(" pad "), "\\spad\\s")
        self.assertEqual(net.keyfile_value("tab\there"), "tab\\there")

    def test_the_ssid_is_written_as_bytes(self):
        text = net.nm_keyfile("Café/Net", "password1", "u")
        self.assertIn("ssid=67;97;102;195;169;47;78;101;116;\n", text)

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
        self.assertEqual(net.join_failure_reason("Connection activation failed: Secrets were required, but not provided"), "password")
        self.assertEqual(net.join_failure_reason("Connection activation failed: The Wi-Fi network could not be found"), "not_found")
        self.assertEqual(net.join_failure_reason("IP configuration could not be reserved (no available address, timeout, etc.)"), "no_address")
        self.assertEqual(net.join_failure_reason("Timeout expired (90 seconds)"), "other")


class Nmcli(unittest.TestCase):
    def test_terse_fields_undo_both_escapes(self):
        self.assertEqual(net.nmcli_fields(r"a\:b\\c:d::e"), ["a:b\\c", "d", "", "e"])

    def test_the_scan_keeps_names_exact_and_drops_hidden_and_setup_networks(self):
        scan = "Home\\:Net:80:WPA2\n Edge :60:WPA2 802.1X\n:50:WPA2\nSorterOS-Setup-ABC:90:\nHome\\:Net:30:WPA2\n"
        self.assertEqual(net.parse_scan(scan), [
            {"ssid": "Home:Net", "signal": 80, "security": "WPA2"},
            {"ssid": " Edge ", "signal": 60, "security": "WPA2 802.1X"},
        ])


class Config(unittest.TestCase):
    def test_placeholder_padding_is_cut_before_parsing(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            start = "# __SORTEROS_CFG" + "_START__"
            end = "# __SORTEROS_CFG" + "_END__"
            # what the setup site leaves: its text right after the start marker,
            # newline padding, then the end marker
            p.write_text(start + '# written by sorteros-setup\nhostname = "bin-3"\n\n[wifi]\nssid = "HomeNet"\npassword = "pw12345678"\n' + "\n" * 500 + end + "\n")
            c = net.read_config(p)
        self.assertEqual(net.wifi_from_config(c), ("HomeNet", "pw12345678"))
        self.assertEqual(c["hostname"], "bin-3")

    def test_untouched_placeholder_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text("# __SORTEROS_CFG" + "_START__\n" + "\n" * 100 + "# __SORTEROS_CFG" + "_END__\n")
            self.assertEqual(net.read_config(p), {})


if __name__ == "__main__":
    unittest.main()
