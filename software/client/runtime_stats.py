import statistics
import time
from dataclasses import dataclass
from typing import Any

MAX_TIMING_SAMPLES = 5000
MAX_STATE_TIMELINE_EVENTS = 5000
MAX_FEEDER_SIGNAL_TIMELINE_EVENTS = 10000
MAX_FEEDER_COMBO_TIMELINE_EVENTS = 5000

FEEDER_BLOCKER_SIGNAL_NAMES = [
    "wait_chute",
    "wait_classification_ready",
    "wait_ch2_dropzone_clear",
    "wait_ch3_dropzone_clear",
    "wait_stepper_busy",
]


def _appendSample(samples: list[float], value: float) -> None:
    samples.append(value)
    if len(samples) > MAX_TIMING_SAMPLES:
        del samples[0]


def _calcSummary(samples: list[float]) -> dict[str, float | int]:
    if not samples:
        return {"n": 0}
    values = sorted(samples)
    n = len(values)
    p90_idx = min(n - 1, int(n * 0.9))
    return {
        "n": n,
        "avg_s": float(statistics.mean(values)),
        "med_s": float(statistics.median(values)),
        "p90_s": float(values[p90_idx]),
        "min_s": float(values[0]),
        "max_s": float(values[-1]),
    }


def _calcValueSummary(samples: list[float]) -> dict[str, float | int]:
    if not samples:
        return {"n": 0}
    values = sorted(samples)
    n = len(values)
    p90_idx = min(n - 1, int(n * 0.9))
    return {
        "n": n,
        "avg": float(statistics.mean(values)),
        "med": float(statistics.median(values)),
        "p90": float(values[p90_idx]),
        "min": float(values[0]),
        "max": float(values[-1]),
    }


@dataclass
class _PulseCounts:
    attempts: int = 0
    sent: int = 0
    busy_skip: int = 0
    failed: int = 0


