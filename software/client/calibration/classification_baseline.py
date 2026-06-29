"""Web-driven classification/carousel baseline capture — "the wiggle".

Rotates the carousel through a full sweep (vibrating the chute throughout) and records the
per-pixel HSV envelope + stable-pixel mask the runtime detector triggers against. Ported from
scripts/calibrate_classification_baseline.py; the capture/envelope math is unchanged, but it
runs as a cancelable background job that reports progress for the web UI instead of printing.

This machine has one classification camera ("classification") and a carousel camera.
"""

from __future__ import annotations

import glob as globmod
import os
import random
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from blob_manager import BLOB_DIR
from hardware.camera_resolver import resolve_camera_setup
from irl.config import make_camera_config
from vision.camera import CaptureThread
from vision.hsv_correction import load_hsv_correction, bgr_to_hsv_scaled
from vision.diff_configs import DEFAULT_CLASSIFICATION_DIFF_CONFIG

CLASSIFICATION_SCALE = DEFAULT_CLASSIFICATION_DIFF_CONFIG.scale

MAX_FRAMES = 64
DEGREES_PER_FRAME = -90
MOVE_SETTLE_S = 2.0
# Carousel completion is polled at this (low) rate during the move. The default blocking
# move polls every 10ms, and each poll is an MCU-bus round-trip that starves the chute
# wiggle thread on the shared bus (the wiggle stutters/jumps as the carousel stops). Polling
# slowly leaves the bus to the chute so it stays smooth and continuous.
CAROUSEL_POLL_S = 0.2
CAROUSEL_MOVE_TIMEOUT_S = 5.0

DEFAULT_CHUTE_WIGGLE_HZ = 5.0
DEFAULT_CHUTE_WIGGLE_STEPS = 40

DEFAULT_MAX_HUE_STD = 12.0
DEFAULT_MAX_SAT_STD = 15.0
DEFAULT_MAX_VAL_STD = 30.0
DEFAULT_PERCENTILE = 2.0

# Which camera roles each --camera selection captures. These are the live camera-setup
# roles (resolveCameraSetup), and also the file prefix for each camera's envelope.
CAMERA_GROUPS = {
    "classification": ["classification"],
    "carousel": ["carousel"],
    "all": ["classification", "carousel"],
}

BASELINE_DIR = BLOB_DIR / "classification_baseline"


def baseline_exists(cameras: Optional[list[str]] = None) -> bool:
    """True if the classification envelope has been captured (drives run gating)."""
    cameras = cameras or ["classification"]
    return all((BASELINE_DIR / f"{c}_baseline_h_min.png").exists() for c in cameras)


# ----- envelope / mask math (unchanged from the script) ------------------

def _circular_hue_std(sum_cos, sum_sin, n):
    C, S = sum_cos / n, sum_sin / n
    R = np.clip(np.sqrt(C * C + S * S), 1e-6, 1.0)
    return np.sqrt(-2.0 * np.log(R)) * (90.0 / np.pi)


def compute_stable_mask(h_frames, s_frames, v_frames, max_hue_std, max_sat_std, max_val_std):
    n = len(h_frames)
    shape = h_frames[0].shape
    sum_cos = np.zeros(shape, np.float64); sum_sin = np.zeros(shape, np.float64)
    sum_s = np.zeros(shape, np.float64); sum_s2 = np.zeros(shape, np.float64)
    sum_v = np.zeros(shape, np.float64); sum_v2 = np.zeros(shape, np.float64)
    for h, s, v in zip(h_frames, s_frames, v_frames):
        ang = h.astype(np.float64) * (np.pi / 90.0)
        sum_cos += np.cos(ang); sum_sin += np.sin(ang)
        sf = s.astype(np.float64); sum_s += sf; sum_s2 += sf * sf
        vf = v.astype(np.float64); sum_v += vf; sum_v2 += vf * vf
    h_std = _circular_hue_std(sum_cos, sum_sin, n)
    s_std = np.sqrt(np.maximum(0.0, sum_s2 / n - (sum_s / n) ** 2))
    v_std = np.sqrt(np.maximum(0.0, sum_v2 / n - (sum_v / n) ** 2))
    stable = (h_std <= max_hue_std) & (s_std <= max_sat_std) & (v_std <= max_val_std)
    return (stable.astype(np.uint8) * 255), 100.0 * float(1.0 - stable.mean())


