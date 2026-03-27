"""
MOG2 background subtraction test for feeder channel detection.
Continuously adapts to rotating faceted rotors while detecting pieces.

Run from /software/client: uv run python scripts/mog2_diff.py
Then open http://localhost:8098 in a browser.
"""

import argparse
import glob
import os
import sys
import time
import threading
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, Response, render_template_string, jsonify, request

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from blob_manager import getCameraSetup, getChannelPolygons
from global_config import mkGlobalConfig
from irl.config import mkIRLConfig, mkIRLInterface
from vision.heatmap_diff import HeatmapDiff
from vision.mog2_diff_configs import DEFAULT_MOG2_DIFF_CONFIG

RECORDINGS_DIR = "recordings"

PORT = 8098

DEFAULT_PARAMS = asdict(DEFAULT_MOG2_DIFF_CONFIG)


# --- Channel geometry ---

def loadChannelPolygons():
    saved = getChannelPolygons()
    if saved is None:
        return None
    polygon_data = saved.get("polygons", {})
    result = {}
    for key in ("second_channel", "third_channel"):
        pts = polygon_data.get(key)
        if pts:
            result[key] = np.array(pts, dtype=np.int32)
    return result if result else None


def loadCarouselPolygon():
    saved = getChannelPolygons()
    if saved is None:
        return None
    polygon_data = saved.get("polygons", {})
    pts = polygon_data.get("carousel")
    if not pts:
        return None
    return [(float(p[0]), float(p[1])) for p in pts]


def buildPolygonMask(polygons, shape):
    mask = np.zeros(shape[:2], dtype=np.uint8)
    if isinstance(polygons, dict):
        for pts in polygons.values():
            cv2.fillPoly(mask, [pts], 255)
    else:
        cv2.fillPoly(mask, [polygons], 255)
    if np.count_nonzero(mask) == 0:
        return None
    return mask


# --- Motor control ---

class MotorRunner:
    def __init__(self, irl, feeder_config):
        self.irl = irl
        self._second_running = False
        self._third_running = False
        self._lock = threading.Lock()
        self._second_steps = feeder_config.second_rotor_normal.steps_per_pulse
        self._second_speed = feeder_config.second_rotor_normal.microsteps_per_second
        self._second_delay = feeder_config.second_rotor_normal.delay_between_pulse_ms / 1000.0
        self._third_steps = feeder_config.third_rotor_normal.steps_per_pulse
        self._third_speed = feeder_config.third_rotor_normal.microsteps_per_second
        self._third_delay = feeder_config.third_rotor_normal.delay_between_pulse_ms / 1000.0

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        next_is_second = True
        while True:
            with self._lock:
                run_second = self._second_running
                run_third = self._third_running

            pulsed = False
            if next_is_second:
                if run_second:
                    self.irl.second_c_channel_rotor_stepper.set_speed_limits(16, self._second_speed)
                    stepper = self.irl.second_c_channel_rotor_stepper
                    stepper.move_degrees(stepper.degrees_for_microsteps(self._second_steps))
                    pulsed = True
                    time.sleep(self._second_delay)
                next_is_second = False
            else:
                if run_third:
                    self.irl.third_c_channel_rotor_stepper.set_speed_limits(16, self._third_speed)
                    stepper = self.irl.third_c_channel_rotor_stepper
                    stepper.move_degrees(stepper.degrees_for_microsteps(self._third_steps))
                    pulsed = True
                    time.sleep(self._third_delay)
                next_is_second = True

            if not pulsed:
                if next_is_second and run_second:
                    self.irl.second_c_channel_rotor_stepper.set_speed_limits(16, self._second_speed)
                    stepper = self.irl.second_c_channel_rotor_stepper
                    stepper.move_degrees(stepper.degrees_for_microsteps(self._second_steps))
                    time.sleep(self._second_delay)
                elif not next_is_second and run_third:
                    self.irl.third_c_channel_rotor_stepper.set_speed_limits(16, self._third_speed)
                    stepper = self.irl.third_c_channel_rotor_stepper
                    stepper.move_degrees(stepper.degrees_for_microsteps(self._third_steps))
                    time.sleep(self._third_delay)
                else:
                    time.sleep(0.1)

    def toggleSecond(self):
        with self._lock:
            self._second_running = not self._second_running
            return self._second_running

    def toggleThird(self):
        with self._lock:
            self._third_running = not self._third_running
            return self._third_running

    @property
    def second_running(self):
        with self._lock:
            return self._second_running

    @property
    def third_running(self):
        with self._lock:
            return self._third_running


# --- Main app state ---

CHANNEL_TO_MOTOR = {
    "second_channel": "second",
    "third_channel": "third",
}


