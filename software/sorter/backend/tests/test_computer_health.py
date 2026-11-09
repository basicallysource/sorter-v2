"""computer_health: reading the kernel's files, and when a warning starts and ends.

fixtures/computer_health/orange-pi-5 holds the real /proc and /sys files of an
idle Orange Pi 5 (RK3588S): seven thermal zones with their trip points, five
cooling devices, three CPU clusters, a PWM fan, an SD card on ext4.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import computer_health as ch
import incidents
import telemetry_store
from runtime_stats import RuntimeStatsCollector

FIXTURE = Path(__file__).parent / "fixtures" / "computer_health" / "orange-pi-5"
DATA_PATH = "/home/orangepi/sorter-v2/software/sorter/backend"


def _sampler(root: Path = FIXTURE, **kwargs) -> ch.ComputerHealth:
    return ch.ComputerHealth(root=root, data_path=DATA_PATH, clock=lambda: True, persist=False, **kwargs)


class ReadingTests(unittest.TestCase):
    def test_zones_take_their_limits_from_the_trip_points(self) -> None:
        zones = ch.listZones(FIXTURE)
        self.assertEqual(
            [z.label for z in zones],
            ["Chip", "Fast cores, first pair", "Fast cores, second pair", "Efficient cores", "Chip center", "Graphics", "AI accelerator"],
        )
        soc = zones[0]
        self.assertEqual((soc.type, soc.slows_c, soc.hot_c, soc.critical_c), ("soc-thermal", 75.0, 85.0, 115.0))
        # Only a critical trip: too hot well under it, never above the default.
        big = zones[1]
        self.assertEqual((big.slows_c, big.hot_c, big.critical_c), (None, 85.0, 115.0))
        self.assertEqual(ch.readTemperature(FIXTURE, soc), 33.3)
        self.assertIs(ch.mainZone(zones), soc)

    def test_clusters_and_cooling_devices_are_named_for_their_cores(self) -> None:
        clusters = ch.listClusters(FIXTURE)
        self.assertEqual([c.cpus for c in clusters], [[0, 1, 2, 3], [4, 5], [6, 7]])
        cooling = ch.listCoolingDevices(FIXTURE, clusters)
        self.assertEqual(
            [(d.label, d.role, d.max_state) for d in cooling],
            [("Cores 0-3", "slows", 7), ("Cores 4-5", "slows", 10), ("Cores 6-7", "slows", 10), ("Memory", "slows", 3), ("Graphics", "slows", 7)],
        )

    def test_a_full_reading_of_an_idle_orange_pi(self) -> None:
        reading = _sampler().read(1000.0)
        self.assertEqual(reading["model"], "Orange Pi 5")
        self.assertIs(reading["slowing"]["active"], False)
        self.assertEqual(
            reading["clusters"][1], {"cpus": "4-5", "mhz": 600, "max_mhz": 2256, "limit_mhz": 2256}
        )
        memory = reading["memory"]
        self.assertEqual(memory["total_bytes"], 6064316 * 1024)
        self.assertGreater(memory["swap_total_bytes"], 0)
        self.assertTrue(0 < memory["used_pct"] < 100)
        self.assertEqual(len(reading["cpu"]["load"]), 3)
        self.assertGreater(reading["uptime_s"], 0)
        # No supply sensor on this board: not reported, not "fine".
        self.assertIsNone(reading["power"]["low"])
        self.assertEqual(reading["fans"], [{"label": "Fan", "pct": 0, "rpm": None}])
        storage = reading["storage"]
        self.assertEqual(
            (storage["read_only"], storage["file_system"], storage["errors"], storage["medium"]),
            (False, "ext4", 0, {"kind": "SD card", "name": "SD32G"}),
        )

    def test_the_kernel_slowing_a_cluster_down_shows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            shutil.copytree(FIXTURE, root)
            (root / "sys/class/thermal/cooling_device1/cur_state").write_text("3\n")
            (root / "sys/devices/system/cpu/cpufreq/policy4/scaling_max_freq").write_text("1416000\n")
            reading = _sampler(root).read(1000.0)
        self.assertIs(reading["slowing"]["active"], True)
        self.assertIn({"label": "Cores 4-5", "state": 3, "max_state": 10}, reading["slowing"]["by"])
        self.assertEqual(reading["clusters"][1]["limit_mhz"], 1416)

    def test_a_computer_without_sensors_reads_as_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reading = ch.ComputerHealth(root=Path(tmp), data_path=tmp, clock=lambda: None, persist=False).read(1.0)
        self.assertEqual(reading["temperatures"], [])
        self.assertIsNone(reading["slowing"]["active"])
        self.assertIsNone(reading["memory"])
        self.assertIsNone(reading["uptime_s"])
        self.assertIsNone(reading["power"]["low"])
        self.assertGreater(reading["storage"]["total_bytes"], 0)
        self.assertEqual(ch.assess(reading, None)["computer_disk_full"][0], False)
        self.assertNotIn("computer_hot", ch.assess(reading, None))

    def test_cpu_use_between_two_readings(self) -> None:
        before = ch.parseCpuTimes((FIXTURE / "proc/stat").read_text())
        # cpu0 busy 30 of 100 jiffies more, cpu1 idle the whole time.
        lines = []
        for line in (FIXTURE / "proc/stat").read_text().splitlines():
            fields = line.split()
            if fields and fields[0] in ("cpu", "cpu0", "cpu1"):
                values = [int(v) for v in fields[1:]]
                busy, idle = {"cpu": (30, 170), "cpu0": (30, 70), "cpu1": (0, 100)}[fields[0]]
                values[0] += busy
                values[3] += idle
                line = " ".join([fields[0], *map(str, values)])
            lines.append(line)
        total, cores = ch.cpuUse(before, ch.parseCpuTimes("\n".join(lines)))
        self.assertEqual(total, 15.0)
        self.assertEqual(cores[:2], [30.0, 0.0])

    def test_names_and_paths(self) -> None:
        self.assertEqual(ch.cpuRange([0, 1, 2, 3, 6]), "0-3, 6")
        self.assertEqual(ch.diskOf("mmcblk1p1"), "mmcblk1")
        self.assertEqual(ch.diskOf("nvme0n1p2"), "nvme0n1")
        self.assertEqual(ch.diskOf("sda1"), "sda")
        mounts = ch.parseMounts((FIXTURE / "proc/mounts").read_text())
        self.assertEqual(ch.mountOf(mounts, DATA_PATH)[1], "/")
        self.assertEqual(ch.mountOf(mounts, "/var/log/journal")[0], "/dev/zram1")
        self.assertEqual(ch.mountOf(mounts, "/var/logs")[1], "/")


class EpisodeTests(unittest.TestCase):
    def test_it_starts_after_holding_bad_and_ends_after_holding_good(self) -> None:
        episode = ch.Episode(start_after_s=10, end_after_s=60)
        self.assertIsNone(episode.update(0, bad=True, good=False))
        self.assertIsNone(episode.update(5, bad=True, good=False))
        self.assertEqual(episode.update(10, bad=True, good=False), "started")
        self.assertIsNone(episode.update(15, bad=True, good=False))
        self.assertIsNone(episode.update(20, bad=False, good=True))
        # Between the thresholds: the good stretch starts over.
        self.assertIsNone(episode.update(70, bad=False, good=False))
        self.assertIsNone(episode.update(75, bad=False, good=True))
        self.assertIsNone(episode.update(130, bad=False, good=True))
        self.assertEqual(episode.update(135, bad=False, good=True), "ended")
        self.assertFalse(episode.active)

    def test_a_short_spike_does_not_start_it(self) -> None:
        episode = ch.Episode(start_after_s=10)
        episode.update(0, bad=True, good=False)
        episode.update(5, bad=False, good=False)
        self.assertIsNone(episode.update(10, bad=True, good=False))
        self.assertFalse(episode.active)


class AssessTests(unittest.TestCase):
    def _reading(self, temp_c: float = 40.0, free_gb: float = 20.0, available_pct: float = 50.0, low: bool | None = None) -> dict:
        total = 32 * 10 ** 9
        return {
            "temperatures": [{"label": "Chip", "temp_c": temp_c, "hot_c": 85.0}],
            "storage": {"free_bytes": int(free_gb * 10 ** 9), "total_bytes": total, "read_only": False, "medium": {"kind": "SD card"}},
            "memory": {"total_bytes": 8 * 10 ** 9, "available_bytes": int(available_pct / 100 * 8 * 10 ** 9)},
            "power": {"low": low},
        }

    def test_hot_has_a_band_between_raising_and_clearing(self) -> None:
        self.assertEqual(ch.assess(self._reading(85.0), None)["computer_hot"][:2], (True, False))
        self.assertEqual(ch.assess(self._reading(82.0), None)["computer_hot"][:2], (False, False))
        self.assertEqual(ch.assess(self._reading(80.0), None)["computer_hot"][:2], (False, True))

    def test_slowed_down_most_of_the_time_is_too_hot_even_under_the_limit(self) -> None:
        bad, good, fields = ch.assess(self._reading(78.0), 0.6)["computer_hot"]
        self.assertEqual((bad, good), (True, False))
        self.assertEqual(fields["detail"], "The computer is at 78 °C and is slowing itself down to cool off.")
        self.assertEqual(ch.assess(self._reading(78.0), 0.3)["computer_hot"][:2], (False, False))

    def test_storage_memory_and_supply(self) -> None:
        bad, good, fields = ch.assess(self._reading(free_gb=1.0), None)["computer_disk_full"]
        self.assertEqual((bad, good), (True, False))
        self.assertEqual(fields["detail"], "Only 1.0 GB of 32.0 GB is free on the SD card.")
        self.assertEqual(ch.assess(self._reading(free_gb=2.5), None)["computer_disk_full"][:2], (False, False))
        self.assertEqual(ch.assess(self._reading(free_gb=4.0), None)["computer_disk_full"][:2], (False, True))
        self.assertEqual(ch.assess(self._reading(available_pct=3), None)["computer_memory_low"][:2], (True, False))
        self.assertEqual(ch.assess(self._reading(available_pct=7), None)["computer_memory_low"][:2], (False, False))
        self.assertEqual(ch.assess(self._reading(low=True), None)["computer_power_low"][:2], (True, False))
        self.assertNotIn("computer_power_low", ch.assess(self._reading(low=None), None))


class WarningTests(unittest.TestCase):
    """A hot computer raises one warning on the dashboard, beside any incident,
    without holding the machine, and clears it once it has cooled."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {"LOCAL_STATE_DB_PATH": os.path.join(tmp.name, "local_state.sqlite")})
        env.start()
        self.addCleanup(env.stop)
        handling = patch.object(incidents, "handling", lambda kind: incidents.MANUAL)
        handling.start()
        self.addCleanup(handling.stop)
        self.root = Path(tmp.name) / "root"
        shutil.copytree(FIXTURE, self.root)
        self.stats = RuntimeStatsCollector()
        self.gc = SimpleNamespace(runtime_stats=self.stats, logger=None)

    def _heat(self, millidegrees: int) -> None:
        (self.root / "sys/class/thermal/thermal_zone0/temp").write_text(f"{millidegrees}\n")

    def test_hot_warning_is_raised_once_and_cleared_after_cooling(self) -> None:
        sampler = ch.ComputerHealth(self.gc, root=self.root, data_path=DATA_PATH, clock=lambda: True, persist=False)
        self.stats.setActiveIncident({"kind": "exit_stuck", "subject": "C4"})
        self._heat(87000)
        sampler.tick(0.0)
        self.assertEqual(self.stats.warnings(), [])
        sampler.tick(10.0)
        cards = self.stats.snapshot(live=True)["warning_cards"]
        self.assertEqual([c["kind"] for c in cards], ["computer_hot"])
        self.assertEqual(cards[0]["todo"].split(".")[0], "The computer is at 87 °C, at or past the 85 °C it should stay under")
        self.assertEqual(cards[0]["link"], {"href": "/settings/computer", "label": "Computer health"})
        self.assertEqual(cards[0]["actions"], [])
        # The incident that holds the machine is untouched.
        self.assertEqual(self.stats.activeIncident()["kind"], "exit_stuck")
        sampler.tick(15.0)
        self.assertEqual(len(self.stats.warnings()), 1)
        self._heat(79000)
        sampler.tick(20.0)
        sampler.tick(75.0)
        self.assertEqual(len(self.stats.warnings()), 1)
        sampler.tick(80.0)
        self.assertEqual(self.stats.warnings(), [])
        import incident_records

        rows = incident_records.listIncidents(limit=10)["items"]
        self.assertEqual(
            sorted((r["kind"], r["status"]) for r in rows), [("computer_hot", "resolved"), ("exit_stuck", "active")]
        )
        held = incident_records.listIncidents(limit=10, exclude_kinds=("computer_hot",))
        self.assertEqual(held["total"], 1)


class HistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {"LOCAL_STATE_DB_PATH": os.path.join(tmp.name, "local_state.sqlite")})
        env.start()
        self.addCleanup(env.stop)

    def test_minutes_are_written_as_a_window_and_read_back_after_a_restart(self) -> None:
        sampler = ch.ComputerHealth(root=FIXTURE, data_path=DATA_PATH, clock=lambda: True)
        start = 1_800_000_000.0
        for i in range(30):
            sampler.tick(start + i * ch.SAMPLE_S)
        sampler.shutdown(start + 150)
        records = telemetry_store.listKind(ch.KIND, start - 1)
        self.assertEqual(len(records), 1)
        minutes = records[0]["data"]["minutes"]
        self.assertEqual([m[0] for m in minutes], [start - 0, start + 60, start + 120])
        self.assertEqual(minutes[0][1], 33.3)  # the hottest zone
        self.assertEqual(minutes[0][2], 0.0)

        again = ch.ComputerHealth(root=FIXTURE, data_path=DATA_PATH, clock=lambda: True)
        with patch.object(ch.time, "time", lambda: start + 200):
            again.seed(start + 200)
            history = again.history(1)
        self.assertEqual([p["t"] for p in history], [start, start + 60, start + 120])
        self.assertEqual(history[0]["slowed"], 0.0)


if __name__ == "__main__":
    unittest.main()