def save_envelope(prefix, channel, frames, percentile=0.0):
    stack = np.stack(frames, axis=0)
    if percentile > 0:
        lo = np.percentile(stack, percentile, axis=0)
        hi = np.percentile(stack, 100.0 - percentile, axis=0)
    else:
        lo = np.min(stack, axis=0); hi = np.max(stack, axis=0)
    cv2.imwrite(str(BASELINE_DIR / f"{prefix}_baseline_{channel}_min.png"), lo.astype(np.uint8))
    cv2.imwrite(str(BASELINE_DIR / f"{prefix}_baseline_{channel}_max.png"), hi.astype(np.uint8))


def _latest_hsv(cap, correction):
    """Working-resolution HSV of a capture's latest frame, same transform as the runtime
    detector (downscale -> cvtColor -> hue rotation/correction)."""
    if cap is None or cap.latest_frame is None:
        return None
    return bgr_to_hsv_scaled(cap.latest_frame.raw, CLASSIFICATION_SCALE, correction, keep_value=True)


class _ChuteWiggler:
    """Oscillate the chute +/- amplitude at a fixed rate during capture so the envelope
    absorbs normal machine vibration. Net-zero: returns to start on stop."""

    def __init__(self, stepper, hz, amplitude_steps, logger=None):
        self._stepper = stepper
        self._half_period = 1.0 / (2.0 * hz) if hz > 0 else 0.083
        self._amplitude = int(amplitude_steps)
        self._logger = logger
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._net = 0

    def set_params(self, hz, amplitude_steps):
        """Live-update frequency + amplitude; the run loop reads these each cycle."""
        self._half_period = 1.0 / (2.0 * hz) if hz > 0 else 0.083
        self._amplitude = int(amplitude_steps)

    def start(self):
        self._stop.clear(); self._net = 0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        direction = 1
        while not self._stop.is_set():
            try:
                self._stepper.move_steps(direction * self._amplitude)
                self._net += direction * self._amplitude
            except Exception:
                pass
            direction = -direction
            self._stop.wait(self._half_period)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._net:
            try:
                self._stepper.move_steps(-self._net)
            except Exception:
                pass
            self._net = 0


