import unittest
from types import SimpleNamespace

from subsystems.distribution.chute import Chute


class _Logger:
    def info(self, *a, **k) -> None: ...
    def warning(self, *a, **k) -> None: ...
    def error(self, *a, **k) -> None: ...


def _mkChute(num_sections=6, section_width_deg=51.75, first_section_offset_deg=8.25):
    gc = SimpleNamespace(logger=_Logger(), disable_chute=False)
    layout = SimpleNamespace(layers=[])
    return Chute(
        gc,
        stepper=SimpleNamespace(),
        home_pin=SimpleNamespace(value=False),
        layout=layout,
        num_sections=num_sections,
        section_width_deg=section_width_deg,
        first_section_offset_deg=first_section_offset_deg,
    )


class ChuteAimingGeometryTests(unittest.TestCase):
    def test_midpoint_placement(self) -> None:
        # K=3, W=30, theta0=0 -> slots of 10, centers at 5, 15, 25.
        chute = _mkChute(num_sections=6, section_width_deg=30.0, first_section_offset_deg=0.0)
        self.assertAlmostEqual(chute.angleForVirtualBin(0, 0, 3, unclamped=True), 5.0)
        self.assertAlmostEqual(chute.angleForVirtualBin(0, 1, 3, unclamped=True), 15.0)
        self.assertAlmostEqual(chute.angleForVirtualBin(0, 2, 3, unclamped=True), 25.0)

    def test_single_bin_centers_in_section(self) -> None:
        chute = _mkChute(num_sections=6, section_width_deg=30.0, first_section_offset_deg=0.0)
        # One bin should sit at the middle of the usable arc: W/2 = 15.
        self.assertAlmostEqual(chute.angleForVirtualBin(0, 0, 1, unclamped=True), 15.0)

    def test_section_pitch_independent_of_bin_count(self) -> None:
        chute = _mkChute(num_sections=6, section_width_deg=30.0, first_section_offset_deg=4.0)
        a0 = chute.angleForVirtualBin(0, 0, 3, unclamped=True)
        a1 = chute.angleForVirtualBin(1, 0, 3, unclamped=True)
        self.assertAlmostEqual(a1 - a0, 60.0)  # 360/6

    def test_derive_round_trip(self) -> None:
        # Forward: a known geometry produces first/last bin angles for K bins.
        true_W, true_theta0, K, N = 42.0, 7.5, 4, 6
        chute = _mkChute(num_sections=N, section_width_deg=true_W, first_section_offset_deg=true_theta0)
        a = chute.angleForVirtualBin(0, 0, K, unclamped=True)
        last = chute.angleForVirtualBin(0, K - 1, K, unclamped=True)

        # Inverse (mirrors derive_chute_aiming_config): recover W and theta0.
        span = last - a
        slot = span / (K - 1)
        section_width = slot * K
        theta0 = a - 0.5 * slot
        self.assertAlmostEqual(section_width, true_W)
        self.assertAlmostEqual(theta0, true_theta0)


if __name__ == "__main__":
    unittest.main()
