from __future__ import annotations

import random
import threading
import time
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from global_config import GlobalConfig

# Numeric pulse-perception params the tuner is allowed to vary, with hard
# bounds. Bounds are deliberately tighter than the config's own clamps — a
# candidate can be slow or double-feed-prone, but never physically wild.
TUNABLE_PARAMS: list[dict[str, Any]] = [
    {"key": "move_speed_usteps_per_s", "type": "int", "min": 800, "max": 5000, "label": "Move speed (µsteps/s)"},
    {"key": "drop_pulse_output_deg", "type": "float", "min": 5.0, "max": 90.0, "label": "Drop-zone pulse distance (deg)"},
    {"key": "drop_pulse_pause_ms", "type": "int", "min": 0, "max": 600, "label": "Drop-zone pause (ms)"},
    {"key": "exit_pulse_output_deg", "type": "float", "min": 0.5, "max": 12.0, "label": "Exit pulse distance (deg)"},
    {"key": "exit_pulse_pause_ms", "type": "int", "min": 30, "max": 500, "label": "Exit pause (ms)"},
    {"key": "greedy_pulse_output_deg", "type": "float", "min": 5.0, "max": 90.0, "label": "Greedy pulse distance (deg)"},
    {"key": "greedy_pulse_pause_ms", "type": "int", "min": 0, "max": 600, "label": "Greedy pause (ms)"},
    {"key": "ch1_pulse_output_deg", "type": "float", "min": 0.25, "max": 8.0, "label": "C1 pulse distance (deg)"},
    {"key": "ch1_pulse_pause_ms", "type": "int", "min": 50, "max": 1000, "label": "C1 pause (ms)"},
]

_TUNABLE_BY_KEY = {meta["key"]: meta for meta in TUNABLE_PARAMS}

# Scoring is a constrained objective, not a weighted blend: a trial whose
# double-drop rate (events per delivered piece) exceeds max_double_drop_rate is
# infeasible and can never become "best" no matter how fast it fed. Among
# feasible trials, highest pieces/min (minus a jam/incident penalty) wins.
DEFAULT_SETTINGS: dict[str, Any] = {
    "trial_duration_s": 120.0,
    "settle_s": 3.0,
    "explore_probability": 0.25,
    "sigma_fraction": 0.15,
    "incident_weight": 10.0,
    "max_double_drop_rate": 0.05,
    "max_trials": 0,
    "param_keys": [meta["key"] for meta in TUNABLE_PARAMS],
}

# C4 drop-zone occupancy >= this many pieces counts as a double-drop event
# (two pieces landed in the same classification slot).
_DOUBLE_DROP_PIECES = 2
_ZONE_CODE_DROP = 1
_TICK_S = 0.2

_dispense_lock = threading.Lock()
_dispense_count = 0
_last_dispense_mono = 0.0

# The dispense signal is a falling edge of C3's per-frame in_exit boolean; a
# 1-2 frame detector dropout while a piece sits at the exit edge fires a
# phantom edge. Real dispenses are >= 1.5s apart (C3 is frozen by the
# post-dispense admission window), so anything faster is detector flicker.
# Kitbash 2026-07-21: ~75 counted vs 64 actually distributed in 17min.
_DISPENSE_DEBOUNCE_S = 1.2


def noteDispense() -> None:
    global _dispense_count, _last_dispense_mono
    now = time.monotonic()
    accepted = False
    with _dispense_lock:
        if now - _last_dispense_mono >= _DISPENSE_DEBOUNCE_S:
            _dispense_count += 1
            _last_dispense_mono = now
            accepted = True
    try:
        import control_data_store

        # Raw edges included (debounced=False) — they measure detector flicker,
        # which a control model needs to see as observation noise.
        control_data_store.record(
            {
                "type": "event",
                "kind": "c3_dispense",
                "t": time.time(),
                "mono": now,
                "debounced": accepted,
            }
        )
    except Exception:
        pass
    _ensureStartupRecovery()
    _maybeResumeBackground()


def dispenseCount() -> int:
    with _dispense_lock:
        return _dispense_count


