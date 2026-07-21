"""Feeder-dynamics ("sim data") capture collector.

Streams the perception state of every channel — per-piece COM positions, zones,
bboxes, track ids — into sim_data_store segments while the machine is actively
sorting. Together with the stepper-command records emitted by the hardware
layer (hardware/sorter_interface.py) and the config-change records written
here, a segment is a full (state, action) transition log: the raw material for
displacement models, feeder controllers, and eventually a learned simulator.

Capture is intentionally passive: it never moves anything, never changes
config, and works the same whether the pulse-perception auto-tuner is idle,
running a session, or exploring in the background — those cases are simply
visible in the config records. Every segment opens with a meta snapshot of the
machine context (setup, modes, tuning configs, polygons, code version) so data
collected on a machine with unusual settings is labeled as such rather than
silently mixed in.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

import sim_data_store

_POLL_INTERVAL_S = 0.02
_CONFIG_WATCH_INTERVAL_S = 2.0
_FLUSH_INTERVAL_S = 2.0
_STOP_SORTING_GRACE_S = 5.0
_SEGMENT_ROTATE_RAW_BYTES = 24 * 1024 * 1024
_SEGMENT_ROTATE_MAX_AGE_S = 30 * 60

CAPTURE_FORMAT_VERSION = 1

_git_sha_cache: str | None = None


def _gitSha() -> str | None:
    global _git_sha_cache
    if _git_sha_cache is not None:
        return _git_sha_cache or None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=3,
        )
        _git_sha_cache = result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        _git_sha_cache = ""
    return _git_sha_cache or None


def _captureEnabled() -> bool:
    return os.getenv("SIM_DATA_CAPTURE", "1").strip() not in ("0", "false", "no")


class SimDataCollector:
    def __init__(self, *, perception_service: Any, gc: Any, irl_config: Any) -> None:
        self._service = perception_service
        self._gc = gc
        self._irl_config = irl_config
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_state_ts: dict[int, float] = {}
        self._last_had_pieces: dict[int, bool] = {}
        self._frame_info_sent: set[int] = set()
        self._last_config_check = 0.0
        self._last_config_snapshot: str = ""
        self._last_flush = 0.0
        self._segment_opened_at = 0.0
        self._not_sorting_since: float | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="sim-data-collector"
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._thread = None
        sim_data_store.endSegment()

    def stats(self) -> dict[str, Any]:
        return sim_data_store.getStats()

    def _isSorting(self) -> bool:
        try:
            from server import shared_state
            from defs.sorter_controller import SorterLifecycle

            controller = shared_state.controller_ref
            return controller is not None and controller.state == SorterLifecycle.RUNNING
        except Exception:
            return False

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:
                try:
                    self._gc.logger.warning(f"[sim-data] collector tick failed: {exc}")
                except Exception:
                    pass
                self._stop.wait(1.0)
            self._stop.wait(_POLL_INTERVAL_S)

    def _tick(self) -> None:
        now = time.monotonic()
        sorting = _captureEnabled() and self._isSorting()

        if not sorting:
            if sim_data_store.segmentOpen():
                if self._not_sorting_since is None:
                    self._not_sorting_since = now
                elif now - self._not_sorting_since >= _STOP_SORTING_GRACE_S:
                    sim_data_store.endSegment()
                    self._resetSegmentState()
            else:
                self._stop.wait(0.3)
            return

        self._not_sorting_since = None
        if not sim_data_store.segmentOpen():
            if sim_data_store.beginSegment(self._buildMeta()):
                self._segment_opened_at = now
                self._frame_info_sent.clear()
                self._last_config_snapshot = ""
                self._last_config_check = 0.0

        self._sampleStates()
        self._watchConfig(now)

        if now - self._last_flush >= _FLUSH_INTERVAL_S:
            self._last_flush = now
            sim_data_store.flush()

        if (
            sim_data_store.activeBytes() >= _SEGMENT_ROTATE_RAW_BYTES
            or now - self._segment_opened_at >= _SEGMENT_ROTATE_MAX_AGE_S
        ):
            sim_data_store.endSegment()
            self._resetSegmentState()

    def _resetSegmentState(self) -> None:
        self._last_state_ts.clear()
        self._last_had_pieces.clear()
        self._frame_info_sent.clear()
        self._last_config_snapshot = ""

    def _sampleStates(self) -> None:
        try:
            states = self._service.read_states()
        except Exception:
            return
        wall = time.time()
        mono = time.monotonic()
        for channel_id, state in states.items():
            ts = float(getattr(state, "ts", 0.0) or 0.0)
            if ts <= 0.0 or self._last_state_ts.get(channel_id) == ts:
                continue
            self._last_state_ts[channel_id] = ts
            pieces = getattr(state, "pieces", ()) or ()
            had_pieces = self._last_had_pieces.get(channel_id, False)
            has_pieces = len(pieces) > 0
            # Empty frames after an empty frame carry no dynamics information;
            # keep only the transition to empty so gaps stay explicit.
            if not has_pieces and not had_pieces:
                continue
            self._last_had_pieces[channel_id] = has_pieces
            self._maybeFrameInfo(channel_id)
            sim_data_store.record(
                {
                    "type": "state",
                    "t": wall,
                    "mono": mono,
                    "ch": channel_id,
                    "ts": ts,
                    "in_drop": bool(state.in_drop),
                    "in_exit": bool(state.in_exit),
                    "pieces": [
                        [
                            piece.com_forward_to_exit_deg,
                            piece.com_section,
                            piece.zone_code,
                            piece.bbox[0],
                            piece.bbox[1],
                            piece.bbox[2],
                            piece.bbox[3],
                            piece.sv_bt_track_id,
                        ]
                        for piece in pieces
                    ],
                }
            )

    def _maybeFrameInfo(self, channel_id: int) -> None:
        if channel_id in self._frame_info_sent:
            return
        self._frame_info_sent.add(channel_id)
        try:
            res = self._service.read_pieces_and_frame(channel_id)
            if res is None:
                self._frame_info_sent.discard(channel_id)
                return
            _, frame = res
            bgr = getattr(frame, "bgr", None)
            if bgr is None or bgr.size == 0:
                self._frame_info_sent.discard(channel_id)
                return
            h, w = bgr.shape[:2]
            sim_data_store.record(
                {"type": "frame_info", "t": time.time(), "ch": channel_id, "w": int(w), "h": int(h)}
            )
        except Exception:
            pass

    def _watchConfig(self, now: float) -> None:
        if now - self._last_config_check < _CONFIG_WATCH_INTERVAL_S:
            return
        self._last_config_check = now
        snapshot = self._configSnapshot()
        if not snapshot:
            return
        import json

        encoded = json.dumps(snapshot, sort_keys=True, default=str)
        if encoded == self._last_config_snapshot:
            return
        self._last_config_snapshot = encoded
        sim_data_store.record({"type": "config", "t": time.time(), **snapshot})

    def _configSnapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        try:
            from toml_config import getPulsePerceptionConfig

            out["pulse_perception"] = getPulsePerceptionConfig()
        except Exception:
            pass
        try:
            from subsystems.feeder.pulse_perception.autotune import currentTrialInfo

            out["autotune"] = currentTrialInfo()
        except Exception:
            pass
        return out

    def _buildMeta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "t": time.time(),
            "capture_version": CAPTURE_FORMAT_VERSION,
            "git_sha": _gitSha(),
        }
        try:
            import local_state

            meta["machine_id"] = local_state.get_machine_id()
        except Exception:
            pass
        try:
            machine_setup = getattr(self._irl_config, "machine_setup", None)
            meta["machine_setup"] = getattr(machine_setup, "key", None)
            feeder = getattr(self._irl_config, "feeder", None)
            mode = getattr(feeder, "mode", None)
            meta["feeder_mode"] = getattr(mode, "value", None) or (str(mode) if mode else None)
            cc = getattr(self._irl_config, "classification_channel", None)
            cc_mode = getattr(cc, "mode", None)
            meta["classification_mode"] = getattr(cc_mode, "value", None) or (
                str(cc_mode) if cc_mode else None
            )
        except Exception:
            pass
        try:
            from subsystems.feeder.pulse_perception.flow import CHANNEL_OUTPUT_GEAR_RATIO

            meta["channel_output_gear_ratio"] = CHANNEL_OUTPUT_GEAR_RATIO
        except Exception:
            pass
        try:
            from toml_config import getPulsePerceptionConfig, getGoToAngleConfig

            meta["pulse_perception_config"] = getPulsePerceptionConfig()
            meta["go_to_angle_config"] = getGoToAngleConfig()
        except Exception:
            pass
        try:
            from toml_config import getClassificationChannelRev01Config

            meta["classification_channel_config"] = getClassificationChannelRev01Config()
        except Exception:
            pass
        try:
            import local_state

            meta["channel_polygons"] = local_state.get_channel_polygons()
            meta["classification_polygons"] = local_state.get_classification_polygons()
        except Exception:
            pass
        try:
            from subsystems.feeder.pulse_perception.autotune import currentTrialInfo

            meta["autotune"] = currentTrialInfo()
        except Exception:
            pass
        return meta
