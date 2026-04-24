import statistics
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

MAX_TIMING_SAMPLES = 5000
MAX_STATE_TIMELINE_EVENTS = 5000
MAX_FEEDER_SIGNAL_TIMELINE_EVENTS = 10000
MAX_FEEDER_COMBO_TIMELINE_EVENTS = 5000
MAX_CHANNEL_EXIT_EVENTS = 10000
MAX_KNOWN_OBJECT_LOOKUP_ENTRIES = 1000

FEEDER_BLOCKER_SIGNAL_NAMES = [
    "wait_chute",
    "wait_classification_ready",
    "wait_ch2_dropzone_clear",
    "wait_ch3_dropzone_clear",
    "wait_stepper_busy",
]

CLASSIFICATION_ACTIVE_OCCUPANCY_STATES = {
    "classification_channel.rotate_pipeline",
    "classification_channel.hood_dwell",
    "classification_channel.drop_commit",
    "classification_channel.exit_release_shimmy",
    "classification_channel.wait_transport_motion_complete",
}


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


def _calcPpm(count: int, duration_s: float) -> float | None:
    if count <= 0 or duration_s <= 0:
        return None
    return (float(count) * 60.0) / float(duration_s)


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
        # Bounded LRU of every KnownObject payload we've ever observed in this
        # process, keyed by uuid. Populated unconditionally (even when the
        # machine is not running) so the frontend can look up a piece by
        # uuid on the detail page long after it ages out of the 10-item WS
        # ring buffer. Evicted FIFO once the cap is reached.
        self._known_object_lookup: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
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
        self._channel_exit_events: list[dict[str, Any]] = []
        self._recognizer_counts: dict[str, int] = {
            "recognize_fired_total": 0,
            "recognize_skipped_no_crops": 0,
            "recognize_skipped_no_carousel_crops": 0,
            "recognize_skipped_not_on_carousel": 0,
            "recognize_skipped_carousel_quota": 0,
            "recognize_skipped_carousel_dwell": 0,
            "recognize_skipped_carousel_traversal": 0,
            "recognize_c3_slots_used": 0,
            "brickognize_empty_result": 0,
            "brickognize_timeout_total": 0,
        }
        self._handoff_ghost_rejected_total: int = 0
        self._handoff_embedding_rebind_total: int = 0
        self._handoff_stale_pending_dropped_total: int = 0
        self._multi_drop_leader_wins_total: int = 0
        self._classification_zone_lost_total: int = 0
        self._exit_wiggle_triggered_c2_total: int = 0
        self._exit_wiggle_triggered_c3_total: int = 0
        self._c2_idle_skipped_no_cluster_total: int = 0
        self._tracker_id_switch_suspect_total: int = 0
        self._all_bins_cleared_after_s: float | None = None
        self._layer_bins_cleared_after_s: dict[int, float] = {}
        self._bin_cleared_after_s: dict[tuple[int, int, int], float] = {}
        self._servo_bus_offline_since_ts: float | None = None
        self._bus_provider: Any | None = None
        self._last_updated_at = time.time()

    def setBusProvider(self, bus_provider: Any | None) -> None:
        self._bus_provider = bus_provider

    def setServoBusOffline(self, ts: float | None = None) -> None:
        """Mark the Waveshare servo bus as offline.

        Idempotent — only updates the timestamp on the first fault so the UI
        can display how long the bus has been unreachable without the stamp
        getting reset by repeat observations.
        """
        if self._servo_bus_offline_since_ts is None:
            self._servo_bus_offline_since_ts = float(time.time() if ts is None else ts)
            self._last_updated_at = time.time()

    def clearServoBusOffline(self) -> None:
        """Clear the servo-bus-offline timestamp once the bus recovers."""
        if self._servo_bus_offline_since_ts is not None:
            self._servo_bus_offline_since_ts = None
            self._last_updated_at = time.time()

    @property
    def servo_bus_offline_since_ts(self) -> float | None:
        return self._servo_bus_offline_since_ts

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

    def observeKnownObject(
        self,
        obj: dict[str, Any],
        *,
        count_when_stopped: bool = False,
    ) -> None:
        obj_uuid = obj.get("uuid")
        if not obj_uuid:
            return
        # Keep the long-lived lookup fresh for every observation, even while
        # not running — so the detail page can hydrate a piece by uuid even
        # after lifecycle transitions. LRU-evicted once bounded.
        lookup_entry = self._known_object_lookup.pop(obj_uuid, None)
        if lookup_entry is None:
            lookup_entry = {}
        lookup_entry.update(obj)
        self._known_object_lookup[obj_uuid] = lookup_entry
        while len(self._known_object_lookup) > MAX_KNOWN_OBJECT_LOOKUP_ENTRIES:
            self._known_object_lookup.popitem(last=False)

        if not self._is_running and not count_when_stopped:
            return
        current = self._piece_by_uuid.get(obj_uuid, {})
        current.update(obj)
        self._piece_by_uuid[obj_uuid] = current
        self._last_updated_at = time.time()

        if (
            self._is_running
            and current.get("distributed_at") is not None
            and current.get("destination_bin") is not None
        ):
            try:
                from local_state import record_piece_distribution

                record_piece_distribution(current)
            except Exception:
                pass

    def lookupKnownObject(self, obj_uuid: str) -> dict[str, Any] | None:
        """Return the last observed KnownObject payload for ``obj_uuid``.

        Returns ``None`` if the piece has aged out of the bounded LRU or
        was never observed in this process. Returned dict is a shallow copy
        so the caller can mutate it safely.
        """
        entry = self._known_object_lookup.get(obj_uuid)
        if entry is None:
            return None
        return dict(entry)

    def observeChannelExit(
        self,
        channel: str,
        *,
        exited_at: float | None = None,
        piece_uuid: str | None = None,
        global_id: int | None = None,
        **meta: Any,
    ) -> None:
        if not self._is_running:
            return
        event: dict[str, Any] = {
            "channel": str(channel),
            "exited_at": float(time.time() if exited_at is None else exited_at),
        }
        if piece_uuid:
            event["piece_uuid"] = str(piece_uuid)
        if global_id is not None:
            event["global_id"] = int(global_id)
        for key, value in meta.items():
            if value is not None:
                event[key] = value
        self._channel_exit_events.append(event)
        if len(self._channel_exit_events) > MAX_CHANNEL_EXIT_EVENTS:
            del self._channel_exit_events[0]
        self._last_updated_at = event["exited_at"]

    def observeHandoffGhostReject(self, **_meta: Any) -> None:
        """Increment the cumulative cross-camera ghost-reject counter.

        Called by the handoff manager whenever a downstream claim is rejected
        because the dying upstream track was stationary and the new detection
        landed on the same pixel region — i.e. almost certainly the same
        static detector artefact leaking between cameras. Counted regardless
        of lifecycle state so pre-run ghosts show up too.
        """
        self._handoff_ghost_rejected_total += 1
        self._last_updated_at = time.time()

    def observeHandoffEmbeddingRebind(self, **_meta: Any) -> None:
        """Increment cross-camera embedding-rebind counter.

        Called by the handoff manager when an OSNet cosine-similarity pick
        beat the FIFO head for a pending-bucket claim — i.e. two pieces
        in flight and the physical order swapped vs. FIFO order. Counted
        regardless of lifecycle state to mirror the ghost-reject counter.
        """
        self._handoff_embedding_rebind_total += 1
        self._last_updated_at = time.time()

    def observeHandoffStalePendingDropped(self, **_meta: Any) -> None:
        """Increment cross-camera stale-pending-dropped counter.

        Called by the handoff manager when a pending ``global_id`` is
        discarded because the upstream tracker still has a live track with
        that id — i.e. the piece never physically left, but a coast-death
        prematurely queued the handoff. Dropping the pending prevents a
        downstream track (e.g. the carousel) from misbinding to the still-
        alive upstream piece. Counted regardless of lifecycle state to
        mirror the ghost-reject counter.
        """
        self._handoff_stale_pending_dropped_total += 1
        self._last_updated_at = time.time()

    def observeExitWiggleTriggered(self, channel: str, **_meta: Any) -> None:
        """Increment per-channel exit-zone wiggle trigger counter.

        Called by C2/C3 stations when a piece has been stuck with its bbox
        mostly overlapping the channel's exit-sections and the downstream
        gate is closed, so a short forward/reverse jog is applied to break
        static friction. Counted regardless of lifecycle state.
        """
        if channel == "c2":
            self._exit_wiggle_triggered_c2_total += 1
        elif channel == "c3":
            self._exit_wiggle_triggered_c3_total += 1
        else:
            return
        self._last_updated_at = time.time()

    def observeC2IdleSkippedNoCluster(self, **_meta: Any) -> None:
        """Increment the C2 idle-strategy skipped-no-cluster counter.

        Called by C2Station.run_idle_strategies when the gating conditions
        for the forward/reverse spread jog are all satisfied *except* that
        C2 doesn't actually host a piece-cluster — so the jog would waste
        motion. Counted regardless of lifecycle state to mirror the other
        feeder diagnostic counters.
        """
        self._c2_idle_skipped_no_cluster_total += 1
        self._last_updated_at = time.time()

    def observeTrackerIdSwitchSuspect(self, **_meta: Any) -> None:
        """Increment the tracker id-switch-suspect counter.

        Called by the polar tracker when the Hungarian solver accepts a pair
        whose cosine similarity is very low *and* whose geometric cost is
        high — i.e. the match was made only because there was no better
        pairing available, which is the usual fingerprint of an intra-
        tracker id switch ("piece suddenly becomes another piece"). Counted
        regardless of lifecycle state so warm-up glitches show up too.
        """
        self._tracker_id_switch_suspect_total += 1
        self._last_updated_at = time.time()

    def observeMultiDropLeaderWins(self, **_meta: Any) -> None:
        """Increment the leader-wins spare-the-trailer counter.

        Called by the classification channel whenever a drop-window conflict
        would have flipped both the leader and a trailing interferer to
        ``multi_drop_fail`` under the old "both fail" rule, but the leader
        was classified and the interferer strictly trailing — so we drop
        the leader cleanly and keep the trailer pending for its own cycle.
        Counted regardless of lifecycle state.
        """
        self._multi_drop_leader_wins_total += 1
        self._last_updated_at = time.time()

    def observeClassificationZoneLost(self, **_meta: Any) -> None:
        """Increment the classification-channel stale-zone expiry counter.

        Called by the classification-channel Running state whenever a piece is
        dropped from the transport because its carousel track went stale for
        longer than ``stale_zone_timeout_s`` — usually because the same
        physical piece got re-acquired under a fresh ``global_id`` after a
        brief occlusion. Counted regardless of lifecycle state so pre-run
        glitches show up too.
        """
        self._classification_zone_lost_total += 1
        self._last_updated_at = time.time()

    def clearBinContents(
        self,
        *,
        scope: str,
        layer_index: int | None = None,
        section_index: int | None = None,
        bin_index: int | None = None,
        cleared_at: float | None = None,
    ) -> None:
        cleared_at = time.time() if cleared_at is None else float(cleared_at)
        if scope == "all":
            self._all_bins_cleared_after_s = cleared_at
            self._last_updated_at = cleared_at
            return

        if scope == "layer":
            if layer_index is None:
                raise ValueError("layer_index is required when clearing a layer")
            self._layer_bins_cleared_after_s[int(layer_index)] = cleared_at
            self._last_updated_at = cleared_at
            return

        if scope == "bin":
            if layer_index is None or section_index is None or bin_index is None:
                raise ValueError("layer_index, section_index, and bin_index are required when clearing a bin")
            self._bin_cleared_after_s[(int(layer_index), int(section_index), int(bin_index))] = cleared_at
            self._last_updated_at = cleared_at
            return

        raise ValueError(f"Unsupported bin clear scope: {scope}")

    def _binContentsClearCutoff(
        self,
        *,
        layer_index: int,
        section_index: int,
        bin_index: int,
    ) -> float | None:
        candidates: list[float] = []
        if self._all_bins_cleared_after_s is not None:
            candidates.append(self._all_bins_cleared_after_s)
        layer_cutoff = self._layer_bins_cleared_after_s.get(layer_index)
        if layer_cutoff is not None:
            candidates.append(layer_cutoff)
        bin_cutoff = self._bin_cleared_after_s.get((layer_index, section_index, bin_index))
        if bin_cutoff is not None:
            candidates.append(bin_cutoff)
        if not candidates:
            return None
        return max(candidates)

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

    def observeRecognizerCounter(self, name: str) -> None:
        # Cumulative diagnostic counters for the classification-channel recognizer.
        # Incremented regardless of lifecycle state so baselines capture pre-run
        # warm-up and paused-state timeouts too; snapshots are absolute.
        if name not in self._recognizer_counts:
            return
        self._recognizer_counts[name] = self._recognizer_counts.get(name, 0) + 1
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

    def binContentsSnapshot(self) -> dict[str, Any]:
        bins: dict[str, dict[str, Any]] = {}

        for piece in self._piece_by_uuid.values():
            destination_bin = piece.get("destination_bin")
            if not isinstance(destination_bin, (list, tuple)) or len(destination_bin) != 3:
                continue
            if piece.get("distributed_at") is None:
                continue

            try:
                layer_index = int(destination_bin[0])
                section_index = int(destination_bin[1])
                bin_index = int(destination_bin[2])
            except (TypeError, ValueError):
                continue

            distributed_at = piece.get("distributed_at")
            clear_cutoff = self._binContentsClearCutoff(
                layer_index=layer_index,
                section_index=section_index,
                bin_index=bin_index,
            )
            if (
                clear_cutoff is not None
                and isinstance(distributed_at, (int, float))
                and float(distributed_at) <= clear_cutoff
            ):
                continue

            bin_key = f"{layer_index}:{section_index}:{bin_index}"
            bucket = bins.get(bin_key)
            if bucket is None:
                bucket = {
                    "bin_key": bin_key,
                    "layer_index": layer_index,
                    "section_index": section_index,
                    "bin_index": bin_index,
                    "piece_count": 0,
                    "unique_item_count": 0,
                    "last_distributed_at": None,
                    "items": [],
                    "recent_pieces": [],
                }
                bins[bin_key] = bucket

            bucket["piece_count"] += 1
            if isinstance(distributed_at, (int, float)):
                current_last = bucket.get("last_distributed_at")
                if not isinstance(current_last, (int, float)) or distributed_at > current_last:
                    bucket["last_distributed_at"] = float(distributed_at)

            part_id = piece.get("part_id")
            color_id = piece.get("color_id")
            color_name = piece.get("color_name")
            category_id = piece.get("category_id")
            classification_status = piece.get("classification_status")
            item_key = "|".join(
                [
                    str(part_id or ""),
                    str(color_id or ""),
                    str(category_id or ""),
                    str(classification_status or ""),
                ]
            )

            item = next((existing for existing in bucket["items"] if existing["key"] == item_key), None)
            if item is None:
                item = {
                    "key": item_key,
                    "part_id": part_id,
                    "color_id": color_id,
                    "color_name": color_name,
                    "category_id": category_id,
                    "classification_status": classification_status,
                    "count": 0,
                    "last_distributed_at": None,
                    "thumbnail": piece.get("thumbnail"),
                    "top_image": piece.get("top_image"),
                    "bottom_image": piece.get("bottom_image"),
                    "brickognize_preview_url": piece.get("brickognize_preview_url"),
                }
                bucket["items"].append(item)

            item["count"] += 1
            if isinstance(distributed_at, (int, float)):
                item_last = item.get("last_distributed_at")
                if not isinstance(item_last, (int, float)) or distributed_at > item_last:
                    item["last_distributed_at"] = float(distributed_at)
                    if piece.get("thumbnail"):
                        item["thumbnail"] = piece.get("thumbnail")
                    if piece.get("top_image"):
                        item["top_image"] = piece.get("top_image")
                    if piece.get("bottom_image"):
                        item["bottom_image"] = piece.get("bottom_image")
                    if piece.get("brickognize_preview_url"):
                        item["brickognize_preview_url"] = piece.get("brickognize_preview_url")

            bucket["recent_pieces"].append(
                {
                    "uuid": piece.get("uuid"),
                    "part_id": part_id,
                    "color_id": color_id,
                    "color_name": color_name,
                    "category_id": category_id,
                    "classification_status": classification_status,
                    "distributed_at": float(distributed_at) if isinstance(distributed_at, (int, float)) else None,
                    "thumbnail": piece.get("thumbnail"),
                    "top_image": piece.get("top_image"),
                    "bottom_image": piece.get("bottom_image"),
                    "brickognize_preview_url": piece.get("brickognize_preview_url"),
                }
            )

        for bucket in bins.values():
            bucket["items"].sort(
                key=lambda item: (
                    -int(item.get("count", 0)),
                    -(float(item.get("last_distributed_at") or 0.0)),
                    str(item.get("part_id") or "~"),
                )
            )
            bucket["unique_item_count"] = len(bucket["items"])
            bucket["recent_pieces"].sort(
                key=lambda piece: -(float(piece.get("distributed_at") or 0.0))
            )
            bucket["recent_pieces"] = bucket["recent_pieces"][:8]

        return {
            "bins": sorted(
                bins.values(),
                key=lambda bucket: (
                    int(bucket["layer_index"]),
                    int(bucket["section_index"]),
                    int(bucket["bin_index"]),
                ),
            )
        }

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
        # Unique-piece accounting: with BoTSORT + the current C4 admission
        # policy, the same physical piece may surface as several dossiers
        # across carousel rotations (each rotation creates a new piece_uuid
        # even though the tracked_global_id is stable). ``pieces_seen``
        # therefore counts *classification attempts*, not distinct physical
        # pieces. The UI needs both numbers — show `pieces_seen` alongside
        # `unique_pieces_seen` so operators can distinguish "10 pieces
        # classified this minute" from "1 piece classified 10 times".
        unique_gids: set[int] = set()
        unique_distributed_gids: set[int] = set()
        unique_classified_gids: set[int] = set()
        for piece in all_pieces:
            gid = piece.get("tracked_global_id")
            if not isinstance(gid, int):
                continue
            unique_gids.add(gid)
            if piece.get("distributed_at") is not None:
                unique_distributed_gids.add(gid)
            status = getattr(
                piece.get("classification_status"),
                "value",
                piece.get("classification_status"),
            )
            if status == "classified":
                unique_classified_gids.add(gid)
        counts = {
            "pieces_seen": len(all_pieces),
            "unique_pieces_seen": len(unique_gids),
            "unique_pieces_classified": len(unique_classified_gids),
            "unique_pieces_distributed": len(unique_distributed_gids),
            "classified": 0,
            "unknown": 0,
            "not_found": 0,
            "multi_drop_fail": 0,
            "distributed": 0,
            "stage_created": 0,
            "stage_distributing": 0,
            "stage_distributed": 0,
            "recognize_fired_total": int(self._recognizer_counts.get("recognize_fired_total", 0)),
            "recognize_skipped_no_crops": int(self._recognizer_counts.get("recognize_skipped_no_crops", 0)),
            "recognize_skipped_no_carousel_crops": int(
                self._recognizer_counts.get("recognize_skipped_no_carousel_crops", 0)
            ),
            "recognize_skipped_not_on_carousel": int(
                self._recognizer_counts.get("recognize_skipped_not_on_carousel", 0)
            ),
            "recognize_skipped_carousel_quota": int(
                self._recognizer_counts.get("recognize_skipped_carousel_quota", 0)
            ),
            "recognize_skipped_carousel_dwell": int(
                self._recognizer_counts.get("recognize_skipped_carousel_dwell", 0)
            ),
            "recognize_skipped_carousel_traversal": int(
                self._recognizer_counts.get("recognize_skipped_carousel_traversal", 0)
            ),
            "recognize_c3_slots_used": int(self._recognizer_counts.get("recognize_c3_slots_used", 0)),
            "brickognize_empty_result": int(self._recognizer_counts.get("brickognize_empty_result", 0)),
            "brickognize_timeout_total": int(self._recognizer_counts.get("brickognize_timeout_total", 0)),
            "tracker_id_switch_suspect_total": int(self._tracker_id_switch_suspect_total),
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
            status = getattr(piece.get("classification_status"), "value", piece.get("classification_status"))
            stage = getattr(piece.get("stage"), "value", piece.get("stage"))
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
        state_totals_snapshot: dict[str, dict[str, float]] = {}
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
            state_totals_snapshot[machine] = dict(totals)
            state_machines[machine] = {
                "current_state": current_state,
                "entered_at": current.get("entered_at_wall"),
                "state_time_s": totals,
                "state_share_pct": shares,
                "transitions": dict(
                    sorted(self._state_transition_counts.get(machine, {}).items())
                ),
            }

        channel_exit_counts = {
            "c_channel_2": 0,
            "c_channel_3": 0,
            "classification_channel": 0,
        }
        channel_exit_timestamps: dict[str, list[float]] = {
            channel: [] for channel in channel_exit_counts
        }
        for event in self._channel_exit_events:
            channel = str(event.get("channel") or "")
            if channel not in channel_exit_counts:
                continue
            channel_exit_counts[channel] += 1
            exited_at = event.get("exited_at")
            if isinstance(exited_at, (int, float)):
                channel_exit_timestamps[channel].append(float(exited_at))

        channel_active_time_s = {
            "c_channel_2": float(feeder_signal_totals_s.get("stepper_busy_ch2", 0.0) or 0.0),
            "c_channel_3": float(feeder_signal_totals_s.get("stepper_busy_ch3", 0.0) or 0.0),
            "classification_channel": sum(
                float(state_totals_snapshot.get("classification.occupancy", {}).get(state_name, 0.0) or 0.0)
                for state_name in CLASSIFICATION_ACTIVE_OCCUPANCY_STATES
            ),
        }

        classification_outcome_timestamps: dict[str, list[float]] = {
            "classified_success": [],
            "distributed_success": [],
            "unknown": [],
            "multi_drop_fail": [],
            "not_found": [],
        }
        for piece in all_pieces:
            status = getattr(piece.get("classification_status"), "value", piece.get("classification_status"))
            classified_at = piece.get("classified_at")
            distributed_at = piece.get("distributed_at")
            if status == "classified" and isinstance(classified_at, (int, float)):
                classification_outcome_timestamps["classified_success"].append(float(classified_at))
            if (
                status == "classified"
                and isinstance(distributed_at, (int, float))
            ):
                classification_outcome_timestamps["distributed_success"].append(float(distributed_at))
            if status == "unknown" and isinstance(classified_at, (int, float)):
                classification_outcome_timestamps["unknown"].append(float(classified_at))
            if status == "multi_drop_fail" and isinstance(classified_at, (int, float)):
                classification_outcome_timestamps["multi_drop_fail"].append(float(classified_at))
            if status == "not_found" and isinstance(classified_at, (int, float)):
                classification_outcome_timestamps["not_found"].append(float(classified_at))

        channel_throughput: dict[str, Any] = {}
        for channel, exit_count in channel_exit_counts.items():
            active_time_s = float(channel_active_time_s.get(channel, 0.0) or 0.0)
            inter_exit_ppm_samples: list[float] = []
            timestamps = sorted(channel_exit_timestamps.get(channel, []))
            for idx in range(1, len(timestamps)):
                dt_s = timestamps[idx] - timestamps[idx - 1]
                if dt_s > 0:
                    inter_exit_ppm_samples.append(60.0 / dt_s)
            channel_entry: dict[str, Any] = {
                "exit_count": exit_count,
                "running_time_s": running_time_s,
                "active_time_s": active_time_s,
                "waiting_time_s": max(0.0, running_time_s - active_time_s),
                "overall_ppm": _calcPpm(exit_count, running_time_s),
                "active_ppm": _calcPpm(exit_count, active_time_s),
                "inter_exit_ppm": _calcValueSummary(inter_exit_ppm_samples),
            }
            if channel == "classification_channel":
                outcomes: dict[str, Any] = {}
                for outcome_key, ts_list in classification_outcome_timestamps.items():
                    count = len(ts_list)
                    outcomes[outcome_key] = {
                        "count": count,
                        "overall_ppm": _calcPpm(count, running_time_s),
                        "active_ppm": _calcPpm(count, active_time_s),
                    }
                channel_entry["outcomes"] = outcomes
                channel_entry["active_state_time_s"] = {
                    state_name: float(
                        state_totals_snapshot.get("classification.occupancy", {}).get(state_name, 0.0) or 0.0
                    )
                    for state_name in sorted(CLASSIFICATION_ACTIVE_OCCUPANCY_STATES)
                }
            channel_throughput[channel] = channel_entry

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
            "channel_throughput": channel_throughput,
            "feeder": {
                "pulse_counts": pulse_counts,
                "skip_counts": dict(sorted(self._skip_counts.items())),
                "handoff_ghost_rejected_total": int(self._handoff_ghost_rejected_total),
                "handoff_embedding_rebind_total": int(self._handoff_embedding_rebind_total),
                "handoff_stale_pending_dropped_total": int(self._handoff_stale_pending_dropped_total),
                "multi_drop_leader_wins_total": int(self._multi_drop_leader_wins_total),
                "classification_zone_lost_total": int(self._classification_zone_lost_total),
                "exit_wiggle_triggered_c2_total": int(self._exit_wiggle_triggered_c2_total),
                "exit_wiggle_triggered_c3_total": int(self._exit_wiggle_triggered_c3_total),
                "c2_idle_skipped_no_cluster_total": int(self._c2_idle_skipped_no_cluster_total),
                "ch3_precise_held_count": self._ch3_precise_held_count,
                "signals_current": dict(sorted(self._feeder_signal_current.items())),
                "signal_time_s": dict(sorted(feeder_signal_totals_s.items())),
                "signal_timeline_recent": list(self._feeder_signal_timeline),
                "blocker_combo_time_s": dict(sorted(feeder_combo_totals_s.items())),
                "blocker_combo_timeline_recent": list(self._feeder_blocker_combo_timeline),
            },
            "state_machines": state_machines,
            "timeline_recent": list(self._state_timeline),
            "bus_recent": (
                list(self._bus_provider.recent())
                if self._bus_provider is not None and hasattr(self._bus_provider, "recent")
                else []
            ),
            "bus_publish_counts": (
                dict(self._bus_provider.publish_counts())
                if self._bus_provider is not None and hasattr(self._bus_provider, "publish_counts")
                else {}
            ),
            "blocked_reason_counts": dict(sorted(self._blocked_reason_counts.items())),
            "pieces_cached": len(self._piece_by_uuid),
            "servo_bus_offline_since_ts": self._servo_bus_offline_since_ts,
            "last_update_age_s": max(0.0, now - self._last_updated_at),
        }