class ChannelMog2:
    def __init__(self, name, polygon, shape, params):
        self.name = name
        self.mask = buildPolygonMask(polygon, shape)
        self.mog2 = cv2.createBackgroundSubtractorMOG2(
            history=int(params["history"]),
            varThreshold=params["var_threshold"],
            detectShadows=False,
        )
        self.mog2.setNMixtures(int(params["n_mixtures"]))

    def rebuild(self, params):
        self.mog2 = cv2.createBackgroundSubtractorMOG2(
            history=int(params["history"]),
            varThreshold=params["var_threshold"],
            detectShadows=False,
        )
        self.mog2.setNMixtures(int(params["n_mixtures"]))


class AppState:
    def __init__(self, device_index, motor_runner, learn_only_rotating, carousel_stepper):
        self.cap = cv2.VideoCapture(device_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.lock = threading.Lock()
        self.latest_frame = None
        self.latest_gray = None
        self.latest_lab = None
        self.channel_polygons = loadChannelPolygons()
        self.channel_mog2s: dict[str, ChannelMog2] = {}
        self.combined_mask = None
        self.running = True
        self.params = dict(DEFAULT_PARAMS)
        self.frame_count = 0
        self.motor_runner = motor_runner
        self.learn_only_rotating = learn_only_rotating
        self.carousel_stepper = carousel_stepper
        self.carousel_polygon = loadCarouselPolygon()
        self.carousel_heatmap = HeatmapDiff()
        self._carousel_rotating = False
        self._carousel_stopped_at: float = 0.0
        self._recording = False
        self._record_writer: cv2.VideoWriter | None = None
        self._record_path: str | None = None
        self._replay_mode = False
        self._replay_cap: cv2.VideoCapture | None = None
        self._replay_idx = 0
        self._replay_total = 0
        self._replay_paused = False
        self._replay_speed = 1
        self._last_replay_out: np.ndarray | None = None
        self._params_version = 0
        self._replay_params_ver = 0
        self._reprocessing = False
        self._replay_lock = threading.Lock()
        self._seek_cancel = False
        self._thread = threading.Thread(target=self._captureLoop, daemon=True)
        self._thread.start()

    def _initChannelMog2s(self, shape):
        if not self.channel_polygons:
            return
        for name, polygon in self.channel_polygons.items():
            self.channel_mog2s[name] = ChannelMog2(name, polygon, shape, self.params)
        self.combined_mask = buildPolygonMask(self.channel_polygons, shape)

    def _rebuildMog2(self):
        for ch in self.channel_mog2s.values():
            ch.rebuild(self.params)

    def _isChannelRotating(self, channel_name):
        motor_key = CHANNEL_TO_MOTOR.get(channel_name)
        if motor_key == "second":
            return self.motor_runner.second_running
        if motor_key == "third":
            return self.motor_runner.third_running
        return False

    def rotateCarousel(self):
        self.carousel_stepper.move_degrees(-90.0)
        self._carousel_rotating = True
        self._carousel_stopped_at = 0.0
        self.carousel_heatmap.clearBaseline()

    def _maybeRecaptureCarouselBaseline(self, gray):
        if not self._carousel_rotating and self._carousel_stopped_at == 0.0:
            return
        if self.carousel_heatmap.has_baseline:
            return
        if self._carousel_rotating:
            if self.carousel_stepper.stopped:
                self._carousel_rotating = False
                self._carousel_stopped_at = time.time()
                print("Carousel stepper stopped, waiting for settle...")
            return
        elapsed_ms = (time.time() - self._carousel_stopped_at) * 1000
        if elapsed_ms < self.params["carousel_settle_ms"]:
            return
        if self.carousel_polygon:
            self.carousel_heatmap.captureBaseline(self.carousel_polygon, gray.shape)
            print(f"Carousel baseline captured after {elapsed_ms:.0f}ms settle")

    def _captureLoop(self):
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            lab_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            self.carousel_heatmap.pushFrame(gray)
            with self.lock:
                self.latest_frame = frame
                self.latest_gray = gray
                self.latest_lab = lab_frame
                if self._recording and self._record_writer is not None:
                    self._record_writer.write(frame)

    def startRecording(self):
        os.makedirs(RECORDINGS_DIR, exist_ok=True)
        path = os.path.join(RECORDINGS_DIR, f"mog2_{int(time.time())}.avi")
        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
        h, w = 1080, 1920
        with self.lock:
            if self.latest_frame is not None:
                h, w = self.latest_frame.shape[:2]
        self._record_writer = cv2.VideoWriter(path, fourcc, 30.0, (w, h))
        self._record_path = path
        self._recording = True
        print(f"Recording started: {path}")

    def stopRecording(self):
        with self.lock:
            self._recording = False
            writer = self._record_writer
            self._record_writer = None
        if writer is not None:
            writer.release()
        print(f"Recording stopped: {self._record_path}")

    def startReplay(self, path: str | None = None):
        target = path or self._record_path
        if not target or not os.path.exists(target):
            return False
        self.stopRecording()
        self._seek_cancel = True
        with self._replay_lock:
            self._seek_cancel = False
            self._record_path = target
            self._replay_mode = True
            self._replay_paused = False
            self._replay_speed = 1
            self._replay_params_ver = self._params_version
            self._restartReplay()
        print(f"Replay started: {target} ({self._replay_total} frames)")
        return True

    def _restartReplay(self):
        old_cap = self._replay_cap
        self._replay_cap = None
        if old_cap is not None:
            old_cap.release()
        self._replay_cap = cv2.VideoCapture(self._record_path)
        self._replay_total = int(self._replay_cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._replay_idx = 0
        self._rebuildMog2()
        self.carousel_heatmap = HeatmapDiff()
        self._last_replay_out = None

    def stopReplay(self):
        self._seek_cancel = True
        with self._replay_lock:
            self._seek_cancel = False
            self._replay_mode = False
            self._replay_paused = False
            cap = self._replay_cap
            self._replay_cap = None
        if cap is not None:
            cap.release()
        self._rebuildMog2()
        print("Replay stopped")

    def getAnnotatedFrame(self):
        if self._replay_mode:
            return self._getReplayFrame()
        with self.lock:
            frame = self.latest_frame
            gray = self.latest_gray
            lab_frame = self.latest_lab
        if frame is None or gray is None or lab_frame is None:
            return None
        return self._processAndAnnotate(frame, gray, lab_frame, force_learn=False)

    def _feedMog2(self, lab_frame):
        if not self.channel_mog2s and self.channel_polygons:
            self._initChannelMog2s(lab_frame.shape)
        p = self.params
        blur_k = int(p["blur_kernel"]) | 1
        blurred = cv2.GaussianBlur(lab_frame, (blur_k, blur_k), 0)
        for ch in self.channel_mog2s.values():
            if ch.mask is not None:
                ch.mog2.apply(blurred, learningRate=p["learning_rate"])

    def _reprocessToFrame(self, target_idx: int):
        hold = self._last_replay_out
        self._restartReplay()
        self._last_replay_out = hold
        cap = self._replay_cap
        if cap is None:
            return
        last_frame = None
        last_gray = None
        last_lab = None
        for i in range(target_idx):
            if self._seek_cancel:
                break
            ret, frame = cap.read()
            if not ret:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            lab_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            self._replay_idx = i + 1
            if i < target_idx - 1:
                self._feedMog2(lab_frame)
            else:
                last_frame = frame
                last_gray = gray
                last_lab = lab_frame
        if last_frame is not None and last_gray is not None and last_lab is not None and not self._seek_cancel:
            self._last_replay_out = self._processAndAnnotate(last_frame, last_gray, last_lab, force_learn=True)

    def _getReplayFrame(self):
        if not self._replay_lock.acquire(blocking=False):
            return self._last_replay_out
        try:
            if self._params_version != self._replay_params_ver:
                target = self._replay_idx
                was_paused = self._replay_paused
                self._reprocessing = True
                self._reprocessToFrame(target)
                self._reprocessing = False
                self._replay_params_ver = self._params_version
                if was_paused:
                    self._replay_paused = True
                    return self._last_replay_out

            cap = self._replay_cap
            if self._replay_paused or cap is None:
                return self._last_replay_out

            batch = 30 if self._replay_speed == 0 else self._replay_speed
            out = None
            for _ in range(batch):
                if self._seek_cancel:
                    break
                ret, frame = cap.read()
                if not ret:
                    self._replay_paused = True
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                lab_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
                self._replay_idx += 1
                out = self._processAndAnnotate(frame, gray, lab_frame, force_learn=True)
            if out is not None:
                self._last_replay_out = out
            return self._last_replay_out
        finally:
            self._replay_lock.release()

    def seekReplay(self, target_idx: int):
        if not self._replay_mode:
            return
        self._seek_cancel = True
        with self._replay_lock:
            self._seek_cancel = False
            target_idx = max(1, min(target_idx, self._replay_total))
            self._reprocessing = True
            self._reprocessToFrame(target_idx)
            self._reprocessing = False
            self._replay_paused = True
            self._replay_params_ver = self._params_version

    def _processAndAnnotate(self, frame, gray, lab_frame, force_learn=False):
        if not self.channel_mog2s and self.channel_polygons:
            self._initChannelMog2s(lab_frame.shape)

        annotated = frame.copy()

        if self.combined_mask is None:
            cv2.putText(annotated, "NO CHANNELS - run polygon_editor.py first", (30, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
            return annotated

        p = self.params
        blur_k = int(p["blur_kernel"]) | 1
        morph_k = int(p["morph_kernel"]) | 1
        learning_rate = p["learning_rate"]
        heat_gain = p["heat_gain"]
        min_area = int(p["min_contour_area"])

        blurred = cv2.GaussianBlur(lab_frame, (blur_k, blur_k), 0)

        fg_mask = np.zeros(lab_frame.shape[:2], dtype=np.uint8)
        for name, ch in self.channel_mog2s.items():
            if ch.mask is None:
                continue
            if not force_learn and self.learn_only_rotating and not self._isChannelRotating(name):
                ch_lr = 0.0
            else:
                ch_lr = learning_rate
            ch_fg_raw = ch.mog2.apply(blurred, learningRate=ch_lr)
            ch_fg = cv2.bitwise_and(ch_fg_raw, ch.mask)
            fg_mask = cv2.bitwise_or(fg_mask, ch_fg)

        fg_thresh = int(p["fg_threshold"])
        if fg_thresh > 0:
            _, fg_mask = cv2.threshold(fg_mask, fg_thresh, 255, cv2.THRESH_BINARY)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morph_k, morph_k))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)

        dilate_iters = int(p["dilate_iterations"])
        if dilate_iters > 0:
            fg_mask = cv2.dilate(fg_mask, kernel, iterations=dilate_iters)

        max_area = int(p["max_contour_area"])
        contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        bboxes = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area:
                continue
            if max_area > 0 and area > max_area:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            bboxes.append((x, y, x + w, y + h))

        mask_bool = self.combined_mask > 0
        fg_bool = fg_mask > 0
        hot_count = int(np.count_nonzero(fg_bool))

        out = annotated.copy()
        out[mask_bool] = (annotated[mask_bool] * 0.5).astype(np.uint8)

        display = np.zeros_like(fg_mask)
        display[fg_bool & mask_bool] = np.clip(
            fg_mask[fg_bool & mask_bool].astype(np.float32) * heat_gain, 0, 255
        ).astype(np.uint8)
        heatmap = cv2.applyColorMap(display, cv2.COLORMAP_JET)
        show_heat = fg_bool & mask_bool
        out[show_heat] = (
            annotated[show_heat].astype(np.float32) * 0.2
            + heatmap[show_heat].astype(np.float32) * 0.8
        ).clip(0, 255).astype(np.uint8)

        if self.channel_polygons:
            for name, pts in self.channel_polygons.items():
                if force_learn:
                    color = (255, 200, 0) if "second" in name else (0, 200, 255)
                    cv2.polylines(out, [pts], True, color, 2)
                else:
                    rotating = self._isChannelRotating(name)
                    frozen = self.learn_only_rotating and not rotating
                    color = (255, 200, 0) if "second" in name else (0, 200, 255)
                    if frozen:
                        color = (80, 80, 80)
                    cv2.polylines(out, [pts], True, color, 2)
                    if frozen:
                        cx = int(np.mean(pts[:, 0]))
                        cy = int(np.mean(pts[:, 1]))
                        cv2.putText(out, "FROZEN", (cx - 40, cy),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 80, 80), 2)

        for x1, y1, x2, y2 in bboxes:
            cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)

        triggered = len(bboxes) > 0
        color = (0, 0, 255) if triggered else (0, 255, 0)
        label = f"DETECTED: {len(bboxes)}" if triggered else "clear"
        cv2.putText(out, label, (30, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
        cv2.putText(out, f"fg_px: {hot_count}", (30, 85),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)

        if not force_learn:
            mr = self.motor_runner
            ch2_label = "CH2: ON" if mr.second_running else "CH2: off"
            ch3_label = "CH3: ON" if mr.third_running else "CH3: off"
            ch2_color = (0, 200, 255) if mr.second_running else (100, 100, 100)
            ch3_color = (0, 200, 255) if mr.third_running else (100, 100, 100)
            cv2.putText(out, ch2_label, (30, 120),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, ch2_color, 2)
            cv2.putText(out, ch3_label, (30, 150),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, ch3_color, 2)

            if self.learn_only_rotating:
                cv2.putText(out, "LEARN-ONLY-ROTATING", (30, 180),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 180, 0), 2)

            self._maybeRecaptureCarouselBaseline(gray)
            if self.carousel_heatmap.has_baseline:
                out = self.carousel_heatmap.annotateFrame(out, label="carousel", text_y=210)
            elif self._carousel_rotating:
                cv2.putText(out, "carousel rotating...", (30, 210),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 180, 255), 2)
            elif self._carousel_stopped_at > 0:
                remaining_ms = self.params["carousel_settle_ms"] - (time.time() - self._carousel_stopped_at) * 1000
                if remaining_ms > 0:
                    cv2.putText(out, f"carousel settling... {remaining_ms:.0f}ms", (30, 210),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 180, 255), 2)
            elif self.carousel_polygon:
                cv2.putText(out, "carousel: no baseline (press Rotate)", (30, 210),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 100, 100), 2)

        if self._replay_mode:
            speed_label = "MAX" if self._replay_speed == 0 else f"{self._replay_speed}x"
            cv2.putText(out, f"REPLAY {self._replay_idx}/{self._replay_total} [{speed_label}]", (30, 120),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 100, 100), 2)
            if self._reprocessing:
                cv2.putText(out, "REPROCESSING...", (30, 150),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 180, 255), 2)
            elif self._replay_paused:
                paused_label = "END" if self._replay_idx >= self._replay_total else "PAUSED"
                cv2.putText(out, paused_label, (30, 150),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)

        self.frame_count += 1
        return out


