import unittest

import vision.camera_recovery as camera_recovery


class RecoveryLadderOrderTests(unittest.TestCase):
    def test_camera_local_rungs_come_before_any_shared_bus_rung(self) -> None:
        # The control board's serial port shares the hub with the cameras, so a
        # shared-bus rung costs motion control. Every reset that cannot do that
        # must be tried first, or a recoverable camera glitch escalates straight
        # into dropping the machine's control board.
        flags = [step.disrupts_shared_bus for step in camera_recovery.RECOVERY_LADDER]
        first_shared = flags.index(True) if True in flags else len(flags)
        self.assertNotIn(False, flags[first_shared:])
        self.assertGreater(first_shared, 0, "at least one camera-local rung must lead")

    def test_the_rungs_that_re_enumerate_the_hub_are_marked(self) -> None:
        marked = {
            step.name
            for step in camera_recovery.RECOVERY_LADDER
            if step.disrupts_shared_bus
        }
        self.assertEqual(
            marked,
            {"usb_hub_reset", "upstream_port_power_cycle", "host_controller_rebind"},
        )

    def test_settle_times_are_positive_and_non_decreasing(self) -> None:
        settles = [step.settle_s for step in camera_recovery.RECOVERY_LADDER]
        self.assertTrue(all(s > 0 for s in settles))
        self.assertEqual(settles, sorted(settles))


class LinkSpeedTests(unittest.TestCase):
    def test_full_speed_link_reads_as_degraded(self) -> None:
        # 12 Mbit/s is the OHCI companion fallback that strips the cameras' high
        # resolution modes; 480 is the high-speed link we need.
        device = _device(speed_mbps=12.0)
        self.assertTrue(camera_recovery.isLinkSpeedDegraded(device))

    def test_high_speed_and_faster_links_are_not_degraded(self) -> None:
        for speed in (480.0, 5000.0):
            self.assertFalse(camera_recovery.isLinkSpeedDegraded(_device(speed_mbps=speed)))

    def test_unknown_speed_is_not_reported_as_degraded(self) -> None:
        # Absent evidence is not evidence of a fault — never escalate on it.
        self.assertFalse(camera_recovery.isLinkSpeedDegraded(_device(speed_mbps=None)))
        self.assertFalse(camera_recovery.isLinkSpeedDegraded(None))


def _device(*, speed_mbps: float | None) -> camera_recovery.CameraUsbDevice:
    return camera_recovery.CameraUsbDevice(
        sysfs_path="/sys/bus/usb/devices/5-1.1",
        devpath="1.1",
        busnum=5,
        devnum=3,
        speed_mbps=speed_mbps,
        parent_sysfs_path="/sys/bus/usb/devices/5-1",
        port_sysfs_path=None,
        parent_port_sysfs_path=None,
        controller_name="5101c00.usb",
        controller_driver="ohci-platform",
    )


if __name__ == "__main__":
    unittest.main()