class BaselineJob:
    """Runs the carousel sweep + envelope build in a background thread. Pollable status;
    cancelable; releases all hardware on completion or cancel."""

    def __init__(self, gc, camera: str = "all", wipe: bool = True,
                 chute_hz: float = DEFAULT_CHUTE_WIGGLE_HZ,
                 chute_steps: int = DEFAULT_CHUTE_WIGGLE_STEPS,
                 progress: Optional[Callable[[dict], None]] = None):
        if camera not in CAMERA_GROUPS:
            raise ValueError(f"camera must be one of {sorted(CAMERA_GROUPS)}")
        self.gc = gc
        self.camera = camera
        self.wipe = wipe
        self._chute_hz = float(chute_hz)
        self._chute_steps = int(chute_steps)
        self._wiggler: Optional[_ChuteWiggler] = None
        self._progress = progress
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._status = {
            "running": False, "camera": camera, "frame": 0, "total": MAX_FRAMES,
            "message": "queued", "done": False, "ok": False, "error": None,
            "chute_hz": self._chute_hz, "chute_steps": self._chute_steps,
        }
        self._lock = threading.Lock()

    def update_chute(self, hz: float, steps: int) -> None:
        """Change chute wiggle params, live if the job is mid-capture."""
        self._chute_hz = float(hz)
        self._chute_steps = int(steps)
        if self._wiggler is not None:
            self._wiggler.set_params(self._chute_hz, self._chute_steps)
        self._set(chute_hz=self._chute_hz, chute_steps=self._chute_steps)

    # ----- status ----
    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def _set(self, **kw):
        with self._lock:
            self._status.update(kw)
        if self._progress:
            try:
                self._progress(self.status())
            except Exception:
                pass

    # ----- lifecycle ----
    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self):
        self._cancel.set()

    def join(self, timeout=None):
        if self._thread:
            self._thread.join(timeout=timeout)

    @property
    def finished(self) -> bool:
        return self._status["done"]

    # ----- the work ----
    def _run(self):
        gc = self.gc
        self._set(running=True, message="starting cameras + steppers")
        correction = load_hsv_correction()
        irl = None
        captures: dict[str, CaptureThread] = {}
        wiggler = None
        try:
            from irl.config import make_irl_config, make_irl_interface

            irl_config = make_irl_config()
            irl = make_irl_interface(irl_config, gc)
            irl.enable_steppers()
            BASELINE_DIR.mkdir(parents=True, exist_ok=True)

            # Own our capture threads (decoupled from the run-mode VisionManager) so we
            # read exactly the camera-setup roles this machine uses.
            setup = resolve_camera_setup(gc.logger)  # role -> live cv2 index
            wanted = CAMERA_GROUPS[self.camera]
            for role in wanted:
                index = setup.get(role)
                if index is None:
                    continue
                cap = CaptureThread(role, make_camera_config(index))
                cap.start()
                captures[role] = cap

            self._set(message=f"waiting for {self.camera} camera frames")
            deadline = time.time() + 15.0
            available: list[str] = []
            while time.time() < deadline and not self._cancel.is_set():
                available = [c for c in wanted if c in captures and captures[c].latest_frame is not None]
                if len(available) == len([c for c in wanted if c in captures]) and available:
                    break
                time.sleep(0.25)
            if not available:
                self._set(message="no camera frames available", done=True, ok=False,
                          error=f"no {self.camera} camera(s) assigned/delivering frames")
                return

            chute_stepper = getattr(irl, "chute_stepper", None)
            if chute_stepper is None and getattr(irl, "chute", None) is not None:
                chute_stepper = getattr(irl.chute, "stepper", None)
            if chute_stepper is not None:
                wiggler = _ChuteWiggler(chute_stepper, self._chute_hz,
                                        self._chute_steps, logger=gc.logger)
                self._wiggler = wiggler
                wiggler.start()

            self._capture(captures, irl, available, correction)
        except Exception as e:
            gc.logger.warning(f"baseline job failed: {e}")
            self._set(message=f"error: {e}", done=True, ok=False, error=str(e))
        finally:
            if wiggler is not None:
                wiggler.stop()
            self._wiggler = None
            for cap in captures.values():
                try:
                    cap.stop()
                except Exception:
                    pass
            if irl is not None:
                try:
                    irl.disable_steppers()
                except Exception:
                    pass
            self._set(running=False)

    def _capture(self, captures, irl, cams, correction):
        # Per-camera frame stacks (optionally wiping prior frames).
        stacks = {c: {"h": [], "s": [], "v": []} for c in cams}
        if self.wipe:
            for c in cams:
                for p in globmod.glob(str(BASELINE_DIR / f"{c}_*.png")):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

        JITTER_RANGE = 5
        debt = 0.0
        interrupted = False
        for i in range(MAX_FRAMES):
            if self._cancel.is_set():
                interrupted = True
                self._set(message="cancelled — finalizing captured frames")
                break
            jitter = random.uniform(-JITTER_RANGE, JITTER_RANGE) if i % 2 == 1 else 0.0
            move = DEGREES_PER_FRAME + jitter - debt
            debt = jitter
            # Non-blocking move + low-rate completion poll so the chute wiggle thread keeps
            # the MCU bus and stays smooth (see CAROUSEL_POLL_S).
            irl.carousel_stepper.move_degrees(move)
            time.sleep(0.3)  # let the move actually start before polling "stopped"
            deadline = time.time() + CAROUSEL_MOVE_TIMEOUT_S
            while time.time() < deadline and not self._cancel.is_set():
                try:
                    if irl.carousel_stepper.stopped:
                        break
                except Exception:
                    break
                time.sleep(CAROUSEL_POLL_S)
            time.sleep(MOVE_SETTLE_S)
            for c in cams:
                hsv = _latest_hsv(captures.get(c), correction)
                if hsv is None:
                    continue
                h, s, v = cv2.split(hsv)
                stacks[c]["h"].append(h); stacks[c]["s"].append(s); stacks[c]["v"].append(v)
            self._set(frame=i + 1, message=f"captured frame {i + 1}/{MAX_FRAMES}")

        # Finalize each camera's robust envelope + stable mask.
        ok = True
        for c in cams:
            hs = stacks[c]
            if not hs["h"]:
                ok = False
                continue
            self._set(message=f"finalizing {c} envelope")
            save_envelope(c, "h", hs["h"], percentile=DEFAULT_PERCENTILE)
            save_envelope(c, "s", hs["s"], percentile=DEFAULT_PERCENTILE)
            save_envelope(c, "v", hs["v"], percentile=DEFAULT_PERCENTILE)
            if len(hs["h"]) >= 2:
                mask, dropped = compute_stable_mask(
                    hs["h"], hs["s"], hs["v"],
                    DEFAULT_MAX_HUE_STD, DEFAULT_MAX_SAT_STD, DEFAULT_MAX_VAL_STD,
                )
                cv2.imwrite(str(BASELINE_DIR / f"{c}_stable_mask.png"), mask)
                self.gc.logger.info(f"{c} stable mask dropped {dropped:.1f}% of pixels")

        msg = "cancelled" if interrupted else ("done" if ok else "no frames captured")
        self._set(message=msg, done=True, ok=ok and not interrupted)