_recovery_done = False
_recovery_lock = threading.Lock()
# Persisted background-exploration record ({enabled, settings, baseline_config,
# enabled_at}), mirrored in memory so per-dispense checks never hit sqlite.
_background_state: dict[str, Any] | None = None


def _ensureStartupRecovery() -> None:
    # A backend restart mid-run leaves the machine on whatever candidate config
    # the last trial wrote. Restore the run's baseline so a random candidate
    # never silently becomes the persistent config. Background exploration is
    # resumed separately (_maybeResumeBackground) once gc is available.
    global _recovery_done, _background_state
    if _recovery_done:
        return
    with _recovery_lock:
        if _recovery_done:
            return
        _recovery_done = True
        try:
            import local_state
            from toml_config import setPulsePerceptionConfig

            interrupted = local_state.interruptActiveFeederAutotuneRuns()
            for run in interrupted:
                baseline = run.get("baseline_config")
                if isinstance(baseline, dict) and baseline:
                    setPulsePerceptionConfig(baseline)
            persisted = local_state.getFeederAutotuneBackground()
            _background_state = persisted if isinstance(persisted, dict) else None
        except Exception:
            pass


def _maybeResumeBackground() -> None:
    state = _background_state
    if not state or not state.get("enabled"):
        return
    try:
        tuner = getAutoTuner()
    except Exception:
        return
    try:
        tuner.resumeBackground(state)
    except Exception:
        pass


def normalizeSettings(raw: dict[str, Any] | None) -> dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    settings["param_keys"] = list(DEFAULT_SETTINGS["param_keys"])
    if not isinstance(raw, dict):
        return settings
    for key in ("trial_duration_s", "settle_s", "explore_probability", "sigma_fraction", "incident_weight", "max_double_drop_rate"):
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            settings[key] = float(value)
    max_trials = raw.get("max_trials")
    if isinstance(max_trials, int) and not isinstance(max_trials, bool) and max_trials >= 0:
        settings["max_trials"] = max_trials
    param_keys = raw.get("param_keys")
    if isinstance(param_keys, list):
        valid = [k for k in param_keys if isinstance(k, str) and k in _TUNABLE_BY_KEY]
        if valid:
            settings["param_keys"] = valid
    settings["trial_duration_s"] = max(20.0, settings["trial_duration_s"])
    settings["settle_s"] = min(30.0, max(0.0, settings["settle_s"]))
    settings["explore_probability"] = min(1.0, max(0.0, settings["explore_probability"]))
    settings["sigma_fraction"] = min(0.5, max(0.02, settings["sigma_fraction"]))
    settings["max_double_drop_rate"] = min(0.5, max(0.0, settings["max_double_drop_rate"]))
    return settings


def _clampParam(meta: dict[str, Any], value: float) -> float | int:
    clamped = min(float(meta["max"]), max(float(meta["min"]), float(value)))
    return int(round(clamped)) if meta["type"] == "int" else round(clamped, 3)


def sampleCandidate(
    param_keys: list[str],
    best_params: dict[str, Any] | None,
    rng: random.Random,
    *,
    explore_probability: float,
    sigma_fraction: float,
) -> tuple[str, dict[str, Any]]:
    explore = best_params is None or rng.random() < explore_probability
    params: dict[str, Any] = {}
    for key in param_keys:
        meta = _TUNABLE_BY_KEY[key]
        lo, hi = float(meta["min"]), float(meta["max"])
        if explore or best_params is None:
            value = rng.uniform(lo, hi)
        else:
            center = float(best_params.get(key, (lo + hi) / 2.0))
            value = rng.gauss(center, sigma_fraction * (hi - lo))
        params[key] = _clampParam(meta, value)
    return ("explore" if explore else "refine"), params


def computeTrialMetrics(
    *,
    measured_s: float,
    pieces_delivered: int,
    incidents: int,
    double_drops: int,
    incident_weight: float,
    max_double_drop_rate: float,
) -> dict[str, Any]:
    if measured_s <= 0:
        return {
            "pieces_per_min": None,
            "double_drop_rate": None,
            "feasible": False,
            "score": None,
        }
    minutes = measured_s / 60.0
    ppm = pieces_delivered / minutes
    if pieces_delivered > 0:
        dd_rate = double_drops / pieces_delivered
    else:
        dd_rate = 1.0 if double_drops > 0 else 0.0
    feasible = dd_rate <= max_double_drop_rate
    score: float | None = None
    if feasible:
        score = round(ppm - incident_weight * (incidents / minutes), 3)
    return {
        "pieces_per_min": round(ppm, 3),
        "double_drop_rate": round(dd_rate, 4),
        "feasible": feasible,
        "score": score,
    }


