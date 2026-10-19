import os
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import fleet_telemetry
import telemetry_store
import upload_stats
from hardware_settings.motors import MOTORS
from server import hive_sync

DRV_STANDSTILL = 1 << 31
DRV_OTPW = 1 << 0


class _FakeStepper:
    """A TMC2209 that answers register reads from a script."""

    def __init__(self, drv: int, sg: int = 300, tstep: int = 115, cs: int = 16) -> None:
        self.last_commanded_at: float | None = None
        self.running_at_speed = False
        self.drv = drv | (cs << 16)
        self.sg = sg
        self.tstep = tstep
        self.reads: list[int] = []

    def read_driver_register(self, address: int) -> int:
        self.reads.append(address)
        return {fleet_telemetry.REG_DRV_STATUS: self.drv, fleet_telemetry.REG_SG_RESULT: self.sg,
                fleet_telemetry.REG_TSTEP: self.tstep}[address]


class _DbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._old_db = os.environ.get("LOCAL_STATE_DB_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["LOCAL_STATE_DB_PATH"] = os.path.join(self._tmpdir.name, "state.sqlite")
        with upload_stats._lock:
            upload_stats._pending.clear()  # counts other tests left unflushed
        self._settings = patch.object(fleet_telemetry, "stepperSettings", lambda motor: {"sgthrs": 55, "irun": 16})
        self._settings.start()

    def tearDown(self) -> None:
        self._settings.stop()
        if self._old_db is None:
            os.environ.pop("LOCAL_STATE_DB_PATH", None)
        else:
            os.environ["LOCAL_STATE_DB_PATH"] = self._old_db
        self._tmpdir.cleanup()


def _irl(**steppers: _FakeStepper) -> SimpleNamespace:
    by_name = {motor.name: motor for motor in MOTORS}
    return SimpleNamespace(**{by_name[name].attr: stepper for name, stepper in steppers.items()})


class StepperLoadTests(_DbTestCase):
    def test_only_steppers_that_were_commanded_are_read(self) -> None:
        chute = _FakeStepper(drv=0)
        idle = _FakeStepper(drv=0)
        probe = fleet_telemetry.StepperLoadProbe()
        irl = _irl(chute=chute, carousel=idle)
        probe.sample(irl, now=100.0)
        self.assertEqual([], chute.reads + idle.reads)
        chute.last_commanded_at = 99.5
        probe.sample(irl, now=100.0)
        self.assertEqual(
            [fleet_telemetry.REG_DRV_STATUS, fleet_telemetry.REG_SG_RESULT, fleet_telemetry.REG_TSTEP], chute.reads
        )
        self.assertEqual([], idle.reads)
        probe.sample(irl, now=103.0)  # its move is long over
        self.assertEqual(3, len(chute.reads))

    def test_a_standstill_costs_one_read_and_moving_readings_are_binned_by_speed(self) -> None:
        stepper = _FakeStepper(drv=DRV_STANDSTILL | DRV_OTPW)
        stepper.running_at_speed = True
        probe = fleet_telemetry.StepperLoadProbe()
        irl = _irl(chute=stepper)
        probe.sample(irl, now=1.0)
        self.assertEqual([fleet_telemetry.REG_DRV_STATUS], stepper.reads)
        stepper.drv &= ~DRV_STANDSTILL
        for sg in (300, 310, 20):
            stepper.sg = sg
            probe.sample(irl, now=2.0)
        data = probe.summary()
        [chute] = data["steppers"]["chute"]
        self.assertEqual((4, 1, 0), (chute["samples"], chute["standstill"], chute["stalls"]))
        self.assertEqual({"otpw": 4}, chute["flags"])
        [band] = chute["bands"]
        self.assertEqual([91, 128], band["tstep"])  # half an octave around 115
        self.assertEqual(3, band["n"])
        # The histogram from its first non-empty bin (SG 0-31) to its last (288-319).
        self.assertEqual(0, band["sg_from"])
        self.assertEqual([1, 0, 0, 0, 0, 0, 0, 0, 0, 2], band["sg"])
        self.assertEqual((20, 310, 630), (band["sg_min"], band["sg_max"], band["sg_sum"]))
        self.assertEqual({"sgthrs": 55, "irun": 16}, chute["settings"])
        self.assertIsNone(probe.summary())  # it starts afresh

    def test_settings_changed_while_sorting_start_a_new_entry_in_the_same_window(self) -> None:
        stepper = _FakeStepper(drv=0, sg=200)
        stepper.running_at_speed = True
        probe = fleet_telemetry.StepperLoadProbe()
        irl = _irl(chute=stepper)
        probe.sample(irl, now=1.0)
        with patch.object(fleet_telemetry, "stepperSettings", lambda motor: {"sgthrs": 30, "irun": 16}):
            probe.sample(irl, now=1.0 + fleet_telemetry.STEPPER_SETTINGS_CHECK_S)
            probe.sample(irl, now=2.0 + fleet_telemetry.STEPPER_SETTINGS_CHECK_S)
        entries = probe.summary()["steppers"]["chute"]
        self.assertEqual([(55, 1), (30, 2)], [(e["settings"]["sgthrs"], e["samples"]) for e in entries])

    def test_a_stall_carries_the_last_readings(self) -> None:
        stepper = _FakeStepper(drv=0, sg=12)
        stepper.running_at_speed = True
        probe = fleet_telemetry.StepperLoadProbe()
        probe.sample(_irl(chute=stepper), now=10.0)
        event = probe.noteStall("chute_stepper", now=10.5)
        self.assertEqual("chute", event["stepper"])
        self.assertEqual([[-0.5, 12, 115, 16, False]], event["recent"])
        self.assertEqual(1, probe.summary()["steppers"]["chute"][0]["stalls"])


class WindowTests(_DbTestCase):
    def _service(self, running: dict) -> fleet_telemetry.FleetTelemetry:
        gc = SimpleNamespace(runtime_stats=SimpleNamespace(is_running=False))
        service = fleet_telemetry.FleetTelemetry(gc)
        service._specs_next_at = float("inf")
        running["gc"] = gc
        return service

    def test_a_window_is_written_when_sorting_stops(self) -> None:
        state: dict = {}
        service = self._service(state)
        stepper = _FakeStepper(drv=0)
        stepper.running_at_speed = True
        with patch.object(fleet_telemetry, "_activeIrl", lambda: _irl(chute=stepper)), \
                patch.object(fleet_telemetry.CameraReadingsProbe, "sample", lambda self, irl, now: None):
            service.tick(0.0, 1000.0)
            self.assertEqual([], telemetry_store.listAfter(0, 10))
            state["gc"].runtime_stats.is_running = True
            for i in range(8):
                service.tick(1.0 + i * fleet_telemetry.TICK_S, 1001.0 + i * fleet_telemetry.TICK_S)
            state["gc"].runtime_stats.is_running = False
            service.tick(4.0, 1004.0)
        [record] = telemetry_store.listAfter(0, 10)
        self.assertEqual(("stepper_load", "window"), (record["kind"], record["form"]))
        self.assertEqual((1001.0, 1004.0), (record["started_at"], record["ended_at"]))
        self.assertEqual(8, record["data"]["steppers"]["chute"][0]["samples"])
        self.assertEqual(2, record["schema"])
        self.assertEqual(1.8, record["data"]["sorting_s"])

    def test_specs_are_written_once_until_they_change(self) -> None:
        service = self._service({})
        specs = {"schema_version": 3, "controller_boards": {"a": {}}, "captured_at": "t1", "steppers": {}}
        with patch("machine_specs.buildMachineSpecs", lambda: dict(specs)):
            service.checkSpecs(0.0)
            specs["captured_at"] = "t2"
            service.checkSpecs(400.0)
            specs["steppers"] = {"chute": {"sgthrs": 60}}
            service.checkSpecs(800.0)
        records = telemetry_store.listAfter(0, 10)
        self.assertEqual(["machine_specs", "machine_specs"], [r["kind"] for r in records])
        self.assertEqual({"chute": {"sgthrs": 60}}, records[1]["data"]["steppers"])

    def test_specs_wait_for_the_boards_a_while(self) -> None:
        service = self._service({})
        with patch("machine_specs.buildMachineSpecs", lambda: {"controller_boards": {}}):
            service.checkSpecs(service._started + 10)
            self.assertEqual([], telemetry_store.listAfter(0, 10))
            service.checkSpecs(service._started + fleet_telemetry.SPECS_WAIT_S + 1)
        self.assertEqual(1, len(telemetry_store.listAfter(0, 10)))


class CameraControlsTests(unittest.TestCase):
    LISTING = """
User Controls

                     brightness 0x00980900 (int)    : min=-64 max=64 step=1 default=0 value=-3
        white_balance_automatic 0x0098090c (bool)   : default=1 value=1
      white_balance_temperature 0x0098091a (int)    : min=2800 max=6500 step=10 default=4600 value=3370 flags=inactive

Camera Controls

                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 value=3 (Aperture Priority Mode)
         exposure_time_absolute 0x009a0902 (int)    : min=0 max=10000 step=1 default=166 value=400 flags=inactive
"""

    def test_every_control_with_its_value_and_whether_auto_drives_it(self) -> None:
        from vision.camera import parse_v4l2_controls

        controls = parse_v4l2_controls(self.LISTING)
        self.assertEqual(
            {
                "brightness": {"value": -3.0, "inactive": False},
                "white_balance_automatic": {"value": 1.0, "inactive": False},
                "white_balance_temperature": {"value": 3370.0, "inactive": True},
                "auto_exposure": {"value": 3.0, "inactive": False},
                "exposure_time_absolute": {"value": 400.0, "inactive": True},
            },
            controls,
        )


class StoreAndSyncTests(_DbTestCase):
    def test_records_too_large_for_hive_are_not_kept(self) -> None:
        self.assertIsNone(telemetry_store.write("x", "event", {"blob": "x" * (70 * 1024)}, started_at=1.0))
        self.assertIsNotNone(telemetry_store.write("x", "event", {"n": 1}, started_at=1.0))

    def test_the_leg_sends_records_in_order_and_counts_them(self) -> None:
        for n in range(3):
            telemetry_store.write("stepper_load", "window", {"n": n}, started_at=float(n), ended_at=float(n + 1))
        sent: list[list[dict]] = []

        class _Client:
            last_body_bytes = 123

            def pushTelemetry(self, records):
                sent.append(records)
                return records[-1]["local_id"]

        syncer = hive_sync._TargetSyncer.__new__(hive_sync._TargetSyncer)
        syncer._id = "t"
        syncer._client = _Client()
        syncer._gate = hive_sync._ConcurrencyGate(1, 1, lambda: False)
        syncer._stop = threading.Event()
        syncer._wm = {t: 0 for t in hive_sync.DATA_TYPES}
        self.assertTrue(syncer._drainTelemetry())
        self.assertEqual([0, 1, 2], [r["data"]["n"] for r in sent[0]])
        self.assertEqual(3, syncer._wm[hive_sync.DATA_TYPE_TELEMETRY])
        self.assertFalse(syncer._drainTelemetry())
        series = upload_stats.series("t", 2)
        self.assertEqual(3, series["series"]["telemetry"]["sent"][-1])
        self.assertEqual(123, series["series"]["telemetry"]["sent_bytes"][-1])

    def test_synced_records_go_after_a_week(self) -> None:
        telemetry_store.write("a", "event", {}, started_at=1.0)
        telemetry_store.markSyncedUpTo(1, 1.0)
        now = telemetry_store.time.time()
        self.assertEqual(0, telemetry_store.prune(now))
        self.assertEqual(1, telemetry_store.prune(now + 8 * 86400.0))


class UploadStatsTests(_DbTestCase):
    def test_counts_land_in_their_hour(self) -> None:
        hour = 3600 * 1000
        upload_stats.noteSent("t", "samples", 2, 500, at=hour + 10)
        upload_stats.noteSent("t", "samples", 1, 100, at=hour + 20)
        upload_stats.noteDropped("t", "samples", 4, 900, at=hour + 30)
        upload_stats.noteWaiting("t", {"samples": 7}, at=hour + 40)
        upload_stats.noteWaiting("t", {"samples": 5}, at=hour + 50)
        upload_stats.noteBudgetWait("t", 12.5, at=hour + 60)
        upload_stats.noteSent("t", "samples", 1, 50, at=hour + 3600)
        series = upload_stats.series("t", 3, now=hour + 3601)
        samples = series["series"]["samples"]
        self.assertEqual([0, 3, 1], samples["sent"])
        self.assertEqual([0, 600, 50], samples["sent_bytes"])
        self.assertEqual([0, 4, 0], samples["dropped"])
        self.assertEqual([None, 7, None], samples["waiting"])
        self.assertEqual([0.0, 12.5, 0.0], series["budget_wait_s"])
        self.assertEqual(hour + 3600, series["last_sent_at"]["samples"])


if __name__ == "__main__":
    unittest.main()
