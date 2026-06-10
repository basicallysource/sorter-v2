from __future__ import annotations

import numpy as np

from vision.picture_calibration import (
    LUMA_TARGET,
    LUMA_TOLERANCE,
    WB_TOLERANCE,
    calibrate_picture,
    measure_roi,
)


class FakeCamera:
    """Simulates a UVC camera: luma responds linearly to exposure+gain, the
    R/B balance responds to white_balance_temperature around 4600K."""

    def __init__(self, *, luma_per_exposure: float = 0.05, neutral_temp: float = 4600.0):
        self.settings: dict = {"exposure_time_absolute": 500, "gain": 0, "white_balance_temperature": 5800}
        self.luma_per_exposure = luma_per_exposure
        self.neutral_temp = neutral_temp
        self.applied_log: list[dict] = []

    def apply(self, settings: dict) -> dict:
        self.applied_log.append(dict(settings))
        self.settings.update(settings)
        return dict(settings)

    def frame(self) -> np.ndarray:
        luma = self.settings["exposure_time_absolute"] * self.luma_per_exposure
        luma += float(self.settings.get("gain", 0)) * 0.3
        luma = float(np.clip(luma, 2, 253))
        # Temperature above neutral renders warmer (more red).
        tilt = (float(self.settings["white_balance_temperature"]) - self.neutral_temp) / 4000.0
        r = np.clip(luma * (1 + tilt), 0, 255)
        b = np.clip(luma * (1 - tilt), 0, 255)
        frame = np.zeros((60, 80, 3), dtype=np.uint8)
        frame[..., 0] = int(b)
        frame[..., 1] = int(luma)
        frame[..., 2] = int(r)
        return frame


CONTROLS = [
    {"key": "auto_exposure", "kind": "bool", "min": 0, "max": 1, "value": True},
    {"key": "white_balance_automatic", "kind": "bool", "min": 0, "max": 1, "value": True},
    {"key": "exposure_time_absolute", "kind": "int", "min": 10, "max": 5000, "step": 1, "value": 500},
    {"key": "gain", "kind": "int", "min": 0, "max": 100, "step": 1, "value": 0},
    {"key": "white_balance_temperature", "kind": "int", "min": 2800, "max": 6500, "step": 10, "value": 5800},
]


def _run(camera: FakeCamera, controls=CONTROLS):
    return calibrate_picture(
        controls=[dict(c) for c in controls],
        apply_settings=camera.apply,
        get_frame=camera.frame,
        settle_s=0.0,
        sleep=lambda _s: None,
    )


def test_converges_on_luma_target_and_neutral_wb() -> None:
    camera = FakeCamera()
    report = _run(camera)

    assert report.ok, report.reason
    assert abs(report.luma - LUMA_TARGET) <= LUMA_TOLERANCE * 1.5
    assert abs(report.wb_delta) <= WB_TOLERANCE
    # Automatics were locked first, before any manual writes.
    assert camera.applied_log[0] == {"auto_exposure": False, "white_balance_automatic": False}
    assert "exposure_time_absolute" in report.settings


def test_raises_gain_when_exposure_range_is_too_dark() -> None:
    # Even max exposure (5000) yields luma 5000*0.01=50 — gain must kick in.
    camera = FakeCamera(luma_per_exposure=0.01)
    report = _run(camera)

    assert report.settings.get("gain", 0) > 0
    assert report.luma > 50


def test_fails_cleanly_without_frames() -> None:
    camera = FakeCamera()
    report = calibrate_picture(
        controls=[dict(c) for c in CONTROLS],
        apply_settings=camera.apply,
        get_frame=lambda: None,
        settle_s=0.0,
        sleep=lambda _s: None,
    )

    assert not report.ok
    assert "frames" in (report.reason or "").lower()


def test_requires_manual_exposure_control() -> None:
    report = calibrate_picture(
        controls=[{"key": "brightness", "min": 0, "max": 255}],
        apply_settings=lambda s: s,
        get_frame=lambda: np.zeros((10, 10, 3), dtype=np.uint8),
        settle_s=0.0,
        sleep=lambda _s: None,
    )

    assert not report.ok
    assert "exposure" in (report.reason or "").lower()


def test_measure_roi_uses_center_crop() -> None:
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[20:80, 20:80] = 200  # center bright, border black
    luma, clip, (r, g, b) = measure_roi(frame)

    assert luma > 190  # border excluded
    assert clip == 0.0
    assert r == g == b