class FeederAutoTuner:
    def __init__(self, gc: "GlobalConfig"):
        self.gc = gc
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._apply_on_stop: str = "baseline"
        self._run: dict[str, Any] | None = None
        self._settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self._mode: str = "session"
        self._best: dict[str, Any] | None = None
        self._live: dict[str, Any] | None = None
        self._rng = random.Random()

    def start(self, raw_settings: dict[str, Any] | None) -> dict[str, Any]:
        _ensureStartupRecovery()
        if _background_state and _background_state.get("enabled"):
            raise RuntimeError(
                "background exploration is enabled — disable it before starting a tuning session"
            )
        from toml_config import getPulsePerceptionConfig

        self._startRun(
            normalizeSettings(raw_settings), getPulsePerceptionConfig(), mode="session"
        )
        return self.status()

    def enableBackground(self, raw_settings: dict[str, Any] | None) -> dict[str, Any]:
        global _background_state
        _ensureStartupRecovery()
        import local_state
        from toml_config import getPulsePerceptionConfig

        with self._lock:
            if self._thread is not None and self._thread.is_alive() and self._mode == "session":
                raise RuntimeError("a tuning session is running — stop it first")
        settings = normalizeSettings(raw_settings)
        # Background sampling is pure exploration: the goal is coverage of the
        # space for the dataset, not convergence.
        settings["explore_probability"] = 1.0
        settings["max_trials"] = 0
        baseline = getPulsePerceptionConfig()
        record = {
            "enabled": True,
            "settings": settings,
            "baseline_config": baseline,
            "enabled_at": time.time(),
        }
        local_state.setFeederAutotuneBackground(record)
        _background_state = record
        try:
            self._startRun(settings, baseline, mode="background")
        except RuntimeError:
            pass
        return self.status()

    def resumeBackground(self, record: dict[str, Any]) -> None:
        settings = normalizeSettings(record.get("settings"))
        settings["explore_probability"] = 1.0
        settings["max_trials"] = 0
        baseline = record.get("baseline_config")
        if not isinstance(baseline, dict) or not baseline:
            return
        try:
            self._startRun(settings, baseline, mode="background")
        except RuntimeError:
            pass

    def disableBackground(self, apply: str = "baseline") -> dict[str, Any]:
        global _background_state
        import local_state

        local_state.setFeederAutotuneBackground(None)
        _background_state = None
        with self._lock:
            if self._thread is not None and self._thread.is_alive() and self._mode == "background":
                if apply in ("baseline", "best", "keep"):
                    self._apply_on_stop = apply
                self._stop_event.set()
        return self.status()

    def _startRun(
        self, settings: dict[str, Any], baseline: dict[str, Any], *, mode: str
    ) -> None:
        import local_state

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("auto-tune is already running")
            run = local_state.createFeederAutotuneRun(baseline, {**settings, "mode": mode})
            if run is None:
                raise RuntimeError("failed to create auto-tune run")
            self._run = run
            self._settings = settings
            self._mode = mode
            self._best = None
            self._live = None
            self._apply_on_stop = "baseline"
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._threadMain, name="feeder-autotune", daemon=True
            )
            self._thread.start()

    def stop(self, apply: str = "baseline") -> dict[str, Any]:
        with self._lock:
            if apply in ("baseline", "best", "keep"):
                self._apply_on_stop = apply
            self._stop_event.set()
        return self.status()

    def status(self) -> dict[str, Any]:
        _ensureStartupRecovery()
        import local_state

        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            run = dict(self._run) if self._run is not None else None
            live = dict(self._live) if self._live is not None else None
            best = dict(self._best) if self._best is not None else None
            settings = dict(self._settings)
            mode = self._mode
        trials: list[dict[str, Any]] = []
        if run is not None:
            trials = local_state.listFeederAutotuneTrials(run["id"], limit=200)
            fresh = local_state.getFeederAutotuneRun(run["id"])
            if fresh is not None:
                run = fresh
        background = _background_state if _background_state else None
        return {
            "state": "running" if running else "idle",
            "mode": mode if running else None,
            "machine_running": self._machineRunning(),
            "run": run,
            "settings": settings,
            "current_trial": live,
            "best_trial": best,
            "trials": trials,
            "tunable_params": TUNABLE_PARAMS,
            "background": {
                "enabled": bool(background and background.get("enabled")),
                "enabled_at": background.get("enabled_at") if background else None,
                "settings": background.get("settings") if background else None,
            },
        }

    def _machineRunning(self) -> bool:
        try:
            from server import shared_state

            controller = shared_state.controller_ref
            return bool(
                controller is not None
                and getattr(controller.state, "value", None) == "running"
            )
        except Exception:
            return False

    def _c4DropCount(self) -> int:
        service = getattr(self.gc, "perception_service", None)
        if service is None:
            return 0
        try:
            c4 = service.read_states().get(4)
        except Exception:
            return 0
        if c4 is None:
            return 0
        return sum(1 for piece in c4.pieces if piece.zone_code == _ZONE_CODE_DROP)

    def _incidentCountBetween(self, start_ts: float, end_ts: float) -> int:
        try:
            import incident_records

            result = incident_records.listIncidents(
                limit=1, date_from=start_ts, date_to=end_ts
            )
            return int(result.get("total") or 0)
        except Exception:
            return 0

    def _applyParams(self, params: dict[str, Any]) -> None:
        from toml_config import setPulsePerceptionConfig

        setPulsePerceptionConfig(params)

    def _threadMain(self) -> None:
        import local_state

        run = self._run
        settings = self._settings
        if run is None:
            return
        run_id = run["id"]
        baseline = run.get("baseline_config") or {}
        baseline_tuned = {
            key: baseline.get(key)
            for key in settings["param_keys"]
            if key in baseline
        }
        final_status = "finished"
        try:
            trial_index = 0
            while not self._stop_event.is_set():
                max_trials = int(settings.get("max_trials") or 0)
                if max_trials > 0 and trial_index >= max_trials:
                    break
                if trial_index == 0 and baseline_tuned:
                    kind, params = "baseline", dict(baseline_tuned)
                else:
                    best_params = self._best["params"] if self._best else None
                    kind, params = sampleCandidate(
                        settings["param_keys"],
                        best_params,
                        self._rng,
                        explore_probability=settings["explore_probability"],
                        sigma_fraction=settings["sigma_fraction"],
                    )
                self._runTrial(run_id, trial_index, kind, params, settings)
                trial_index += 1
        except Exception as exc:
            final_status = "error"
            try:
                self.gc.logger.warning(f"FeederAutotune: run failed: {exc}")
            except Exception:
                pass
        finally:
            try:
                apply = self._apply_on_stop
                if apply == "best" and self._best is not None:
                    self._applyParams(self._best["params"])
                elif apply == "baseline" and isinstance(baseline, dict) and baseline:
                    self._applyParams(baseline)
                local_state.finishFeederAutotuneRun(run_id, final_status)
            except Exception:
                pass
            with self._lock:
                self._live = None

    def _runTrial(
        self,
        run_id: str,
        trial_index: int,
        kind: str,
        params: dict[str, Any],
        settings: dict[str, Any],
    ) -> None:
        import local_state

        self._applyParams(params)
        trial_id = local_state.insertFeederAutotuneTrial(run_id, trial_index, kind, params)
        self.gc.logger.info(
            f"FeederAutotune: trial {trial_index} ({kind}) started params={params}"
        )

        # The flow re-reads its config from disk on a 1s TTL; wait for the
        # candidate to actually be live before measuring.
        settle_deadline = time.monotonic() + float(settings["settle_s"]) + 1.0
        while time.monotonic() < settle_deadline and not self._stop_event.is_set():
            time.sleep(_TICK_S)

        duration = float(settings["trial_duration_s"])
        measured = 0.0
        double_drops = 0
        double_active = False
        pieces_at_start = dispenseCount()
        wall_start = time.time()
        last_tick = time.monotonic()

        while not self._stop_event.is_set() and measured < duration:
            time.sleep(_TICK_S)
            now = time.monotonic()
            dt = now - last_tick
            last_tick = now
            if not self._machineRunning():
                self._updateLive(trial_id, trial_index, kind, params, measured, duration, pieces_at_start, double_drops, waiting=True)
                continue
            measured += dt
            drop_count = self._c4DropCount()
            if drop_count >= _DOUBLE_DROP_PIECES:
                if not double_active:
                    double_drops += 1
                    double_active = True
            else:
                double_active = False
            self._updateLive(trial_id, trial_index, kind, params, measured, duration, pieces_at_start, double_drops, waiting=False)

        pieces = dispenseCount() - pieces_at_start
        incidents = self._incidentCountBetween(wall_start, time.time())
        metrics = computeTrialMetrics(
            measured_s=measured,
            pieces_delivered=pieces,
            incidents=incidents,
            double_drops=double_drops,
            incident_weight=float(settings["incident_weight"]),
            max_double_drop_rate=float(settings["max_double_drop_rate"]),
        )
        aborted = measured < 0.5 * duration
        local_state.finalizeFeederAutotuneTrial(
            trial_id,
            status="aborted" if aborted else "done",
            measured_s=measured,
            pieces_delivered=pieces,
            incidents=incidents,
            double_drops=double_drops,
            pieces_per_min=metrics["pieces_per_min"],
            double_drop_rate=metrics["double_drop_rate"],
            feasible=metrics["feasible"],
            score=None if aborted else metrics["score"],
        )
        self.gc.logger.info(
            f"FeederAutotune: trial {trial_index} ({kind}) done measured={measured:.0f}s "
            f"pieces={pieces} incidents={incidents} double_drops={double_drops} "
            f"ppm={metrics['pieces_per_min']} dd_rate={metrics['double_drop_rate']} "
            f"feasible={metrics['feasible']} score={metrics['score']} aborted={aborted}"
        )
        score = metrics["score"]
        if not aborted and metrics["feasible"] and score is not None:
            with self._lock:
                if self._best is None or score > self._best["score"]:
                    self._best = {
                        "trial_id": trial_id,
                        "trial_index": trial_index,
                        "kind": kind,
                        "params": dict(params),
                        "score": score,
                        "pieces_per_min": metrics["pieces_per_min"],
                        "double_drop_rate": metrics["double_drop_rate"],
                        "measured_s": round(measured, 1),
                        "pieces_delivered": pieces,
                        "incidents": incidents,
                        "double_drops": double_drops,
                    }
                    local_state.setFeederAutotuneBestTrial(run_id, trial_id)

    def _updateLive(
        self,
        trial_id: int,
        trial_index: int,
        kind: str,
        params: dict[str, Any],
        measured: float,
        duration: float,
        pieces_at_start: int,
        double_drops: int,
        *,
        waiting: bool,
    ) -> None:
        with self._lock:
            self._live = {
                "trial_id": trial_id,
                "trial_index": trial_index,
                "kind": kind,
                "params": params,
                "measured_s": round(measured, 1),
                "duration_s": duration,
                "pieces_delivered": dispenseCount() - pieces_at_start,
                "double_drops": double_drops,
                "waiting_for_machine": waiting,
            }


def currentTrialInfo() -> dict[str, Any] | None:
    """Light snapshot for the control-data capture stream: which tuner mode is
    active (if any) and the live trial. None when no tuner exists yet."""
    tuner = _tuner
    if tuner is None:
        return None
    with tuner._lock:
        running = tuner._thread is not None and tuner._thread.is_alive()
        return {
            "mode": tuner._mode if running else None,
            "trial": dict(tuner._live) if tuner._live is not None else None,
        }


_tuner_lock = threading.Lock()
_tuner: FeederAutoTuner | None = None


def getAutoTuner() -> FeederAutoTuner:
    global _tuner
    with _tuner_lock:
        if _tuner is None:
            from server import shared_state

            gc = shared_state.gc_ref
            if gc is None:
                raise RuntimeError("backend not initialized")
            _tuner = FeederAutoTuner(gc)
        return _tuner
