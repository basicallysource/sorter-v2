from __future__ import annotations

import numpy as np

from vision.picture_calibration import (
    LUMA_ACCEPT_TOLERANCE,
    LUMA_TARGET,
    WB_TOLERANCE,
    calibrate_picture,
    measure_roi,
)


class FakeCamera:
    """Simulates a UVC camera with a fake clock.

    luma responds to exposure (optionally capped by the frame interval, like
    real 30fps UVC), gain and gamma; R/B balance responds to the white
    balance temperature around ``neutral_temp``. Frames carry timestamps and
    only become "fresh" after the settings change, like the real capture.
    """

    def __init__(
        self,
        *,
        luma_per_exposure: float = 0.8,
        exposure_cap: float | None = None,
        neutral_temp: float = 4600.0,
        with_gain: bool = True,
        with_gamma: bool = False,
        gamma_luma_boost: float = 0.3,
    ):
        self.settings: dict = {
            "exposure": 148,
            "gain": 0,
            "gamma": 100,
            "white_balance_temperature": 5800,
        }
        self.luma_per_exposure = luma_per_exposure
        self.exposure_cap = exposure_cap
        self.neutral_temp = neutral_temp
        self.with_gain = with_gain
        self.with_gamma = with_gamma
        self.gamma_luma_boost = gamma_luma_boost
        self.clock = 100.0
        self.applied_log: list[dict] = []

    def apply(self, settings: dict) -> dict:
        self.applied_log.append(dict(settings))
        self.settings.update(settings)
        return dict(settings)

    def sleep(self, seconds: float) -> None:
        self.clock += max(0.01, seconds)

    def now(self) -> float:
        return self.clock

    def frame(self):
        self.clock += 0.05  # frames keep arriving
        exposure = float(self.settings["exposure"])
        if self.exposure_cap is not None:
            exposure = min(exposure, self.exposure_cap)
        luma = exposure * self.luma_per_exposure
        if self.with_gain:
            luma += float(self.settings.get("gain", 0)) * 0.6
        if self.with_gamma:
            luma += (float(self.settings.get("gamma", 100)) - 100.0) * self.gamma_luma_boost
        luma = float(np.clip(luma, 2, 253))
        tilt = (float(self.settings["white_balance_temperature"]) - self.neutral_temp) / 4000.0
        r = np.clip(luma * (1 + tilt), 0, 255)
        b = np.clip(luma * (1 - tilt), 0, 255)
        frame = np.zeros((60, 80, 3), dtype=np.uint8)
        frame[..., 0] = int(b)
        frame[..., 1] = int(luma)
        frame[..., 2] = int(r)
        return frame, self.clock


def _controls(*, with_gain: bool = True, with_gamma: bool = False) -> list[dict]:
    controls = [
        {"key": "auto_exposure", "kind": "menu", "min": 0, "max": 3, "value": 3},
        {"key": "auto_white_balance", "kind": "boolean", "value": True},
        {"key": "exposure", "kind": "number", "min": 50, "max": 10000, "step": 1, "value": 148},
        {"key": "white_balance_temperature", "kind": "number", "min": 2800, "max": 6500, "step": 10, "value": 5800},
    ]
    if with_gain:
        controls.append({"key": "gain", "kind": "number", "min": 0, "max": 100, "step": 1, "value": 0})
    if with_gamma:
        controls.append({"key": "gamma", "kind": "number", "min": 100, "max": 500, "step": 1, "value": 100})
    return controls


def _run(camera: FakeCamera, controls: list[dict]):
    return calibrate_picture(
        controls=controls,
        apply_settings=camera.apply,
        get_frame=camera.frame,
        sleep=camera.sleep,
        now=camera.now,
    )


def test_converges_on_luma_target_and_neutral_wb() -> None:
    camera = FakeCamera()
    report = _run(camera, _controls())

    assert report.ok, report.reason
    assert abs(report.luma - LUMA_TARGET) <= LUMA_ACCEPT_TOLERANCE
    assert abs(report.wb_delta) <= WB_TOLERANCE
    assert camera.applied_log[0] == {"auto_exposure": False, "auto_white_balance": False}
    assert "exposure" in report.settings


def test_detects_frame_interval_exposure_cap_and_uses_gain() -> None:
    # Exposure stops responding above 330 (30fps cap) — luma 330*0.2=66.
    camera = FakeCamera(luma_per_exposure=0.2, exposure_cap=330)
    report = _run(camera, _controls())

    assert report.ok, report.reason
    assert report.settings.get("gain", 0) > 0
    # The search must not have parked exposure deep in the dead range only.
    assert abs(report.luma - LUMA_TARGET) <= LUMA_ACCEPT_TOLERANCE


def test_falls_back_to_gamma_when_camera_has_no_gain() -> None:
    camera = FakeCamera(
        luma_per_exposure=0.2, exposure_cap=330, with_gain=False, with_gamma=True
    )
    report = _run(camera, _controls(with_gain=False, with_gamma=True))

    assert report.ok, report.reason
    assert report.settings.get("gamma", 100) > 100


def test_failed_run_restores_touched_controls() -> None:
    # Even all levers maxed cannot reach the target → must restore.
    camera = FakeCamera(luma_per_exposure=0.01, exposure_cap=330, with_gain=False)
    controls = _controls(with_gain=False)
    report = _run(camera, controls)

    assert not report.ok
    assert report.restored
    assert "restored" in (report.reason or "").lower() or "light" in (report.reason or "").lower()
    # Last applied settings == the originals from the control descriptors.
    assert camera.settings["exposure"] == 148
    assert camera.applied_log[-1].get("auto_exposure") == 3


def test_fails_cleanly_without_frames() -> None:
    camera = FakeCamera()
    report = calibrate_picture(
        controls=_controls(),
        apply_settings=camera.apply,
        get_frame=lambda: None,
        sleep=camera.sleep,
        now=camera.now,
    )

    assert not report.ok
    assert "frames" in (report.reason or "").lower()


def test_requires_manual_exposure_control() -> None:
    report = calibrate_picture(
        controls=[{"key": "brightness", "min": 0, "max": 255}],
        apply_settings=lambda s: s,
        get_frame=lambda: (np.zeros((10, 10, 3), dtype=np.uint8), 1.0),
        sleep=lambda _s: None,
        now=lambda: 0.0,
    )

    assert not report.ok
    assert "exposure" in (report.reason or "").lower()


def test_measure_roi_uses_center_crop() -> None:
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[20:80, 20:80] = 200
    luma, clip, (r, g, b) = measure_roi(frame)

    assert luma > 190
    assert clip == 0.0
    assert r == g == b
