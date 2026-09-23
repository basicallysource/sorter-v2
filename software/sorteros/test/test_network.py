"""The boot-time network decisions in sorteros-network, against a simulated
clock and a fake NetworkManager. Run: python3 -m unittest test/test_network.py"""

import importlib.util
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "build/overlay/usr/local/sbin/sorteros-network.py"
_spec = importlib.util.spec_from_file_location("sorteros_network", _SRC)
net = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(net)

HOUR = 3600.0


class Fake:
    """NetworkManager as far as sorteros-network can see it. A saved network
    joins on its own (NM autoconnect) whenever the radio isn't broadcasting
    the setup network and `wifi_ok(name, t)` says it would work at time t."""

    def __init__(self, *, iface="wlan0", cable_at=None, saved=(), wifi_ok=lambda name, t: False,
                 phone_submits_at=None, phone_password_ok=True, clients=lambda t: False,
                 page_active=lambda t: False, portal_dies_at=None, imported=""):
        self.t = 0.0
        self.iface, self.cable_at, self.saved, self.wifi_ok = iface, cable_at, list(saved), wifi_ok
        self.phone_submits_at, self.phone_password_ok = phone_submits_at, phone_password_ok
        self.clients, self.page_active, self.portal_dies_at = clients, page_active, portal_dies_at
        self._imported = imported
        self.ap = False
        self.portal = False
        self.portal_done = False
        self.joined = None
        self.log = []

    # clock
    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s
        if self.portal and self.portal_dies_at is not None and self.t >= self.portal_dies_at:
            self.portal, self.portal_dies_at = False, None
        if self.ap and self.phone_submits_at is not None and self.t >= self.phone_submits_at:
            self.phone_submits_at = None
            self.log.append(("phone", self.t))
            if self.phone_password_ok:
                self.ap, self.joined, self.portal_done = False, "PhoneNet", True
                self.saved.append("PhoneNet")

    # network
    def wifi_iface(self):
        return self.iface

    def online(self):
        if self.cable_at is not None and self.t >= self.cable_at:
            return True
        if self.joined:
            return True
        if not self.ap and self.iface:
            for name in self.saved:
                if self.wifi_ok(name, self.t):
                    self.joined = name
                    return True
        return False

    def saved_wifi(self):
        return list(self.saved)

    def write_wifi(self, ssid, password):
        self.log.append(("write", ssid, password))
        if ssid not in self.saved:
            self.saved.append(ssid)

    def connect(self, name, iface):
        self.log.append(("connect", name, self.t))
        self.ap = False
        self.t += net.CONNECT_TIMEOUT_S if not self.wifi_ok(name, self.t) else 5
        if self.wifi_ok(name, self.t):
            self.joined = name
            return True
        return False

    def ap_up(self, iface):
        self.log.append(("ap_up", self.t))
        self.ap = True
        return "SorterOS-Setup-ABC123"

    def ap_down(self):
        self.log.append(("ap_down", self.t))
        self.ap = False

    def ap_has_clients(self, iface):
        return self.clients(self.t)

    # portal
    def start_portal(self):
        self.log.append(("portal", self.t))
        self.portal, self.portal_done = True, False

    def portal_alive(self):
        return self.portal

    def stop_portal(self):
        self.portal = False

    def portal_connected(self):
        return self.portal_done

    def portal_idle_s(self):
        return 0.0 if self.page_active(self.t) else float("inf")

    # import bookkeeping
    def imported(self):
        return self._imported

    def mark_imported(self, digest):
        self._imported = digest

    def count(self, kind):
        return sum(1 for e in self.log if e[0] == kind)


def cfg(ssid="HomeNet", password="right-password"):
    return {"wifi": {"ssid": ssid, "password": password}}