# --- Flask app ---

app = Flask(__name__)
state: AppState = None  # type: ignore[assignment]

HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>MOG2 Background Subtraction - Feeder Channels</title>
    <style>
        * { box-sizing: border-box; }
        body { margin: 0; background: #111; color: #eee; font-family: monospace;
               display: flex; flex-direction: column; align-items: center; }
        h1 { margin: 12px 0 8px; font-size: 18px; }
        .top-row { display: flex; align-items: center; gap: 12px; margin: 8px 0; flex-wrap: wrap; }
        button { padding: 8px 20px; font-size: 14px; cursor: pointer;
                 background: #2a6; color: #fff; border: none; border-radius: 4px; }
        button:hover { background: #3b7; }
        button.motor { background: #555; }
        button.motor.active { background: #c62; }
        button.motor:hover { background: #777; }
        button.motor.active:hover { background: #e73; }
        button.record { background: #900; }
        button.record.active { background: #f00; }
        button.replay { background: #06a; }
        button.replay:hover { background: #08c; }
        button.replay.active { background: #0af; }
        #status { color: #aaa; font-size: 13px; }
        img { max-width: 95vw; max-height: 70vh; border: 1px solid #333; }
        .controls { display: flex; flex-wrap: wrap; gap: 16px; margin: 10px 0;
                     padding: 10px 16px; background: #1a1a1a; border-radius: 6px;
                     border: 1px solid #333; max-width: 95vw; }
        .param { display: flex; flex-direction: column; gap: 2px; min-width: 200px; }
        .param label { font-size: 12px; color: #999; }
        .param .row { display: flex; align-items: center; gap: 8px; }
        .param input[type=range] { flex: 1; accent-color: #2a6; }
        .param .val { font-size: 14px; min-width: 50px; text-align: right; color: #4f8; }
        .param .desc { font-size: 10px; color: #666; }
        .replay-row { display: flex; align-items: center; gap: 12px; margin: 4px 0; flex-wrap: wrap; }
        .replay-row select { padding: 4px 8px; font-size: 13px; background: #222; color: #eee;
                             border: 1px solid #555; border-radius: 4px; }
        .scrub-row { display: flex; align-items: center; gap: 8px; margin: 4px 0; max-width: 95vw; }
        .scrub-row input[type=range] { flex: 1; accent-color: #06a; }
        .scrub-row span { font-size: 13px; color: #aaa; min-width: 100px; }
    </style>
</head>
<body>
    <h1>MOG2 Background Subtraction - Feeder Channels</h1>
    <div class="top-row">
        <button onclick="resetMog2()">Reset MOG2</button>
        <button id="btn_ch2" class="motor" onclick="toggleMotor('second')">Channel 2 Motor</button>
        <button id="btn_ch3" class="motor" onclick="toggleMotor('third')">Channel 3 Motor</button>
        <button onclick="rotateCarousel()">Rotate Carousel</button>
        <button id="btn_record" class="record" onclick="toggleRecord()">Record</button>
        <button onclick="copyParams()">Copy Params</button>
        <span id="copy_status" style="font-size:11px;color:#888;"></span>
        <span id="status">MOG2 learning...</span>
    </div>
    <div class="replay-row" id="replay_row">
        <select id="recording_select"></select>
        <button class="replay" id="btn_replay" onclick="startReplay()">Replay</button>
        <button class="replay" id="btn_stop_replay" onclick="stopReplay()" style="display:none">Stop Replay</button>
        <button id="btn_pause" onclick="togglePause()" style="display:none">Pause</button>
        <select id="replay_speed" onchange="setSpeed(this.value)" style="display:none">
            <option value="1">1x</option>
            <option value="2">2x</option>
            <option value="4">4x</option>
            <option value="8">8x</option>
            <option value="0">Max</option>
        </select>
    </div>
    <div class="scrub-row" id="scrub_row" style="display:none">
        <input type="range" id="scrub_slider" min="1" max="1" value="1"
               oninput="onScrubInput(this.value)" onchange="onScrubChange(this.value)" />
        <span id="scrub_label">0 / 0</span>
    </div>
    <div class="controls" id="controls"></div>
    <img id="feed" src="/feed" />
    <script>
        const PARAMS = [
            { key: 'var_threshold', label: 'Variance Threshold',
              desc: 'How many sigma from a mode to be foreground (lower = more sensitive)',
              min: 4, max: 64, step: 1 },
            { key: 'learning_rate', label: 'Learning Rate',
              desc: 'How fast background adapts (0 = frozen, 0.01 = slow, 0.1 = fast)',
              min: 0, max: 0.1, step: 0.001 },
            { key: 'blur_kernel', label: 'Blur Kernel',
              desc: 'Gaussian blur size before MOG2 (smooths sensor noise)',
              min: 1, max: 21, step: 2 },
            { key: 'min_contour_area', label: 'Min Contour Area',
              desc: 'Minimum foreground blob area (px^2) to count as detection',
              min: 10, max: 1000, step: 10 },
            { key: 'max_contour_area', label: 'Max Contour Area',
              desc: 'Maximum blob area (0 = no limit) — rejects huge false positives',
              min: 0, max: 50000, step: 500 },
            { key: 'morph_kernel', label: 'Morph Kernel',
              desc: 'Morphological open/close kernel size (cleans up noise blobs)',
              min: 1, max: 15, step: 2 },
            { key: 'dilate_iterations', label: 'Dilate Iterations',
              desc: 'Expands foreground blobs before contouring — merges nearby clumps into one bbox',
              min: 0, max: 10, step: 1 },
            { key: 'fg_threshold', label: 'FG Threshold',
              desc: 'Min pixel confidence to count as foreground (0 = any nonzero, 128 = high confidence only)',
              min: 0, max: 254, step: 1 },
            { key: 'n_mixtures', label: 'Gaussian Mixtures',
              desc: 'Number of MOG2 mixtures per pixel (more = handles complex backgrounds like rotating rotors)',
              min: 1, max: 10, step: 1 },
            { key: 'heat_gain', label: 'Heat Gain',
              desc: 'Visual amplification for heatmap overlay',
              min: 1, max: 10, step: 0.5 },
            { key: 'carousel_settle_ms', label: 'Carousel Settle (ms)',
              desc: 'Time to wait after stepper stops before snapping baseline',
              min: 0, max: 5000, step: 50 },
        ];

        let currentValues = {};
        let inReplay = false;

        async function loadParams() {
            const res = await fetch('/params');
            currentValues = await res.json();
            renderControls();
        }

        function renderControls() {
            const el = document.getElementById('controls');
            el.innerHTML = '';
            for (const p of PARAMS) {
                const val = currentValues[p.key] ?? 0;
                const div = document.createElement('div');
                div.className = 'param';
                div.innerHTML = `
                    <label>${p.label}</label>
                    <div class="row">
                        <input type="range" min="${p.min}" max="${p.max}" step="${p.step}"
                               value="${val}" oninput="updateParam('${p.key}', this.value, this)" />
                        <span class="val" id="val_${p.key}">${val}</span>
                    </div>
                    <span class="desc">${p.desc}</span>
                `;
                el.appendChild(div);
            }
        }

        async function updateParam(key, value, input) {
            const numVal = parseFloat(value);
            currentValues[key] = numVal;
            document.getElementById('val_' + key).textContent = numVal;
            await fetch('/params', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ [key]: numVal }),
            });
        }

        async function copyParams() {
            const res = await fetch('/params_export');
            const text = await res.text();
            await navigator.clipboard.writeText(text);
            const el = document.getElementById('copy_status');
            el.textContent = 'copied!';
            setTimeout(() => { el.textContent = ''; }, 2000);
        }

        async function resetMog2() {
            const res = await fetch('/reset', { method: 'POST' });
            const data = await res.json();
            document.getElementById('status').textContent = data.ok
                ? 'MOG2 reset at ' + new Date().toLocaleTimeString()
                : 'Reset failed';
        }

        async function toggleMotor(channel) {
            const res = await fetch('/motor/' + channel, { method: 'POST' });
            const data = await res.json();
            const btnId = channel === 'second' ? 'btn_ch2' : 'btn_ch3';
            const btn = document.getElementById(btnId);
            if (data.running) {
                btn.classList.add('active');
                btn.textContent = (channel === 'second' ? 'Channel 2' : 'Channel 3') + ' Motor (ON)';
            } else {
                btn.classList.remove('active');
                btn.textContent = (channel === 'second' ? 'Channel 2' : 'Channel 3') + ' Motor';
            }
        }

        async function rotateCarousel() {
            const res = await fetch('/carousel/rotate', { method: 'POST' });
            const data = await res.json();
            document.getElementById('status').textContent = data.ok
                ? 'Carousel rotating, settling ' + data.settle_ms + 'ms...'
                : 'Carousel rotate failed';
        }

        async function toggleRecord() {
            const res = await fetch('/record/toggle', { method: 'POST' });
            const data = await res.json();
            const btn = document.getElementById('btn_record');
            if (data.recording) {
                btn.classList.add('active');
                btn.textContent = 'Stop Record';
            } else {
                btn.classList.remove('active');
                btn.textContent = 'Record';
                loadRecordings();
            }
            document.getElementById('status').textContent = data.recording
                ? 'Recording...' : 'Stopped recording';
        }

        async function loadRecordings() {
            const res = await fetch('/recordings');
            const data = await res.json();
            const sel = document.getElementById('recording_select');
            sel.innerHTML = '';
            for (const r of data.recordings) {
                const opt = document.createElement('option');
                opt.value = r;
                opt.textContent = r;
                sel.appendChild(opt);
            }
        }

        async function startReplay() {
            const sel = document.getElementById('recording_select');
            const path = sel.value;
            if (!path) return;
            const res = await fetch('/replay/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: path }),
            });
            const data = await res.json();
            if (data.ok) {
                inReplay = true;
                document.getElementById('btn_replay').style.display = 'none';
                document.getElementById('btn_stop_replay').style.display = '';
                document.getElementById('btn_pause').style.display = '';
                document.getElementById('btn_pause').textContent = 'Pause';
                document.getElementById('replay_speed').style.display = '';
                document.getElementById('status').textContent = 'Replay: ' + data.total_frames + ' frames';
                showScrub(data.total_frames);
                startStatusPoll();
            }
        }

        async function stopReplay() {
            await fetch('/replay/stop', { method: 'POST' });
            inReplay = false;
            document.getElementById('btn_replay').style.display = '';
            document.getElementById('btn_stop_replay').style.display = 'none';
            document.getElementById('btn_pause').style.display = 'none';
            document.getElementById('replay_speed').style.display = 'none';
            document.getElementById('status').textContent = 'Live';
            hideScrub();
            stopStatusPoll();
        }

        async function togglePause() {
            const res = await fetch('/replay/pause', { method: 'POST' });
            const data = await res.json();
            document.getElementById('btn_pause').textContent = data.paused ? 'Resume' : 'Pause';
        }

        async function setSpeed(val) {
            await fetch('/replay/speed', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ speed: parseInt(val) }),
            });
        }

        let scrubTimeout = null;
        let scrubbing = false;

        function onScrubInput(val) {
            document.getElementById('scrub_label').textContent = val + ' / ' + document.getElementById('scrub_slider').max;
            scrubbing = true;
            if (scrubTimeout) clearTimeout(scrubTimeout);
            scrubTimeout = setTimeout(() => onScrubChange(val), 200);
        }

        function onScrubChange(val) {
            scrubbing = false;
            if (scrubTimeout) clearTimeout(scrubTimeout);
            scrubTimeout = null;
            fetch('/replay/seek', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ frame: parseInt(val) }),
            }).then(res => res.json()).then(data => {
                document.getElementById('btn_pause').textContent = 'Resume';
            });
        }

        function showScrub(total) {
            const row = document.getElementById('scrub_row');
            const slider = document.getElementById('scrub_slider');
            row.style.display = 'flex';
            slider.max = total;
        }

        function hideScrub() {
            document.getElementById('scrub_row').style.display = 'none';
        }

        let statusInterval = null;
        function startStatusPoll() {
            if (statusInterval) return;
            statusInterval = setInterval(async () => {
                const res = await fetch('/replay/status');
                const data = await res.json();
                if (!data.active) { stopStatusPoll(); return; }
                if (!scrubbing) {
                    const slider = document.getElementById('scrub_slider');
                    slider.max = data.total;
                    slider.value = data.frame;
                    document.getElementById('scrub_label').textContent = data.frame + ' / ' + data.total;
                }
            }, 250);
        }

        function stopStatusPoll() {
            if (statusInterval) { clearInterval(statusInterval); statusInterval = null; }
        }

        setInterval(() => {
            const img = document.getElementById('feed');
            img.src = '/feed?' + Date.now();
        }, 30000);

        loadParams();
        loadRecordings();
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/reset", methods=["POST"])
def reset_mog2():
    state._rebuildMog2()
    return jsonify({"ok": True})

@app.route("/carousel/rotate", methods=["POST"])
def rotate_carousel():
    if not state.carousel_polygon:
        return jsonify({"ok": False, "error": "no carousel polygon"}), 400
    state.rotateCarousel()
    return jsonify({"ok": True, "settle_ms": state.params["carousel_settle_ms"]})

@app.route("/motor/<channel>", methods=["POST"])
def toggle_motor(channel):
    if channel == "second":
        running = state.motor_runner.toggleSecond()
    elif channel == "third":
        running = state.motor_runner.toggleThird()
    else:
        return jsonify({"error": "unknown channel"}), 400
    return jsonify({"running": running, "channel": channel})

@app.route("/params", methods=["GET"])
def get_params():
    return jsonify(state.params)

@app.route("/params_export")
def params_export():
    lines = ["mog2 diff params:"]
    for k, v in state.params.items():
        default = DEFAULT_PARAMS[k]
        marker = "  <-- changed" if v != default else ""
        lines.append(f"  {k}: {v}{marker}")
    changed = {k: v for k, v in state.params.items() if v != DEFAULT_PARAMS[k]}
    if changed:
        lines.append("")
        lines.append(f"changed from default: {changed}")
    else:
        lines.append("")
        lines.append("(all defaults)")
    return Response("\n".join(lines), mimetype="text/plain")

@app.route("/params", methods=["POST"])
def set_params():
    updates = request.get_json()
    rebuild = False
    for k, v in updates.items():
        if k in state.params:
            state.params[k] = float(v)
            if k in ("history", "var_threshold", "n_mixtures"):
                rebuild = True
    if rebuild:
        state._rebuildMog2()
    state._params_version += 1
    return jsonify(state.params)

@app.route("/record/toggle", methods=["POST"])
def toggle_record():
    if state._recording:
        state.stopRecording()
    else:
        state.startRecording()
    return jsonify({"recording": state._recording, "path": state._record_path})

@app.route("/recordings", methods=["GET"])
def list_recordings():
    if not os.path.isdir(RECORDINGS_DIR):
        return jsonify({"recordings": []})
    files = sorted(glob.glob(os.path.join(RECORDINGS_DIR, "*.avi")), reverse=True)
    return jsonify({"recordings": files})

@app.route("/replay/start", methods=["POST"])
def start_replay():
    data = request.get_json() or {}
    path = data.get("path")
    ok = state.startReplay(path)
    return jsonify({"ok": ok, "total_frames": state._replay_total})

@app.route("/replay/stop", methods=["POST"])
def stop_replay():
    state.stopReplay()
    return jsonify({"ok": True})

@app.route("/replay/pause", methods=["POST"])
def pause_replay():
    state._replay_paused = not state._replay_paused
    return jsonify({"paused": state._replay_paused})

@app.route("/replay/speed", methods=["POST"])
def set_replay_speed():
    data = request.get_json() or {}
    state._replay_speed = int(data.get("speed", 1))
    return jsonify({"speed": state._replay_speed})

@app.route("/replay/seek", methods=["POST"])
def seek_replay():
    data = request.get_json() or {}
    target = int(data.get("frame", 0))
    state.seekReplay(target)
    return jsonify({"ok": True, "frame": state._replay_idx, "total": state._replay_total})

@app.route("/replay/status", methods=["GET"])
def replay_status():
    return jsonify({
        "active": state._replay_mode,
        "frame": state._replay_idx,
        "total": state._replay_total,
        "paused": state._replay_paused,
        "reprocessing": state._reprocessing,
    })

def generateFrames():
    while True:
        frame = state.getAnnotatedFrame()
        if frame is None:
            time.sleep(0.03)
            continue
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
        if not state._replay_mode:
            time.sleep(0.033)

@app.route("/feed")
def feed():
    return Response(generateFrames(), mimetype="multipart/x-mixed-replace; boundary=frame")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MOG2 background subtraction test")
    parser.add_argument(
        "--learn-always", action="store_true",
        help="update MOG2 background model even when motors are stopped",
    )
    args, remaining = parser.parse_known_args()
    sys.argv = [sys.argv[0]] + remaining

    if loadChannelPolygons() is None:
        print("ERROR: No channel polygons saved. Run client/scripts/polygon_editor.py first.")
        sys.exit(1)

    camera_setup = getCameraSetup()
    if camera_setup is None or "feeder" not in camera_setup:
        print("ERROR: No camera setup found. Run client/scripts/camera_setup.py first.")
        sys.exit(1)

    device_index = camera_setup["feeder"]
    print(f"Using feeder camera device index: {device_index}")
    learn_only_rotating = not args.learn_always
    if learn_only_rotating:
        print("Mode: learn-only-rotating (frozen channels won't update background)")

    gc = mkGlobalConfig()
    irl_config = mkIRLConfig()
    irl = mkIRLInterface(irl_config, gc)
    irl.enableSteppers()

    motor_runner = MotorRunner(irl, irl_config.feeder_config)
    state = AppState(device_index, motor_runner, learn_only_rotating, irl.carousel_stepper)
    print(f"Server starting on http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
