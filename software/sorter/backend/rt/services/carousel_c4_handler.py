"""CarouselC4Handler — Main-style sequential carousel applied to a polar C4.

Built as the analogue of ``SectionFeederHandler`` for the classification
chamber. Where Main's carousel is *physically* discrete (4 platforms,
90° lockstep rotation), our C4 is a continuous polar tray — but we
*can* treat it as a virtual carousel by walking the front piece through
a fixed sequence of angular checkpoints:

    arriving (intake) → advancing → classify (settle + snap) → await
    distributor → advancing → drop (eject) → idle

This handler only owns the **scheduling decisions**: when to pulse C4
transport, when to request a distributor handoff, when to fire the
exit eject. It deliberately does *not* own perception, classifier
submission, or piece UUID generation — those stay on the existing
RuntimeC4 path so BoxMot tracking and image collection keep working
unchanged. Operationally: ``c4_mode = "carousel"`` skips the
RuntimeC4 transport / handoff / eject decisions and lets this handler
drive instead. Default mode (``"runtime"``) keeps the legacy stack.

This is the C4 counterpart to the section feeder's "swap the decision
layer, keep BoxMot for piece UUIDs and image crops" architecture.

State machine (per cycle, single piece):

* ``IDLE`` — no piece in cycle. Wait for one.
* ``ADVANCING_TO_CLASSIFY`` — pulse transport until front piece's
  angle is within ``classify_tolerance_deg`` of ``classify_deg``.
* ``SETTLING_AT_CLASSIFY`` — hold position for ``settle_s`` so the
  classifier sees a stable frame.
* ``AWAIT_CLASSIFICATION`` — RuntimeC4's classifier finished its
  submission while we were settling; we just wait for the dossier
  to carry a result.
* ``REQUESTING_DISTRIBUTOR`` — got a result. Ask the distributor to
  position to the chosen bin.
* ``AWAIT_DISTRIBUTOR_READY`` — distributor still moving the chute.
* ``ADVANCING_TO_DROP`` — pulse transport until the piece is at
  ``drop_deg``.
* ``DROPPING`` — fire eject + commit the handoff.

The handler is intentionally small (~250 lines). It's a starting
point: live throughput tuning and multi-piece pipelining are follow-up
work, mirrored on the SectionFeederHandler progression.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol


class CarouselState(str, Enum):
    IDLE = "idle"
    ADVANCING_TO_CLASSIFY = "advancing_to_classify"
    SETTLING_AT_CLASSIFY = "settling_at_classify"
    AWAIT_CLASSIFICATION = "await_classification"
    REQUESTING_DISTRIBUTOR = "requesting_distributor"
    AWAIT_DISTRIBUTOR_READY = "await_distributor_ready"
    ADVANCING_TO_DROP = "advancing_to_drop"
    DROPPING = "dropping"


@dataclass(slots=True)
class _CycleSnapshot:
    """Per-piece visibility into the handler's pipeline."""

    piece_uuid: str
    started_at_mono: float
    state: CarouselState = CarouselState.IDLE
    state_entered_at_mono: float = 0.0
    classification_present: bool = False
    distributor_ready: bool = False
    eject_attempted: bool = False
    completed: bool = False
    completion_reason: str | None = None


@dataclass(slots=True)
class _Counters:
    cycles_started: int = 0
    cycles_completed: int = 0
    cycles_aborted: int = 0
    transport_pulses_classify: int = 0
    transport_pulses_drop: int = 0
    distributor_requests: int = 0
    distributor_request_rejects: int = 0
    ejects_fired: int = 0
    state_transitions: dict[str, int] = field(default_factory=dict)