class BringUp(unittest.TestCase):
    def test_cable_means_no_setup_network(self):
        f = Fake(cable_at=3)
        self.assertEqual(net.bring_up(f, {}), 0)
        self.assertEqual(f.count("ap_up"), 0)

    def test_setup_site_wifi_is_saved_and_joined(self):
        f = Fake(wifi_ok=lambda name, t: name == "HomeNet" and t > 20)
        self.assertEqual(net.bring_up(f, cfg()), 0)
        self.assertIn(("write", "HomeNet", "right-password"), f.log)
        self.assertEqual(f.joined, "HomeNet")
        self.assertEqual(f.count("ap_up"), 0)

    def test_setup_site_wifi_is_imported_once(self):
        f = Fake(wifi_ok=lambda name, t: name == "HomeNet")
        net.bring_up(f, cfg())
        g = Fake(wifi_ok=lambda name, t: name == "HomeNet", saved=["HomeNet"], imported=f.imported())
        net.bring_up(g, cfg())
        self.assertEqual(g.count("write"), 0)

    def test_changed_setup_site_wifi_is_imported_again(self):
        f = Fake(wifi_ok=lambda name, t: True)
        net.bring_up(f, cfg(password="old-password"))
        g = Fake(wifi_ok=lambda name, t: True, saved=["HomeNet"], imported=f.imported())
        net.bring_up(g, cfg(password="new-password"))
        self.assertIn(("write", "HomeNet", "new-password"), g.log)

    def test_wrong_password_falls_back_to_the_setup_network_after_one_wait(self):
        f = Fake(phone_submits_at=10 * 60)  # HomeNet never works; the phone fixes it
        self.assertEqual(net.bring_up(f, cfg(password="wrong")), 0)
        first_ap = next(e for e in f.log if e[0] == "ap_up")
        self.assertLessEqual(first_ap[1], net.WIFI_DEVICE_WAIT_S + net.WIFI_WAIT_S + net.TICK_S)
        self.assertEqual(f.joined, "PhoneNet")

    def test_no_wifi_given_no_cable_opens_the_setup_network_after_the_wired_wait(self):
        f = Fake(phone_submits_at=5 * 60)
        self.assertEqual(net.bring_up(f, {}), 0)
        first_ap = next(e for e in f.log if e[0] == "ap_up")
        self.assertLessEqual(first_ap[1], net.WIRED_WAIT_S + net.TICK_S)

    def test_cable_plugged_in_during_setup_closes_the_setup_network(self):
        f = Fake(cable_at=15 * 60)
        self.assertEqual(net.bring_up(f, {}), 0)
        self.assertEqual(f.log[-1][0], "ap_down")
        self.assertGreaterEqual(f.t, 15 * 60)

    def test_router_slower_than_the_pi_after_a_power_cut(self):
        # Right password, but the router is down for the first 20 minutes.
        f = Fake(saved=["HomeNet"], wifi_ok=lambda name, t: name == "HomeNet" and t > 20 * 60)
        self.assertEqual(net.bring_up(f, {}), 0)
        self.assertEqual(f.joined, "HomeNet")
        self.assertLess(f.t, 20 * 60 + net.RETRY_EVERY_S + 2 * net.CONNECT_TIMEOUT_S + 60)

    def test_no_tight_loop_when_the_saved_network_never_comes_back(self):
        f = Fake(saved=["HomeNet"], cable_at=HOUR)
        net.bring_up(f, {})
        self.assertLessEqual(f.count("connect"), HOUR / net.RETRY_EVERY_S + 1)
        self.assertGreater(f.count("connect"), 3)  # it does keep trying

    def test_never_drops_the_setup_network_under_someone_using_it(self):
        f = Fake(saved=["HomeNet"], cable_at=HOUR, clients=lambda t: True)
        net.bring_up(f, {})
        self.assertEqual(f.count("connect"), 0)
        g = Fake(saved=["HomeNet"], cable_at=HOUR, page_active=lambda t: True)
        net.bring_up(g, {})
        self.assertEqual(g.count("connect"), 0)

    def test_wrong_password_on_the_phone_keeps_the_setup_network(self):
        f = Fake(phone_submits_at=5 * 60, phone_password_ok=False, cable_at=HOUR)
        self.assertEqual(net.bring_up(f, {}), 0)
        self.assertEqual(f.count("phone"), 1)
        self.assertEqual(f.count("ap_up"), 1)  # never dropped
        self.assertEqual(f.log[-1], ("ap_down", HOUR))  # closed only for the cable

    def test_setup_page_is_restarted_if_it_dies(self):
        f = Fake(portal_dies_at=6 * 60, cable_at=20 * 60)
        net.bring_up(f, {})
        self.assertGreaterEqual(f.count("portal"), 2)

    def test_no_wifi_hardware_waits_for_a_cable(self):
        f = Fake(iface=None, cable_at=30 * 60)
        self.assertEqual(net.bring_up(f, {}), 0)
        self.assertEqual(f.count("ap_up"), 0)


class Config(unittest.TestCase):
    def test_placeholder_padding_is_cut_before_parsing(self, tmp=Path("/tmp")):
        import tempfile
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
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text("# __SORTEROS_CFG" + "_START__\n" + "\n" * 100 + "# __SORTEROS_CFG" + "_END__\n")
            self.assertEqual(net.read_config(p), {})


if __name__ == "__main__":
    unittest.main()