class RuntimeStatsCollector:
    def __init__(self) -> None:
        self._lifecycle_state = "initializing"
        self._is_running = False
        self._running_total_s = 0.0
        self._running_started_at_monotonic: float | None = None
        self._piece_by_uuid: dict[str, dict[str, Any]] = {}
        self._pulse_counts: dict[str, _PulseCounts] = {}
        self._ch2_clear_wait_start_mono: float | None = None
        self._ch3_clear_wait_start_mono: float | None = None
        self._ch3_held_start_mono: float | None = None
        self._ch2_clear_to_ch1_pulse_s: list[float] = []
        self._ch3_clear_to_ch2_pulse_s: list[float] = []
        self._ch3_precise_held_s: list[float] = []
        self._ch3_precise_held_count = 0
        self._skip_counts: dict[str, int] = {}
        self._blocked_reason_counts: dict[str, int] = {}
        self._state_current: dict[str, dict[str, Any]] = {}
        self._state_totals_s: dict[str, dict[str, float]] = {}
        self._state_transition_counts: dict[str, dict[str, int]] = {}
        self._state_timeline: list[dict[str, Any]] = []
        self._feeder_signal_current: dict[str, bool] = {}
        self._feeder_signal_started_at_monotonic: dict[str, float] = {}
        self._feeder_signal_totals_s: dict[str, float] = {}
        self._feeder_signal_timeline: list[dict[str, Any]] = []
        self._feeder_blocker_combo_current: tuple[str, ...] = tuple()
        self._feeder_blocker_combo_entered_at_monotonic: float | None = None
        self._feeder_blocker_combo_totals_s: dict[str, float] = {}
        self._feeder_blocker_combo_timeline: list[dict[str, Any]] = []
        self._last_updated_at = time.time()

    def setLifecycleState(
        self,
        lifecycle_state: str,
        now_wall: float | None = None,
        now_monotonic: float | None = None,
    ) -> None:
        now_wall = time.time() if now_wall is None else now_wall
        now_monotonic = time.monotonic() if now_monotonic is None else now_monotonic
        if lifecycle_state == self._lifecycle_state:
            return

        was_running = self._is_running
        self._lifecycle_state = lifecycle_state
        self._is_running = lifecycle_state == "running"
        self._last_updated_at = now_wall

        if was_running and not self._is_running:
            if self._running_started_at_monotonic is not None:
                self._running_total_s += max(
                    0.0, now_monotonic - self._running_started_at_monotonic
                )
                self._running_started_at_monotonic = None

            for machine, current in self._state_current.items():
                prev_state = str(current.get("state"))
                entered_at = float(current.get("entered_at_monotonic", now_monotonic))
                elapsed_s = max(0.0, now_monotonic - entered_at)
                machine_totals = self._state_totals_s.get(machine)
                if machine_totals is None:
                    machine_totals = {}
                    self._state_totals_s[machine] = machine_totals
                machine_totals[prev_state] = machine_totals.get(prev_state, 0.0) + elapsed_s
                current["entered_at_monotonic"] = now_monotonic
                current["entered_at_wall"] = now_wall

            if self._ch3_held_start_mono is not None:
                held_s = now_monotonic - self._ch3_held_start_mono
                if held_s >= 0:
                    _appendSample(self._ch3_precise_held_s, held_s)
                self._ch3_held_start_mono = None

            self._ch2_clear_wait_start_mono = None
            self._ch3_clear_wait_start_mono = None
            self._flushFeederSignals(now_wall, now_monotonic)

        if (not was_running) and self._is_running:
            self._running_started_at_monotonic = now_monotonic
            for current in self._state_current.values():
                current["entered_at_monotonic"] = now_monotonic
                current["entered_at_wall"] = now_wall

    def observeKnownObject(self, obj: dict[str, Any]) -> None:
        if not self._is_running:
            return
        obj_uuid = obj.get("uuid")
        if not obj_uuid:
            return
        current = self._piece_by_uuid.get(obj_uuid, {})
        current.update(obj)
        self._piece_by_uuid[obj_uuid] = current
        self._last_updated_at = time.time()

    def observeFeederState(
        self,
        now_monotonic: float,
        ch2_dropzone_occupied: bool,
        ch3_dropzone_occupied: bool,
        can_run: bool,
        classification_ready: bool,
        ch2_action: str,
        ch3_action: str,
    ) -> None:
        if not self._is_running:
            return
        self._last_updated_at = time.time()

        if ch2_dropzone_occupied:
            self._ch2_clear_wait_start_mono = None
            self._bumpSkip("ch1_blocked_by_ch2_dropzone")
        elif self._ch2_clear_wait_start_mono is None:
            self._ch2_clear_wait_start_mono = now_monotonic

        if ch3_dropzone_occupied:
            self._ch3_clear_wait_start_mono = None
            self._bumpSkip("ch2_blocked_by_ch3_dropzone")
        elif self._ch3_clear_wait_start_mono is None:
            self._ch3_clear_wait_start_mono = now_monotonic

        ch3_precise_held = (not classification_ready) and ch3_action == "precise"
        if ch3_precise_held and self._ch3_held_start_mono is None:
            self._ch3_held_start_mono = now_monotonic
            self._ch3_precise_held_count += 1
        elif not ch3_precise_held and self._ch3_held_start_mono is not None:
            held_s = now_monotonic - self._ch3_held_start_mono
            if held_s >= 0:
                _appendSample(self._ch3_precise_held_s, held_s)
            self._ch3_held_start_mono = None

        if not can_run:
            self._bumpSkip("all_channels_blocked_by_chute")
        if ch3_action == "precise" and not classification_ready:
            self._bumpSkip("ch3_precise_held_for_carousel")

    def observePulse(self, label: str, status: str, now_monotonic: float) -> None:
        if not self._is_running:
            return
        counts = self._pulse_counts.get(label)
        if counts is None:
            counts = _PulseCounts()
            self._pulse_counts[label] = counts
        counts.attempts += 1
        if status == "sent":
            counts.sent += 1
        elif status == "busy":
            counts.busy_skip += 1
        elif status == "failed":
            counts.failed += 1

        if status != "sent":
            return

        if label == "ch1" and self._ch2_clear_wait_start_mono is not None:
            wait_s = now_monotonic - self._ch2_clear_wait_start_mono
            if wait_s >= 0:
                _appendSample(self._ch2_clear_to_ch1_pulse_s, wait_s)
            self._ch2_clear_wait_start_mono = None

        if (label == "ch2_normal" or label == "ch2_precise") and self._ch3_clear_wait_start_mono is not None:
            wait_s = now_monotonic - self._ch3_clear_wait_start_mono
            if wait_s >= 0:
                _appendSample(self._ch3_clear_to_ch2_pulse_s, wait_s)
            self._ch3_clear_wait_start_mono = None

    def _comboKey(self, combo: tuple[str, ...]) -> str:
        if not combo:
            return "none"
        return "+".join(combo)

    def _flushFeederSignals(self, now_wall: float, now_monotonic: float) -> None:
        signal_names = list(self._feeder_signal_current.keys())
        for signal_name in signal_names:
            if not self._feeder_signal_current.get(signal_name, False):
                continue
            entered_at = self._feeder_signal_started_at_monotonic.get(signal_name)
            if entered_at is not None:
                elapsed_s = max(0.0, now_monotonic - entered_at)
                self._feeder_signal_totals_s[signal_name] = (
                    self._feeder_signal_totals_s.get(signal_name, 0.0) + elapsed_s
                )
            self._feeder_signal_current[signal_name] = False
            self._feeder_signal_started_at_monotonic.pop(signal_name, None)
            self._feeder_signal_timeline.append(
                {
                    "ts": now_wall,
                    "signal": signal_name,
                    "active": False,
                }
            )
            if len(self._feeder_signal_timeline) > MAX_FEEDER_SIGNAL_TIMELINE_EVENTS:
                del self._feeder_signal_timeline[0]

        if self._feeder_blocker_combo_entered_at_monotonic is not None:
            combo_key = self._comboKey(self._feeder_blocker_combo_current)
            elapsed_s = max(
                0.0, now_monotonic - self._feeder_blocker_combo_entered_at_monotonic
            )
            self._feeder_blocker_combo_totals_s[combo_key] = (
                self._feeder_blocker_combo_totals_s.get(combo_key, 0.0) + elapsed_s
            )
            self._feeder_blocker_combo_timeline.append(
                {
                    "ts": now_wall,
                    "combo": "none",
                }
            )
            if len(self._feeder_blocker_combo_timeline) > MAX_FEEDER_COMBO_TIMELINE_EVENTS:
                del self._feeder_blocker_combo_timeline[0]
        self._feeder_blocker_combo_current = tuple()
        self._feeder_blocker_combo_entered_at_monotonic = None

    def observeFeederSignals(
        self,
        signals: dict[str, bool],
        now_wall: float | None = None,
        now_monotonic: float | None = None,
    ) -> None:
        if not self._is_running:
            return
        now_wall = time.time() if now_wall is None else now_wall
        now_monotonic = time.monotonic() if now_monotonic is None else now_monotonic
        self._last_updated_at = now_wall

        signal_names = set(self._feeder_signal_current.keys())
        signal_names.update(signals.keys())
        for signal_name in signal_names:
            next_active = bool(signals.get(signal_name, False))
            prev_active = bool(self._feeder_signal_current.get(signal_name, False))
            if next_active == prev_active:
                continue

            if next_active:
                self._feeder_signal_started_at_monotonic[signal_name] = now_monotonic
            else:
                entered_at = self._feeder_signal_started_at_monotonic.get(signal_name)
                if entered_at is not None:
                    elapsed_s = max(0.0, now_monotonic - entered_at)
                    self._feeder_signal_totals_s[signal_name] = (
                        self._feeder_signal_totals_s.get(signal_name, 0.0) + elapsed_s
                    )
                self._feeder_signal_started_at_monotonic.pop(signal_name, None)

            self._feeder_signal_current[signal_name] = next_active
            self._feeder_signal_timeline.append(
                {
                    "ts": now_wall,
                    "signal": signal_name,
                    "active": next_active,
                }
            )
            if len(self._feeder_signal_timeline) > MAX_FEEDER_SIGNAL_TIMELINE_EVENTS:
                del self._feeder_signal_timeline[0]

        blocker_combo = tuple(
            sorted(
                signal_name
                for signal_name in FEEDER_BLOCKER_SIGNAL_NAMES
                if self._feeder_signal_current.get(signal_name, False)
            )
        )
        if blocker_combo == self._feeder_blocker_combo_current:
            return

        if self._feeder_blocker_combo_entered_at_monotonic is not None:
            prev_key = self._comboKey(self._feeder_blocker_combo_current)
            elapsed_s = max(
                0.0, now_monotonic - self._feeder_blocker_combo_entered_at_monotonic
            )
            self._feeder_blocker_combo_totals_s[prev_key] = (
                self._feeder_blocker_combo_totals_s.get(prev_key, 0.0) + elapsed_s
            )

        self._feeder_blocker_combo_current = blocker_combo
        self._feeder_blocker_combo_entered_at_monotonic = now_monotonic
        self._feeder_blocker_combo_timeline.append(
            {
                "ts": now_wall,
                "combo": self._comboKey(blocker_combo),
            }
        )
        if len(self._feeder_blocker_combo_timeline) > MAX_FEEDER_COMBO_TIMELINE_EVENTS:
            del self._feeder_blocker_combo_timeline[0]

    def _bumpSkip(self, reason: str) -> None:
        self._skip_counts[reason] = self._skip_counts.get(reason, 0) + 1

    def observeBlockedReason(self, machine: str, reason: str) -> None:
        if not self._is_running:
            return
        key = f"{machine}.{reason}"
        self._blocked_reason_counts[key] = self._blocked_reason_counts.get(key, 0) + 1
        self._last_updated_at = time.time()

    def observeStateTransition(
        self,
        machine: str,
        from_state: str | None,
        to_state: str,
        now_wall: float | None = None,
        now_monotonic: float | None = None,
    ) -> None:
        now_wall = time.time() if now_wall is None else now_wall
        now_monotonic = time.monotonic() if now_monotonic is None else now_monotonic
        self._last_updated_at = now_wall

        current = self._state_current.get(machine)
        if current is not None and self._is_running:
            prev_state = str(current.get("state"))
            entered_at = float(current.get("entered_at_monotonic", now_monotonic))
            elapsed_s = max(0.0, now_monotonic - entered_at)
            machine_totals = self._state_totals_s.get(machine)
            if machine_totals is None:
                machine_totals = {}
                self._state_totals_s[machine] = machine_totals
            machine_totals[prev_state] = machine_totals.get(prev_state, 0.0) + elapsed_s

        self._state_current[machine] = {
            "state": to_state,
            "entered_at_monotonic": now_monotonic,
            "entered_at_wall": now_wall,
        }

        machine_transitions = self._state_transition_counts.get(machine)
        if machine_transitions is None:
            machine_transitions = {}
            self._state_transition_counts[machine] = machine_transitions
        if self._is_running:
            edge = f"{from_state or 'none'}->{to_state}"
            machine_transitions[edge] = machine_transitions.get(edge, 0) + 1

            self._state_timeline.append(
                {
                    "ts": now_wall,
                    "machine": machine,
                    "from_state": from_state,
                    "to_state": to_state,
                }
            )
            if len(self._state_timeline) > MAX_STATE_TIMELINE_EVENTS:
                del self._state_timeline[0]

    def snapshot(self) -> dict[str, Any]:
        now = time.time()

        def addDuration(
            out: list[float],
            piece: dict[str, Any],
            start_key: str,
            end_key: str,
        ) -> None:
            start = piece.get(start_key)
            end = piece.get(end_key)
            if start is None or end is None:
                return
            if end >= start:
                out.append(float(end - start))

        all_pieces = list(self._piece_by_uuid.values())
        counts = {
            "pieces_seen": len(all_pieces),
            "classified": 0,
            "unknown": 0,
            "not_found": 0,
            "multi_drop_fail": 0,
            "distributed": 0,
            "stage_created": 0,
            "stage_distributing": 0,
            "stage_distributed": 0,
        }
        timing_samples: dict[str, list[float]] = {
            "feed_ready_to_landed_s": [],
            "created_to_classified_s": [],
            "created_to_distributed_s": [],
            "found_to_rotated_s": [],
            "found_to_snap_done_s": [],
            "found_to_next_baseline_s": [],
            "found_to_next_ready_s": [],
            "rotate_only_s": [],
            "snap_window_s": [],
            "target_selected_to_positioned_s": [],
            "motion_started_to_positioned_s": [],
            "ch2_clear_to_ch1_pulse_s": list(self._ch2_clear_to_ch1_pulse_s),
            "ch3_clear_to_ch2_pulse_s": list(self._ch3_clear_to_ch2_pulse_s),
            "ch3_precise_held_s": list(self._ch3_precise_held_s),
        }

        for piece in all_pieces:
            status = piece.get("classification_status")
            stage = piece.get("stage")
            if status == "classified":
                counts["classified"] += 1
            elif status == "unknown":
                counts["unknown"] += 1
            elif status == "not_found":
                counts["not_found"] += 1
            elif status == "multi_drop_fail":
                counts["multi_drop_fail"] += 1
            if stage == "created":
                counts["stage_created"] += 1
            elif stage == "distributing":
                counts["stage_distributing"] += 1
            elif stage == "distributed":
                counts["stage_distributed"] += 1
            if piece.get("distributed_at") is not None:
                counts["distributed"] += 1

            detect_confirmed_at = piece.get("carousel_detected_confirmed_at") or piece.get("created_at")

            addDuration(timing_samples["feed_ready_to_landed_s"], piece, "feeding_started_at", "created_at")
            addDuration(timing_samples["created_to_classified_s"], piece, "created_at", "classified_at")
            addDuration(timing_samples["created_to_distributed_s"], piece, "created_at", "distributed_at")
            if detect_confirmed_at is not None:
                detect_piece = {"start": detect_confirmed_at}
                detect_piece.update(piece)
                addDuration(timing_samples["found_to_rotated_s"], detect_piece, "start", "carousel_rotated_at")
                addDuration(timing_samples["found_to_snap_done_s"], detect_piece, "start", "carousel_snapping_completed_at")
                addDuration(timing_samples["found_to_next_baseline_s"], detect_piece, "start", "carousel_next_baseline_captured_at")
                addDuration(timing_samples["found_to_next_ready_s"], detect_piece, "start", "carousel_next_ready_at")
            addDuration(timing_samples["rotate_only_s"], piece, "carousel_rotate_started_at", "carousel_rotated_at")
            addDuration(timing_samples["snap_window_s"], piece, "carousel_snapping_started_at", "carousel_snapping_completed_at")
            addDuration(
                timing_samples["target_selected_to_positioned_s"],
                piece,
                "distribution_target_selected_at",
                "distribution_positioned_at",
            )
            addDuration(
                timing_samples["motion_started_to_positioned_s"],
                piece,
                "distribution_motion_started_at",
                "distribution_positioned_at",
            )

        timings = {k: _calcSummary(v) for k, v in timing_samples.items()}
        running_time_s = self._running_total_s
        if self._is_running and self._running_started_at_monotonic is not None:
            running_time_s += max(
                0.0, time.monotonic() - self._running_started_at_monotonic
            )

        distributed_timestamps: list[float] = []
        for piece in all_pieces:
            distributed_at = piece.get("distributed_at")
            if distributed_at is not None:
                distributed_timestamps.append(float(distributed_at))
        distributed_timestamps.sort()
        inter_piece_ppm_samples: list[float] = []
        for idx in range(1, len(distributed_timestamps)):
            dt_s = distributed_timestamps[idx] - distributed_timestamps[idx - 1]
            if dt_s > 0:
                inter_piece_ppm_samples.append(60.0 / dt_s)
        throughput_overall_ppm: float | None = None
        if running_time_s > 0 and counts["distributed"] > 0:
            throughput_overall_ppm = (float(counts["distributed"]) * 60.0) / running_time_s
        pulse_counts = {
            k: {
                "attempts": v.attempts,
                "sent": v.sent,
                "busy_skip": v.busy_skip,
                "failed": v.failed,
            }
            for k, v in sorted(self._pulse_counts.items())
        }
        feeder_signal_totals_s = dict(self._feeder_signal_totals_s)
        for signal_name, is_active in self._feeder_signal_current.items():
            if not is_active:
                continue
            entered_at = self._feeder_signal_started_at_monotonic.get(signal_name)
            if entered_at is None:
                continue
            feeder_signal_totals_s[signal_name] = feeder_signal_totals_s.get(
                signal_name, 0.0
            ) + max(0.0, time.monotonic() - entered_at)

        feeder_combo_totals_s = dict(self._feeder_blocker_combo_totals_s)
        if self._is_running and self._feeder_blocker_combo_entered_at_monotonic is not None:
            combo_key = self._comboKey(self._feeder_blocker_combo_current)
            feeder_combo_totals_s[combo_key] = feeder_combo_totals_s.get(combo_key, 0.0) + max(
                0.0, time.monotonic() - self._feeder_blocker_combo_entered_at_monotonic
            )


        state_machines: dict[str, Any] = {}
        for machine, current in self._state_current.items():
            totals = dict(self._state_totals_s.get(machine, {}))
            current_state = str(current.get("state"))
            if self._is_running:
                entered_at_mono = float(current.get("entered_at_monotonic", time.monotonic()))
                totals[current_state] = totals.get(current_state, 0.0) + max(
                    0.0, time.monotonic() - entered_at_mono
                )
            total_s = sum(totals.values())
            shares: dict[str, float] = {}
            if total_s > 0:
                for state_name, state_s in totals.items():
                    shares[state_name] = (state_s / total_s) * 100.0
            state_machines[machine] = {
                "current_state": current_state,
                "entered_at": current.get("entered_at_wall"),
                "state_time_s": totals,
                "state_share_pct": shares,
                "transitions": dict(
                    sorted(self._state_transition_counts.get(machine, {}).items())
                ),
            }

        return {
            "updated_at": now,
            "lifecycle_state": self._lifecycle_state,
            "is_running": self._is_running,
            "counts": counts,
            "timings": timings,
            "throughput": {
                "running_time_s": running_time_s,
                "distributed_count": counts["distributed"],
                "overall_ppm": throughput_overall_ppm,
                "inter_piece_ppm": _calcValueSummary(inter_piece_ppm_samples),
            },
            "feeder": {
                "pulse_counts": pulse_counts,
                "skip_counts": dict(sorted(self._skip_counts.items())),
                "ch3_precise_held_count": self._ch3_precise_held_count,
                "signals_current": dict(sorted(self._feeder_signal_current.items())),
                "signal_time_s": dict(sorted(feeder_signal_totals_s.items())),
                "signal_timeline_recent": list(self._feeder_signal_timeline),
                "blocker_combo_time_s": dict(sorted(feeder_combo_totals_s.items())),
                "blocker_combo_timeline_recent": list(self._feeder_blocker_combo_timeline),
            },
            "state_machines": state_machines,
            "timeline_recent": list(self._state_timeline),
            "blocked_reason_counts": dict(sorted(self._blocked_reason_counts.items())),
            "pieces_cached": len(self._piece_by_uuid),
            "last_update_age_s": max(0.0, now - self._last_updated_at),
        }