# Pulled at tick time. The orchestrator builds this from the C4 runtime's
# perception + dossier state so we don't reach back into runtime internals.
@dataclass(frozen=True, slots=True)
class CarouselTickInput:
    front_piece_uuid: str | None
    front_track_angle_deg: float | None
    front_classification_present: bool
    front_classification: Any  # ClassifierResult, kept opaque to avoid import cycles
    front_dossier: dict[str, Any]
    front_track_count: int
    distributor_pending_piece_uuid: str | None
    distributor_pending_ready: bool


class _DistributorPort(Protocol):
    def handoff_request(
        self,
        *,
        piece_uuid: str,
        classification: Any,
        dossier: dict[str, Any] | None = None,
        now_mono: float | None = None,
    ) -> bool: ...

    def pending_ready(self, piece_uuid: str | None = None) -> bool: ...

    def handoff_commit(
        self, piece_uuid: str, now_mono: float | None = None
    ) -> bool: ...


class CarouselC4Handler:
    """Sequential single-piece scheduler for C4.

    All hardware moves go through *callables* injected at construction —
    same pattern as ``SectionFeederHandler``. The handler enforces its
    own per-state cooldowns so it never stacks pending hardware commands.
    """

    DEFAULT_CLASSIFY_DEG = 18.0
    DEFAULT_DROP_DEG = 30.0
    DEFAULT_CLASSIFY_TOLERANCE_DEG = 6.0
    DEFAULT_DROP_TOLERANCE_DEG = 3.0
    DEFAULT_SETTLE_S = 0.6
    DEFAULT_ADVANCE_STEP_DEG = 4.0
    DEFAULT_ADVANCE_COOLDOWN_S = 0.18
    DEFAULT_DISTRIBUTOR_TIMEOUT_S = 8.0
    # Sector mode: when ``sector_count > 0`` the platter is treated as
    # ``sector_count`` discrete bins of equal width. Pieces inside a
    # sector are forced to travel with the platter (5-wall hardware
    # design 2026-04-27). The handler then snaps target angles to the
    # nearest sector center, derives sensible default tolerances, and
    # exposes the current front-piece sector index in the snapshot.
    DEFAULT_SECTOR_COUNT = 0
    DEFAULT_SECTOR_OFFSET_DEG = 0.0

    def __init__(
        self,
        *,
        c4_transport: Callable[[float], bool],
        c4_eject: Callable[[], bool],
        distributor_port: _DistributorPort,
        c4_hw_busy: Callable[[], bool] | None = None,
        classify_deg: float = DEFAULT_CLASSIFY_DEG,
        drop_deg: float = DEFAULT_DROP_DEG,
        classify_tolerance_deg: float = DEFAULT_CLASSIFY_TOLERANCE_DEG,
        drop_tolerance_deg: float = DEFAULT_DROP_TOLERANCE_DEG,
        settle_s: float = DEFAULT_SETTLE_S,
        advance_step_deg: float = DEFAULT_ADVANCE_STEP_DEG,
        advance_cooldown_s: float = DEFAULT_ADVANCE_COOLDOWN_S,
        distributor_timeout_s: float = DEFAULT_DISTRIBUTOR_TIMEOUT_S,
        sector_count: int = DEFAULT_SECTOR_COUNT,
        sector_offset_deg: float = DEFAULT_SECTOR_OFFSET_DEG,
        logger: logging.Logger | None = None,
    ) -> None:
        self._c4_transport = c4_transport
        self._c4_eject = c4_eject
        self._distributor = distributor_port
        self._c4_hw_busy = c4_hw_busy or (lambda: False)
        self._classify_deg = float(classify_deg)
        self._drop_deg = float(drop_deg)
        self._classify_tolerance_deg = max(0.5, float(classify_tolerance_deg))
        self._drop_tolerance_deg = max(0.5, float(drop_tolerance_deg))
        self._settle_s = max(0.0, float(settle_s))
        self._advance_step_deg = max(0.5, float(advance_step_deg))
        self._advance_cooldown_s = max(0.0, float(advance_cooldown_s))
        self._distributor_timeout_s = max(0.5, float(distributor_timeout_s))
        self._sector_count = max(0, int(sector_count))
        self._sector_offset_deg = float(sector_offset_deg)
        if self._sector_count > 0:
            self._apply_sector_defaults()
        self._logger = logger or logging.getLogger("rt.carousel_c4")
        self._enabled = False
        self._state: CarouselState = CarouselState.IDLE
        self._state_entered_at_mono: float = -float("inf")
        self._last_advance_at_mono: float = -float("inf")
        self._cycle: _CycleSnapshot | None = None
        self._counters = _Counters()

    # ------------------------------------------------------------------
    # Lifecycle

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False
        self._abort_cycle("handler_disabled")

    def is_enabled(self) -> bool:
        return self._enabled

    def update_geometry(
        self,
        *,
        classify_deg: float | None = None,
        drop_deg: float | None = None,
        classify_tolerance_deg: float | None = None,
        drop_tolerance_deg: float | None = None,
        sector_count: int | None = None,
        sector_offset_deg: float | None = None,
    ) -> None:
        if classify_deg is not None:
            self._classify_deg = float(classify_deg)
        if drop_deg is not None:
            self._drop_deg = float(drop_deg)
        if classify_tolerance_deg is not None:
            self._classify_tolerance_deg = max(0.5, float(classify_tolerance_deg))
        if drop_tolerance_deg is not None:
            self._drop_tolerance_deg = max(0.5, float(drop_tolerance_deg))
        sector_changed = False
        if sector_count is not None:
            self._sector_count = max(0, int(sector_count))
            sector_changed = True
        if sector_offset_deg is not None:
            self._sector_offset_deg = float(sector_offset_deg)
            sector_changed = True
        if sector_changed and self._sector_count > 0:
            # Snap classify/drop to nearest sector centers and recompute
            # the default advance step + tolerances. The operator can
            # override these afterwards via update_geometry/update_timing
            # if they want fractional-sector advances or tighter
            # tolerances than the sector-half-width default.
            self._apply_sector_defaults()

    def update_timing(
        self,
        *,
        settle_s: float | None = None,
        advance_step_deg: float | None = None,
        advance_cooldown_s: float | None = None,
        distributor_timeout_s: float | None = None,
    ) -> None:
        if settle_s is not None:
            self._settle_s = max(0.0, float(settle_s))
        if advance_step_deg is not None:
            self._advance_step_deg = max(0.5, float(advance_step_deg))
        if advance_cooldown_s is not None:
            self._advance_cooldown_s = max(0.0, float(advance_cooldown_s))
        if distributor_timeout_s is not None:
            self._distributor_timeout_s = max(0.5, float(distributor_timeout_s))

    # ------------------------------------------------------------------
    # Tick

    def tick(self, payload: CarouselTickInput, *, now_mono: float | None = None) -> CarouselState:
        ts = time.monotonic() if now_mono is None else float(now_mono)
        if not self._enabled:
            return self._state

        # Pick up the cycle's piece on first appearance, or when the
        # current cycle's piece has rotated away.
        if self._cycle is None and payload.front_piece_uuid is not None:
            self._begin_cycle(payload.front_piece_uuid, ts)

        if self._cycle is None:
            self._set_state(CarouselState.IDLE, ts)
            return self._state

        # If the runtime lost track of our piece (different uuid at the
        # front), abort the cycle so we don't wait forever.
        if (
            payload.front_piece_uuid is not None
            and payload.front_piece_uuid != self._cycle.piece_uuid
        ):
            self._abort_cycle("front_piece_changed")
            return self._state

        if payload.front_piece_uuid is None and self._state in {
            CarouselState.IDLE,
            CarouselState.ADVANCING_TO_CLASSIFY,
        }:
            # Piece disappeared before we even started classifying.
            self._abort_cycle("front_piece_lost")
            return self._state

        # Dispatch on the current state. Each branch is small and
        # idempotent — tick is called every orchestrator cycle (50 Hz)
        # so any guard that returns without a transition just retries
        # next tick.
        if self._state in (CarouselState.IDLE, CarouselState.ADVANCING_TO_CLASSIFY):
            self._handle_advance_to_classify(payload, ts)
        elif self._state == CarouselState.SETTLING_AT_CLASSIFY:
            self._handle_settle(payload, ts)
        elif self._state == CarouselState.AWAIT_CLASSIFICATION:
            self._handle_await_classification(payload, ts)
        elif self._state == CarouselState.REQUESTING_DISTRIBUTOR:
            self._handle_request_distributor(payload, ts)
        elif self._state == CarouselState.AWAIT_DISTRIBUTOR_READY:
            self._handle_await_distributor(payload, ts)
        elif self._state == CarouselState.ADVANCING_TO_DROP:
            self._handle_advance_to_drop(payload, ts)
        elif self._state == CarouselState.DROPPING:
            self._handle_drop(payload, ts)
        return self._state

    # ------------------------------------------------------------------
    # Snapshot

    def snapshot(self) -> dict[str, Any]:
        cycle = self._cycle
        sector_size = (
            360.0 / float(self._sector_count) if self._sector_count > 0 else None
        )
        return {
            "enabled": self._enabled,
            "state": self._state.value,
            "state_entered_at_mono": self._state_entered_at_mono,
            "geometry": {
                "classify_deg": self._classify_deg,
                "drop_deg": self._drop_deg,
                "classify_tolerance_deg": self._classify_tolerance_deg,
                "drop_tolerance_deg": self._drop_tolerance_deg,
                "sector_count": int(self._sector_count),
                "sector_offset_deg": float(self._sector_offset_deg),
                "sector_size_deg": sector_size,
                "classify_sector_idx": (
                    self.sector_index_for(self._classify_deg)
                    if self._sector_count > 0
                    else None
                ),
                "drop_sector_idx": (
                    self.sector_index_for(self._drop_deg)
                    if self._sector_count > 0
                    else None
                ),
            },
            "timing": {
                "settle_s": self._settle_s,
                "advance_step_deg": self._advance_step_deg,
                "advance_cooldown_s": self._advance_cooldown_s,
                "distributor_timeout_s": self._distributor_timeout_s,
            },
            "current_cycle": (
                {
                    "piece_uuid": cycle.piece_uuid,
                    "state": cycle.state.value,
                    "started_at_mono": cycle.started_at_mono,
                    "classification_present": cycle.classification_present,
                    "distributor_ready": cycle.distributor_ready,
                    "eject_attempted": cycle.eject_attempted,
                }
                if cycle is not None
                else None
            ),
            "counters": {
                "cycles_started": self._counters.cycles_started,
                "cycles_completed": self._counters.cycles_completed,
                "cycles_aborted": self._counters.cycles_aborted,
                "transport_pulses_classify": self._counters.transport_pulses_classify,
                "transport_pulses_drop": self._counters.transport_pulses_drop,
                "distributor_requests": self._counters.distributor_requests,
                "distributor_request_rejects": self._counters.distributor_request_rejects,
                "ejects_fired": self._counters.ejects_fired,
                "state_transitions": dict(self._counters.state_transitions),
            },
        }

    # ------------------------------------------------------------------
    # Sector helpers

    def _apply_sector_defaults(self) -> None:
        """Re-derive defaults that depend on the sector geometry.

        Idempotent: called from ``__init__`` and ``update_geometry``
        whenever ``sector_count`` / ``sector_offset_deg`` change. Always
        snaps ``classify_deg`` / ``drop_deg`` to the nearest sector
        centers and sets ``advance_step_deg`` to one full sector. If
        the operator has a tighter tolerance preference they call
        ``update_geometry`` after switching to sector mode.
        """
        if self._sector_count <= 0:
            return
        sector_size = 360.0 / float(self._sector_count)
        self._classify_deg = self._snap_to_sector_center(self._classify_deg)
        self._drop_deg = self._snap_to_sector_center(self._drop_deg)
        # Sector half-width minus a small margin so a piece sitting
        # near a wall still registers in the *correct* sector even
        # with a few degrees of detection jitter.
        margin = max(2.0, sector_size * 0.1)
        self._classify_tolerance_deg = max(0.5, sector_size / 2.0 - margin)
        self._drop_tolerance_deg = max(0.5, sector_size / 2.0 - margin)
        self._advance_step_deg = sector_size

    def auto_calibrate_offset(
        self,
        angles_deg: list[float],
        *,
        method: str = "gaps",
    ) -> float | None:
        """Estimate ``sector_offset_deg`` from observed track angles.

        Without an encoder/homing on C4 the wall positions shift
        after every restart. The 5-wall geometry leaves narrow
        angular gaps where no piece can ever sit (the walls
        themselves) — the ``"gaps"`` method (default) histograms
        observations modulo the sector size and finds the lowest-
        density bin to locate one wall, then derives the offset.

        Falls back to ``"centers"`` (clustering-based) if the
        operator wants the older heuristic for comparison.

        For wall positions detected directly (e.g. from a YOLO
        wall-detector), use :meth:`update_walls` instead — it skips
        the indirect inference entirely.

        Returns the inferred offset (and applies it in place) or
        ``None`` when the input is empty / sector mode is off.
        """
        if method == "centers":
            offset = calibrate_sector_offset_from_angles(
                angles_deg, self._sector_count
            )
        else:
            offset = calibrate_sector_offset_from_gaps(
                angles_deg, self._sector_count
            )
        if offset is None:
            return None
        self.update_geometry(sector_offset_deg=offset)
        return offset

    def update_walls(self, wall_angles_deg: list[float]) -> float | None:
        """Update ``sector_offset_deg`` from directly detected walls.

        Most robust path: a YOLO (or other CV) detector publishes the
        absolute angular positions of the visible walls and we use
        those directly. No need to wait for pieces to populate the
        platter or for a rotation cycle to expose gaps.

        Returns the new offset and applies it in place, or ``None``
        if input is empty / sector mode is off.
        """
        offset = calibrate_sector_offset_from_walls(
            wall_angles_deg, self._sector_count
        )
        if offset is None:
            return None
        self.update_geometry(sector_offset_deg=offset)
        return offset

    def sector_index_for(self, angle_deg: float) -> int | None:
        """Return the sector index that contains ``angle_deg``.

        Returns ``None`` in continuous mode (``sector_count == 0``).
        Index 0 starts at ``sector_offset_deg`` and runs counter-
        clockwise (with the platter rotation direction).
        """
        if self._sector_count <= 0:
            return None
        sector_size = 360.0 / float(self._sector_count)
        rel = (float(angle_deg) - self._sector_offset_deg) % 360.0
        return int(rel // sector_size)

    def sector_center_deg(self, sector_idx: int) -> float | None:
        if self._sector_count <= 0:
            return None
        sector_size = 360.0 / float(self._sector_count)
        center = self._sector_offset_deg + (float(sector_idx) + 0.5) * sector_size
        return _wrap_deg(center)

    def _snap_to_sector_center(self, angle_deg: float) -> float:
        if self._sector_count <= 0:
            return float(angle_deg)
        idx = self.sector_index_for(angle_deg)
        if idx is None:
            return float(angle_deg)
        center = self.sector_center_deg(idx)
        return float(angle_deg) if center is None else float(center)

    # ------------------------------------------------------------------
    # Internals

    def _begin_cycle(self, piece_uuid: str, ts: float) -> None:
        self._cycle = _CycleSnapshot(
            piece_uuid=piece_uuid,
            started_at_mono=ts,
            state=CarouselState.ADVANCING_TO_CLASSIFY,
            state_entered_at_mono=ts,
        )
        self._counters.cycles_started += 1
        self._set_state(CarouselState.ADVANCING_TO_CLASSIFY, ts)

    def _abort_cycle(self, reason: str) -> None:
        if self._cycle is not None:
            self._cycle.completed = True
            self._cycle.completion_reason = reason
            self._counters.cycles_aborted += 1
        self._cycle = None
        self._set_state(CarouselState.IDLE, time.monotonic())

    def _complete_cycle(self) -> None:
        if self._cycle is not None:
            self._cycle.completed = True
            self._cycle.completion_reason = "delivered"
            self._counters.cycles_completed += 1
        self._cycle = None
        self._set_state(CarouselState.IDLE, time.monotonic())

    def _set_state(self, new_state: CarouselState, ts: float) -> None:
        if new_state == self._state:
            return
        key = f"{self._state.value}->{new_state.value}"
        self._counters.state_transitions[key] = (
            self._counters.state_transitions.get(key, 0) + 1
        )
        self._state = new_state
        self._state_entered_at_mono = ts
        if self._cycle is not None:
            self._cycle.state = new_state
            self._cycle.state_entered_at_mono = ts

    def _handle_advance_to_classify(self, payload: CarouselTickInput, ts: float) -> None:
        if payload.front_track_angle_deg is None:
            return
        if abs(_wrap_deg(payload.front_track_angle_deg - self._classify_deg)) <= self._classify_tolerance_deg:
            self._set_state(CarouselState.SETTLING_AT_CLASSIFY, ts)
            return
        if self._maybe_advance(ts):
            self._counters.transport_pulses_classify += 1

    def _handle_settle(self, payload: CarouselTickInput, ts: float) -> None:
        if payload.front_classification_present:
            self._cycle.classification_present = True  # type: ignore[union-attr]
            self._set_state(CarouselState.REQUESTING_DISTRIBUTOR, ts)
            return
        if (ts - self._state_entered_at_mono) < self._settle_s:
            return
        # Settle period elapsed. The classifier (still owned by RuntimeC4)
        # had time to capture the piece at rest; wait for the result.
        self._set_state(CarouselState.AWAIT_CLASSIFICATION, ts)

    def _handle_await_classification(
        self, payload: CarouselTickInput, ts: float
    ) -> None:
        if payload.front_classification_present:
            self._cycle.classification_present = True  # type: ignore[union-attr]
            self._set_state(CarouselState.REQUESTING_DISTRIBUTOR, ts)

    def _handle_request_distributor(
        self, payload: CarouselTickInput, ts: float
    ) -> None:
        if self._cycle is None:
            return
        if payload.distributor_pending_piece_uuid == self._cycle.piece_uuid:
            self._set_state(CarouselState.AWAIT_DISTRIBUTOR_READY, ts)
            return
        if payload.distributor_pending_piece_uuid is not None:
            # Distributor is busy with someone else — wait, don't spam.
            return
        try:
            ok = bool(
                self._distributor.handoff_request(
                    piece_uuid=self._cycle.piece_uuid,
                    classification=payload.front_classification,
                    dossier=payload.front_dossier,
                    now_mono=ts,
                )
            )
        except Exception:
            self._logger.exception(
                "CarouselC4Handler: distributor.handoff_request raised"
            )
            ok = False
        self._counters.distributor_requests += 1
        if not ok:
            self._counters.distributor_request_rejects += 1
            return
        self._set_state(CarouselState.AWAIT_DISTRIBUTOR_READY, ts)

    def _handle_await_distributor(
        self, payload: CarouselTickInput, ts: float
    ) -> None:
        if self._cycle is None:
            return
        if (ts - self._state_entered_at_mono) > self._distributor_timeout_s:
            self._abort_cycle("distributor_timeout")
            return
        ready = (
            payload.distributor_pending_piece_uuid == self._cycle.piece_uuid
            and payload.distributor_pending_ready
        )
        if ready:
            self._cycle.distributor_ready = True
            self._set_state(CarouselState.ADVANCING_TO_DROP, ts)

    def _handle_advance_to_drop(
        self, payload: CarouselTickInput, ts: float
    ) -> None:
        if payload.front_track_angle_deg is None:
            return
        if abs(_wrap_deg(payload.front_track_angle_deg - self._drop_deg)) <= self._drop_tolerance_deg:
            self._set_state(CarouselState.DROPPING, ts)
            return
        if self._maybe_advance(ts):
            self._counters.transport_pulses_drop += 1

    def _handle_drop(self, payload: CarouselTickInput, ts: float) -> None:
        if self._cycle is None:
            return
        if self._cycle.eject_attempted:
            return
        try:
            ejected = bool(self._c4_eject())
        except Exception:
            self._logger.exception("CarouselC4Handler: c4_eject raised")
            ejected = False
        self._cycle.eject_attempted = True
        self._counters.ejects_fired += 1
        if not ejected:
            self._abort_cycle("eject_failed")
            return
        try:
            self._distributor.handoff_commit(self._cycle.piece_uuid, now_mono=ts)
        except Exception:
            self._logger.exception(
                "CarouselC4Handler: distributor.handoff_commit raised"
            )
        self._complete_cycle()

    def _maybe_advance(self, ts: float) -> bool:
        if (ts - self._last_advance_at_mono) < self._advance_cooldown_s:
            return False
        if self._c4_hw_busy():
            return False
        try:
            ok = bool(self._c4_transport(self._advance_step_deg))
        except Exception:
            self._logger.exception("CarouselC4Handler: c4_transport raised")
            ok = False
        if ok:
            self._last_advance_at_mono = ts
        return ok


def _wrap_deg(angle: float) -> float:
    a = float(angle) % 360.0
    if a > 180.0:
        a -= 360.0
    elif a <= -180.0:
        a += 360.0
    return a


def calibrate_sector_offset_from_angles(
    angles_deg: list[float],
    sector_count: int,
) -> float | None:
    """Infer ``sector_offset_deg`` by clustering — assumes pieces rest
    near a consistent point within each sector (centers by default).

    Less robust than ``calibrate_sector_offset_from_gaps`` because the
    "rest near centers" assumption is an operator-verifiable guess,
    not a physical guarantee. Useful as a sanity-check / fallback
    when there isn't enough data for the gap method.

    Returns ``None`` if ``sector_count <= 0`` or the input is empty
    or the circular mean is undefined (vectors cancel exactly).
    """
    if sector_count <= 0:
        return None
    if not angles_deg:
        return None
    sector_size = 360.0 / float(sector_count)
    sin_sum = 0.0
    cos_sum = 0.0
    for raw in angles_deg:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        rel = value % sector_size
        # Map rel ∈ [0, sector_size) onto a unit circle so we can take
        # a vector mean that respects the wraparound at sector_size.
        theta = (rel / sector_size) * 2.0 * math.pi
        sin_sum += math.sin(theta)
        cos_sum += math.cos(theta)
    if sin_sum == 0.0 and cos_sum == 0.0:
        return None
    mean_rad = math.atan2(sin_sum, cos_sum)
    if mean_rad < 0:
        mean_rad += 2.0 * math.pi
    mean_rel = (mean_rad / (2.0 * math.pi)) * sector_size
    # Pieces cluster at sector_size/2 if rest position is the center;
    # the offset that puts that cluster exactly there is:
    offset = (mean_rel - sector_size / 2.0) % sector_size
    return float(offset)


def calibrate_sector_offset_from_walls(
    wall_angles_deg: list[float],
    sector_count: int,
) -> float | None:
    """Infer ``sector_offset_deg`` from directly detected wall positions.

    Most robust calibration path: a separate detector (e.g. a YOLO
    model trained on the wall-divider geometry) publishes the
    angular positions of the visible walls. Each wall's angle modulo
    ``sector_size`` approximates the offset (since walls are
    ``sector_size`` degrees apart), and the circular mean of those
    moduli minimises detector noise.

    Inputs:

    * ``wall_angles_deg``: any subset of the ``sector_count`` walls
      (typically all of them; partial detections still work as long
      as the moduli are reproducible).
    * ``sector_count``: hardware constant (5 for the 2026-04-27
      install).

    Returns the inferred offset or ``None`` for empty input /
    ``sector_count <= 0``.
    """
    if sector_count <= 0:
        return None
    if not wall_angles_deg:
        return None
    sector_size = 360.0 / float(sector_count)
    sin_sum = 0.0
    cos_sum = 0.0
    n = 0
    for raw in wall_angles_deg:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        rel = value % sector_size
        theta = (rel / sector_size) * 2.0 * math.pi
        sin_sum += math.sin(theta)
        cos_sum += math.cos(theta)
        n += 1
    if n == 0:
        return None
    if sin_sum == 0.0 and cos_sum == 0.0:
        return None
    mean_rad = math.atan2(sin_sum, cos_sum)
    if mean_rad < 0:
        mean_rad += 2.0 * math.pi
    return float((mean_rad / (2.0 * math.pi)) * sector_size % sector_size)


def calibrate_sector_offset_from_gaps(
    angles_deg: list[float],
    sector_count: int,
    bin_width_deg: float = 2.0,
) -> float | None:
    """Infer ``sector_offset_deg`` by detecting the empty wall gap.

    Physically grounded: walls are narrow physical structures that
    pieces *can never sit on*. Histogramming all observed track
    angles modulo ``sector_size`` and finding the lowest-density bin
    locates the wall — no assumption about where within a sector
    pieces tend to rest.

    Robust to:
    * arbitrary rest positions (leading wall, trailing wall, center,
      anywhere within a sector)
    * pieces drifting through their sector during platter motion
    * unequal piece distributions across sectors

    Less robust to:
    * very sparse data (few pieces, short observation window) — the
      "deepest gap" might be an unexplored region rather than a wall.
      Mitigation: feed angles collected over several seconds while
      the platter is rotating so each piece sweeps through its sector.

    Returns ``None`` if ``sector_count <= 0`` or the input is empty.
    """
    if sector_count <= 0:
        return None
    if not angles_deg:
        return None
    sector_size = 360.0 / float(sector_count)
    n_bins = max(8, int(round(sector_size / max(0.5, float(bin_width_deg)))))
    bins = [0] * n_bins
    sample_count = 0
    for raw in angles_deg:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        rel = value % sector_size
        idx = int(rel / sector_size * n_bins) % n_bins
        bins[idx] += 1
        sample_count += 1
    if sample_count == 0:
        return None
    # Find the deepest gap. Doubling the array handles wraparound
    # in run-length detection so a gap that straddles index 0 is
    # treated correctly.
    min_count = min(bins)
    extended = bins + bins
    best_start, best_len = 0, 0
    cur_start, cur_len = -1, 0
    for i, c in enumerate(extended):
        if c == min_count:
            if cur_start < 0:
                cur_start = i
            cur_len += 1
            if cur_len > best_len:
                best_len = cur_len
                best_start = cur_start
        else:
            cur_start = -1
            cur_len = 0
    # Sector 0's leading wall sits at the gap center.
    gap_center_idx = (best_start + best_len / 2.0) % n_bins
    gap_center_rel_deg = gap_center_idx / n_bins * sector_size
    return float(gap_center_rel_deg % sector_size)


__all__ = [
    "CarouselC4Handler",
    "CarouselState",
    "CarouselTickInput",
    "calibrate_sector_offset_from_angles",
    "calibrate_sector_offset_from_gaps",
    "calibrate_sector_offset_from_walls",
]
