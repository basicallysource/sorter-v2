"""PieceTrackBank — durable per-piece state for a single ring.

Owns the physical-piece UUID, a tray-frame polar Kalman state with
explicit covariance, and the lifecycle / dispatch eligibility flags. Raw
tracker IDs (BoxMot / ByteTrack global_id) become aliases inside a
PieceTrack — they are sensor hints, not durable identities.

Per the architecture recommendation in
``docs/lab/sorter-tracking-architecture-recommendation.md``: the runtime
predicts every track to the current encoder angle, associates incoming
vision measurements via Mahalanobis-gated Hungarian matching, and only
admits a new piece when no existing track explains the measurement.

This module is deliberately thin and dependency-free apart from numpy:
the runtime that owns the bank (RuntimeC4 in stage 2 of the rollout)
calls ``predict_all`` once per orchestrator tick, then
``associate_and_update`` once per perception-frame. The bank does not
fire motion or eject — it is a state surface, not a controller.

Coordinate convention:
    theta_cam = atan2(y - cy, x - cx) — pixel-frame radians, with the
        same orientation as the camera image.
    phi(t)    = encoder-reported tray angle at time t, radians.
    a(t)      = wrap(theta_cam(t) - phi(t)) — tray-frame angle. A piece
        carried perfectly by the tray has ``a`` constant; sliding /
        nudged pieces have non-zero ``adot``.

State vector x = [a, r, adot, rdot] in tray-frame polar:
    a    — tray-frame angle (radians, wrapped to [-pi, pi])
    r    — radius (pixels in the rectified camera image)
    adot — angular velocity (rad/s, tray-frame)
    rdot — radial velocity (px/s)

Process model: constant velocity with isotropic noise. Stage 5 of the
rollout swaps this for a mode-switched IMM (carried / sliding /
collision_or_clump / edge_transfer / lost_coast); the public API of this
bank is shaped so that swap is a process-noise change, not a structural
rewrite.
"""

from __future__ import annotations

import math
import uuid as _uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

import numpy as np


# ---------------------------------------------------------------------------
# Lifecycle


class PieceLifecycleState(str, Enum):
    """Per-piece dispatch eligibility.

    The hard rules from the architecture recommendation:
    - ``CLASSIFIED_CONFIDENT`` is the only state that may be dispatched
      into a class-specific bin.
    - Every other state may still occupy the chute window — i.e. block
      another piece's dispatch — until it is finalized.
    """

    TENTATIVE = "tentative"
    CONFIRMED_UNCLASSIFIED = "confirmed_unclassified"
    CLASSIFIED_CONFIDENT = "classified_confident"
    CLASSIFIED_IDENTITY_UNCERTAIN = "classified_identity_uncertain"
    LOST_COASTING = "lost_coasting"
    CLUSTERED = "clustered"
    REJECT_ONLY = "reject_only"
    EJECTED = "ejected"
    FINALIZED_LOST = "finalized_lost"


_DISPATCH_ELIGIBLE_STATES = frozenset(
    {PieceLifecycleState.CLASSIFIED_CONFIDENT}
)
_CHUTE_BLOCKING_STATES = frozenset(
    {
        PieceLifecycleState.TENTATIVE,
        PieceLifecycleState.CONFIRMED_UNCLASSIFIED,
        PieceLifecycleState.CLASSIFIED_CONFIDENT,
        PieceLifecycleState.CLASSIFIED_IDENTITY_UNCERTAIN,
        PieceLifecycleState.LOST_COASTING,
        PieceLifecycleState.CLUSTERED,
        PieceLifecycleState.REJECT_ONLY,
    }
)


def is_dispatch_eligible(state: PieceLifecycleState) -> bool:
    return state in _DISPATCH_ELIGIBLE_STATES


def is_chute_blocking(state: PieceLifecycleState) -> bool:
    return state in _CHUTE_BLOCKING_STATES


# ---------------------------------------------------------------------------
# Geometry


def wrap_rad(angle: float) -> float:
    """Wrap an angle into [-pi, pi]."""
    return float(math.atan2(math.sin(angle), math.cos(angle)))


def wrap_diff_rad(a: float, b: float) -> float:
    """Smallest signed difference ``a - b`` wrapped to [-pi, pi]."""
    return wrap_rad(a - b)


@dataclass(frozen=True, slots=True)
class CameraTrayCalibration:
    """Camera <-> tray-plane mapping for one ring.

    Pixel center ``(cx, cy)`` is the projected tray axis on the camera
    image. ``orientation`` is +1 if increasing ``theta_cam`` matches the
    tray's positive rotation direction, -1 otherwise. The bank does not
    need a full intrinsic / extrinsic — only the polar mapping around
    the tray axis.
    """

    cx: float
    cy: float
    orientation: int = 1

    def to_polar(self, x: float, y: float) -> tuple[float, float]:
        """Return ``(theta_cam_rad, radius_px)`` for an image-plane point."""
        dx = float(x) - self.cx
        dy = float(y) - self.cy
        return float(math.atan2(dy, dx)) * float(self.orientation), float(
            math.hypot(dx, dy)
        )


# ---------------------------------------------------------------------------
# Measurements + tracks


@dataclass(slots=True)
class Measurement:
    """One incoming vision detection mapped into tray-frame polar coords.

    ``a_meas`` is already in tray frame (encoder subtracted). ``r_meas``
    is in image pixels. ``raw_track_id`` is the BoxMot/ByteTrack global
    id if the source tracker provided one — used as an association hint
    but never as a durable identity.
    """

    a_meas: float
    r_meas: float
    score: float
    raw_track_id: int | None = None
    appearance_embedding: tuple[float, ...] | None = None
    bbox_xyxy: tuple[int, int, int, int] | None = None
    confirmed_real: bool = False
    timestamp: float = 0.0


@dataclass(slots=True)
class PieceTrack:
    """One physical piece on a ring — durable identity + Bayesian state.

    ``last_observed_t`` is the wall time of the last actual vision
    update — used for the silence / coast / finalize lifecycle.
    ``last_predicted_t`` is just a bookkeeping cursor for the Kalman
    integrator so the next prediction step uses the correct ``dt``.
    """

    piece_uuid: str
    channel: str
    state_mean: np.ndarray  # shape (4,): [a, r, adot, rdot]
    state_covariance: np.ndarray  # shape (4, 4)
    last_observed_t: float
    last_observed_encoder: float
    last_predicted_t: float
    raw_track_aliases: set[int] = field(default_factory=set)
    embedding_mean: np.ndarray | None = None
    embedding_count: int = 0
    confirmed_real_observations: int = 0
    detection_observations: int = 0
    ghost_observations: int = 0
    lifecycle_state: PieceLifecycleState = PieceLifecycleState.TENTATIVE
    class_label: str | None = None
    class_confidence: float | None = None

    @property
    def angle_rad(self) -> float:
        return float(self.state_mean[0])

    @property
    def radius_px(self) -> float:
        return float(self.state_mean[1])

    @property
    def angle_deg(self) -> float:
        return float(math.degrees(self.angle_rad))

    @property
    def angle_sigma_rad(self) -> float:
        return float(math.sqrt(max(0.0, self.state_covariance[0, 0])))

    @property
    def angle_sigma_deg(self) -> float:
        return float(math.degrees(self.angle_sigma_rad))


# ---------------------------------------------------------------------------
# Kalman primitives


def _identity_4() -> np.ndarray:
    return np.eye(4, dtype=float)


def _measurement_matrix() -> np.ndarray:
    """H: 4-state -> 2-measurement (observe a and r only)."""
    return np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ],
        dtype=float,
    )


_H = _measurement_matrix()


def _process_matrix(dt: float) -> np.ndarray:
    """F: constant-velocity in tray-frame polar.

    a' = a + adot * dt
    r' = r + rdot * dt
    adot' = adot
    rdot' = rdot
    """
    f = _identity_4()
    f[0, 2] = float(dt)
    f[1, 3] = float(dt)
    return f


@dataclass(frozen=True, slots=True)
class ProcessNoise:
    """Diagonal process-noise model with separate angular / radial scales.

    ``sigma_a_per_s`` is the standard deviation we add to ``adot`` per
    second of prediction (rad/s/s noise, integrated over dt). The
    matrix is built so the pre-update state covariance grows at a
    physically meaningful rate even when no detection arrives. Stage 5
    will swap this for a mode-switched version (collision_or_clump
    inflates, carried shrinks).
    """

    sigma_a_per_s: float = math.radians(2.0)
    sigma_r_per_s: float = 4.0
    sigma_adot_per_s: float = math.radians(8.0)
    sigma_rdot_per_s: float = 12.0

    def matrix(self, dt: float) -> np.ndarray:
        dt = max(0.0, float(dt))
        q = np.zeros((4, 4), dtype=float)
        q[0, 0] = (self.sigma_a_per_s * dt) ** 2 + (self.sigma_adot_per_s * dt * dt / 2.0) ** 2
        q[1, 1] = (self.sigma_r_per_s * dt) ** 2 + (self.sigma_rdot_per_s * dt * dt / 2.0) ** 2
        q[2, 2] = (self.sigma_adot_per_s * dt) ** 2
        q[3, 3] = (self.sigma_rdot_per_s * dt) ** 2
        return q


@dataclass(frozen=True, slots=True)
class MeasurementNoise:
    """Diagonal measurement noise (camera detection variance).

    YOLO bbox centers are accurate to roughly a pixel for clean
    detections, which projects to well under a degree at the C4 camera
    distance. The default is intentionally tight so the bank trusts
    each fresh observation strongly — the Kalman is here to bridge
    short silences between vision frames, not to second-guess clean
    measurements with state-momentum bias.
    """

    sigma_a_rad: float = math.radians(0.5)
    sigma_r_px: float = 2.0

    def matrix(self) -> np.ndarray:
        return np.diag(
            [
                self.sigma_a_rad ** 2,
                self.sigma_r_px ** 2,
            ]
        ).astype(float)


# ---------------------------------------------------------------------------
# The bank


@dataclass
class PieceTrackBankConfig:
    channel: str
    calibration: CameraTrayCalibration
    process_noise: ProcessNoise = field(default_factory=ProcessNoise)
    measurement_noise: MeasurementNoise = field(default_factory=MeasurementNoise)
    # Mahalanobis chi-squared 2-DOF gates (1 - alpha):
    #   2-DOF chi2 inverse cdf: 0.95 -> 5.99, 0.99 -> 9.21, 0.999 -> 13.82
    association_gate_chi2: float = 9.21
    # Innovation snap threshold. When a measurement on an *existing*
    # track lands more than this many sigma away (Mahalanobis squared),
    # the Kalman gain blend lags reality — usually because the piece
    # genuinely jumped (slip / nudge / collision) rather than drifted.
    # Snap the state straight to the measurement and reset velocity.
    snap_chi2_threshold: float = 50.0
    # Birth threshold: a tentative track gets promoted to
    # ``CONFIRMED_UNCLASSIFIED`` after this many real detections.
    confirm_min_detections: int = 3
    confirm_min_real: int = 1
    # A track with no detection for this many seconds drops to LOST_COASTING.
    coast_after_silence_s: float = 0.6
    # A LOST_COASTING track whose covariance grew past these sigmas is
    # finalized — its position can no longer poison dispatch.
    finalize_lost_after_silence_s: float = 4.0
    # Initial state covariance for a freshly-admitted track.
    initial_sigma_a_rad: float = math.radians(4.0)
    initial_sigma_r_px: float = 8.0
    initial_sigma_adot_per_s: float = math.radians(8.0)
    initial_sigma_rdot_per_s: float = 16.0

    def initial_covariance(self) -> np.ndarray:
        return np.diag(
            [
                self.initial_sigma_a_rad ** 2,
                self.initial_sigma_r_px ** 2,
                self.initial_sigma_adot_per_s ** 2,
                self.initial_sigma_rdot_per_s ** 2,
            ]
        ).astype(float)


class PieceTrackBank:
    """Owner of all PieceTracks for one ring."""

    def __init__(self, config: PieceTrackBankConfig) -> None:
        self._config = config
        self._tracks: dict[str, PieceTrack] = {}
        self._raw_id_index: dict[int, str] = {}
        self._pending_landings: dict[str, PendingLanding] = {}

    # ------------------------------------------------------------------
    # Read-only views

    @property
    def channel(self) -> str:
        return self._config.channel

    @property
    def config(self) -> PieceTrackBankConfig:
        return self._config

    def __len__(self) -> int:
        return len(self._tracks)

    def tracks(self) -> Iterable[PieceTrack]:
        return tuple(self._tracks.values())

    def track(self, piece_uuid: str) -> PieceTrack | None:
        return self._tracks.get(piece_uuid)

    def find_by_raw_id(self, raw_track_id: int) -> PieceTrack | None:
        piece_uuid = self._raw_id_index.get(int(raw_track_id))
        if piece_uuid is None:
            return None
        return self._tracks.get(piece_uuid)

    def dispatch_eligible(self) -> tuple[PieceTrack, ...]:
        return tuple(
            t for t in self._tracks.values() if is_dispatch_eligible(t.lifecycle_state)
        )

    def chute_blocking(self) -> tuple[PieceTrack, ...]:
        return tuple(
            t for t in self._tracks.values() if is_chute_blocking(t.lifecycle_state)
        )

    # ------------------------------------------------------------------
    # Predict / update / lifecycle

    def predict_all(self, t: float, encoder_rad: float) -> None:
        """Propagate every track to time ``t`` using the constant-velocity
        process model.

        The encoder angle is used implicitly: tracks live in tray frame,
        so the carrier rotation is already absorbed. The encoder is only
        recorded so downstream consumers can convert tray-frame angles
        back to world-frame angles when they need to.
        """
        q_builder = self._config.process_noise
        for tr in self._tracks.values():
            dt = float(t) - float(tr.last_predicted_t)
            if dt <= 0.0:
                continue
            f = _process_matrix(dt)
            q = q_builder.matrix(dt)
            tr.state_mean = f @ tr.state_mean
            tr.state_mean[0] = wrap_rad(float(tr.state_mean[0]))
            tr.state_covariance = f @ tr.state_covariance @ f.T + q
            tr.last_predicted_t = float(t)

    def associate_and_update(
        self,
        measurements: list[Measurement],
        *,
        now_t: float,
        encoder_rad: float,
    ) -> "AssociationOutcome":
        """Match each measurement against the predicted bank state.

        Returns the outcome for caller logging — which measurements
        updated which tracks, which created a new piece, and which were
        rejected as ghosts.
        """
        outcome = AssociationOutcome()
        if not measurements:
            self._update_lifecycle(now_t)
            return outcome

        track_uuids = list(self._tracks.keys())
        if not track_uuids:
            for meas in measurements:
                self._birth_from_measurement(meas, now_t=now_t, encoder_rad=encoder_rad)
                outcome.births += 1
            self._update_lifecycle(now_t)
            return outcome

        cost = self._build_cost_matrix(track_uuids, measurements)
        # Greedy minimum-cost assignment with gating. A future stage swaps
        # this for Hungarian; greedy is good enough at the scale we run
        # (typically <= 12 tracks * <= 12 measurements per channel).
        assigned_meas: set[int] = set()
        assigned_tracks: set[str] = set()
        order = sorted(
            ((cost[i, j], i, j) for i in range(len(track_uuids)) for j in range(len(measurements))),
            key=lambda item: item[0],
        )
        for c, i, j in order:
            if c >= self._config.association_gate_chi2:
                break
            uuid_i = track_uuids[i]
            if uuid_i in assigned_tracks or j in assigned_meas:
                continue
            assigned_tracks.add(uuid_i)
            assigned_meas.add(j)
            self._kalman_update(uuid_i, measurements[j], now_t=now_t, encoder_rad=encoder_rad)
            outcome.updates.append((uuid_i, j))

        for j, meas in enumerate(measurements):
            if j in assigned_meas:
                continue
            self._birth_from_measurement(meas, now_t=now_t, encoder_rad=encoder_rad)
            outcome.births += 1

        self._update_lifecycle(now_t)
        return outcome

    def _build_cost_matrix(
        self,
        track_uuids: list[str],
        measurements: list[Measurement],
    ) -> np.ndarray:
        h = _H
        r = self._config.measurement_noise.matrix()
        cost = np.full((len(track_uuids), len(measurements)), float("inf"), dtype=float)
        for i, piece_uuid in enumerate(track_uuids):
            tr = self._tracks[piece_uuid]
            s = h @ tr.state_covariance @ h.T + r  # innovation covariance
            try:
                s_inv = np.linalg.inv(s)
            except np.linalg.LinAlgError:
                continue
            predicted = h @ tr.state_mean  # (a, r)
            for j, meas in enumerate(measurements):
                z = np.array([meas.a_meas, meas.r_meas], dtype=float)
                # Wrap angular residual so a measurement at +pi+eps does
                # not look infinitely far from a track at -pi+eps.
                innov = z - predicted
                innov[0] = wrap_rad(float(innov[0]))
                d2 = float(innov.T @ s_inv @ innov)
                # Penalise a raw-id mismatch softly: if the measurement
                # carries a raw track id that already aliases a *different*
                # piece, we still allow the association via geometry but
                # add a chi2-equivalent penalty so the geometric match has
                # to be strong.
                if (
                    meas.raw_track_id is not None
                    and meas.raw_track_id in self._raw_id_index
                    and self._raw_id_index[meas.raw_track_id] != piece_uuid
                ):
                    d2 += 4.0  # ~2 sigma soft penalty
                cost[i, j] = d2
        return cost

    def _birth_from_measurement(
        self,
        meas: Measurement,
        *,
        now_t: float,
        encoder_rad: float,
    ) -> str:
        """Admit a new piece with a freshly minted uuid."""
        piece_uuid = _uuid.uuid4().hex[:12]
        self.admit_with_uuid(
            piece_uuid=piece_uuid,
            measurement=meas,
            now_t=now_t,
            encoder_rad=encoder_rad,
        )
        return piece_uuid

    def admit_with_uuid(
        self,
        *,
        piece_uuid: str,
        measurement: Measurement,
        now_t: float,
        encoder_rad: float,
    ) -> PieceTrack:
        """Admit a new piece with a caller-provided uuid.

        Used by runtime callers that already mint piece_uuids elsewhere
        (e.g. the C4 runtime that shares uuids with its dispatch-side
        ``_PieceDossier``). Idempotent: re-admit returns the existing
        track without overwriting.
        """
        existing = self._tracks.get(piece_uuid)
        if existing is not None:
            return existing
        meas = measurement
        state = np.array([meas.a_meas, meas.r_meas, 0.0, 0.0], dtype=float)
        cov = self._config.initial_covariance()
        emb_mean: np.ndarray | None = None
        emb_count = 0
        if meas.appearance_embedding is not None:
            emb_mean = np.asarray(meas.appearance_embedding, dtype=float)
            emb_count = 1
        track = PieceTrack(
            piece_uuid=piece_uuid,
            channel=self._config.channel,
            state_mean=state,
            state_covariance=cov,
            last_observed_t=float(now_t),
            last_observed_encoder=float(encoder_rad),
            last_predicted_t=float(now_t),
            embedding_mean=emb_mean,
            embedding_count=emb_count,
            confirmed_real_observations=1 if meas.confirmed_real else 0,
            detection_observations=1,
            lifecycle_state=PieceLifecycleState.TENTATIVE,
        )
        if meas.raw_track_id is not None:
            track.raw_track_aliases.add(int(meas.raw_track_id))
            self._raw_id_index[int(meas.raw_track_id)] = piece_uuid
        self._tracks[piece_uuid] = track
        return track

    def update_with_measurement(
        self,
        piece_uuid: str,
        measurement: Measurement,
        *,
        now_t: float,
        encoder_rad: float,
    ) -> bool:
        """Public Kalman-update on an existing track. Returns False if
        the named track does not exist."""
        if piece_uuid not in self._tracks:
            return False
        self._kalman_update(piece_uuid, measurement, now_t=now_t, encoder_rad=encoder_rad)
        return True

    def _kalman_update(
        self,
        piece_uuid: str,
        meas: Measurement,
        *,
        now_t: float,
        encoder_rad: float,
    ) -> None:
        tr = self._tracks[piece_uuid]
        h = _H
        r = self._config.measurement_noise.matrix()
        s = h @ tr.state_covariance @ h.T + r
        try:
            s_inv = np.linalg.inv(s)
            k = tr.state_covariance @ h.T @ s_inv
        except np.linalg.LinAlgError:
            return
        z = np.array([meas.a_meas, meas.r_meas], dtype=float)
        innov = z - (h @ tr.state_mean)
        innov[0] = wrap_rad(float(innov[0]))
        # Innovation gate: a large residual most likely means the piece
        # was nudged, slipped, or — in tests — jumped to a synthetic
        # new position. Trying to blend the prediction toward the new
        # observation via the standard Kalman gain leaves the state
        # lagging by tens of degrees for several frames. Snap instead:
        # take the measurement as ground truth, reset the velocity
        # estimate to zero, and inflate covariance so the next update
        # converges quickly.
        d2 = float(innov.T @ s_inv @ innov)
        if d2 > self._config.snap_chi2_threshold:
            # Snap path: replace state and covariance entirely. Skip the
            # Kalman covariance update below — its gain ``k`` was computed
            # from the pre-snap state and would corrupt the freshly reset
            # covariance into negative-definite territory.
            tr.state_mean = np.array(
                [meas.a_meas, meas.r_meas, 0.0, 0.0], dtype=float
            )
            tr.state_covariance = self._config.initial_covariance()
        else:
            tr.state_mean = tr.state_mean + k @ innov
            tr.state_covariance = (np.eye(4) - k @ h) @ tr.state_covariance
        tr.state_mean[0] = wrap_rad(float(tr.state_mean[0]))
        tr.last_observed_t = float(now_t)
        tr.last_observed_encoder = float(encoder_rad)
        tr.last_predicted_t = float(now_t)
        tr.detection_observations += 1
        if meas.confirmed_real:
            tr.confirmed_real_observations += 1
        if meas.raw_track_id is not None:
            raw_id = int(meas.raw_track_id)
            tr.raw_track_aliases.add(raw_id)
            self._raw_id_index[raw_id] = piece_uuid
        if meas.appearance_embedding is not None:
            emb = np.asarray(meas.appearance_embedding, dtype=float)
            if tr.embedding_mean is None:
                tr.embedding_mean = emb
                tr.embedding_count = 1
            else:
                n = tr.embedding_count
                tr.embedding_mean = (tr.embedding_mean * n + emb) / (n + 1)
                tr.embedding_count = n + 1

    def _update_lifecycle(self, now_t: float) -> None:
        cfg = self._config
        to_finalize: list[str] = []
        for tr in self._tracks.values():
            if tr.lifecycle_state in (
                PieceLifecycleState.EJECTED,
                PieceLifecycleState.FINALIZED_LOST,
            ):
                continue
            silence = float(now_t) - float(tr.last_observed_t)
            # Promote tentative -> confirmed_unclassified when we have
            # enough real evidence.
            if (
                tr.lifecycle_state is PieceLifecycleState.TENTATIVE
                and tr.detection_observations >= cfg.confirm_min_detections
                and tr.confirmed_real_observations >= cfg.confirm_min_real
            ):
                tr.lifecycle_state = PieceLifecycleState.CONFIRMED_UNCLASSIFIED
            # Demote to LOST_COASTING when we have not seen a detection
            # for ``coast_after_silence_s``.
            if silence >= cfg.coast_after_silence_s and tr.lifecycle_state in (
                PieceLifecycleState.TENTATIVE,
                PieceLifecycleState.CONFIRMED_UNCLASSIFIED,
                PieceLifecycleState.CLASSIFIED_CONFIDENT,
                PieceLifecycleState.CLASSIFIED_IDENTITY_UNCERTAIN,
            ):
                tr.lifecycle_state = PieceLifecycleState.LOST_COASTING
            if (
                tr.lifecycle_state is PieceLifecycleState.LOST_COASTING
                and silence >= cfg.finalize_lost_after_silence_s
            ):
                to_finalize.append(tr.piece_uuid)
        for piece_uuid in to_finalize:
            self.finalize(piece_uuid, reason=PieceLifecycleState.FINALIZED_LOST)

    # ------------------------------------------------------------------
    # Lifecycle mutators (called from the runtime)

    def bind_classification(
        self,
        piece_uuid: str,
        *,
        class_label: str | None,
        class_confidence: float | None,
        identity_uncertain: bool = False,
    ) -> None:
        tr = self._tracks.get(piece_uuid)
        if tr is None:
            return
        tr.class_label = class_label
        tr.class_confidence = class_confidence
        tr.lifecycle_state = (
            PieceLifecycleState.CLASSIFIED_IDENTITY_UNCERTAIN
            if identity_uncertain
            else PieceLifecycleState.CLASSIFIED_CONFIDENT
        )

    def mark_clustered(self, piece_uuids: Iterable[str]) -> None:
        for piece_uuid in piece_uuids:
            tr = self._tracks.get(piece_uuid)
            if tr is None:
                continue
            tr.lifecycle_state = PieceLifecycleState.CLUSTERED

    def mark_ejected(self, piece_uuid: str) -> None:
        tr = self._tracks.get(piece_uuid)
        if tr is None:
            return
        tr.lifecycle_state = PieceLifecycleState.EJECTED

    def finalize(
        self,
        piece_uuid: str,
        *,
        reason: PieceLifecycleState = PieceLifecycleState.FINALIZED_LOST,
    ) -> None:
        tr = self._tracks.pop(piece_uuid, None)
        if tr is None:
            return
        for raw_id in list(tr.raw_track_aliases):
            if self._raw_id_index.get(raw_id) == piece_uuid:
                self._raw_id_index.pop(raw_id, None)
        # We deliberately do not retain the finalized track in-memory —
        # the run recorder is the durable history surface.

    # ------------------------------------------------------------------
    # Dispatch query — the posterior singleton check

    def chute_window_occupants(
        self,
        *,
        chute_center_rad: float,
        chute_half_width_rad: float,
        encoder_rad: float,
    ) -> tuple[PieceTrack, ...]:
        """Return chute-blocking tracks whose 2-sigma interval overlaps the
        chute window at the *current* tray angle.

        Each track's tray-frame angle ``a`` plus the encoder ``phi`` gives
        a world-frame angle; the chute window is fixed in world frame.
        """
        out: list[PieceTrack] = []
        for tr in self._tracks.values():
            if not is_chute_blocking(tr.lifecycle_state):
                continue
            world_angle = wrap_rad(float(tr.state_mean[0]) + float(encoder_rad))
            sigma = tr.angle_sigma_rad
            extent = 2.0 * sigma  # 2-sigma interval
            distance = abs(wrap_diff_rad(world_angle, chute_center_rad))
            if distance - extent <= chute_half_width_rad:
                out.append(tr)
        return tuple(out)

    # ------------------------------------------------------------------
    # Landing-lease API — the C3 to C4 software escapement.

    def request_landing_lease(
        self,
        *,
        predicted_arrival_t: float,
        predicted_landing_a: float,
        min_spacing_rad: float,
        now_t: float,
        lease_ttl_s: float = 1.5,
        requested_by: int | None = None,
    ) -> str | None:
        """Reserve a future landing slot, or refuse if it would clash.

        Refusal rule: at the predicted arrival time, the predicted angle
        of every existing PieceTrack and every other pending landing
        must be at least ``min_spacing_rad`` away from the proposed
        landing angle. The mathematics is "predict to t = arrival,
        check angular distance".

        Granted leases are recorded with a TTL so a C3 pulse that fails
        to deliver a piece does not orphan the slot forever. The C4
        admission/reconcile path is responsible for calling
        ``consume_landing_lease`` when the new track actually appears.
        """
        self._sweep_pending_landings(now_t)
        for tr in self._tracks.values():
            if tr.lifecycle_state in (
                PieceLifecycleState.EJECTED,
                PieceLifecycleState.FINALIZED_LOST,
            ):
                continue
            dt = max(0.0, predicted_arrival_t - tr.last_predicted_t)
            predicted_a = wrap_rad(
                float(tr.state_mean[0]) + float(tr.state_mean[2]) * dt
            )
            if abs(wrap_diff_rad(predicted_a, predicted_landing_a)) < min_spacing_rad:
                return None
        for pending in self._pending_landings.values():
            if (
                abs(wrap_diff_rad(pending.predicted_landing_a, predicted_landing_a))
                < min_spacing_rad
            ):
                return None

        lease_id = _uuid.uuid4().hex[:12]
        self._pending_landings[lease_id] = PendingLanding(
            lease_id=lease_id,
            predicted_arrival_t=float(predicted_arrival_t),
            predicted_landing_a=float(predicted_landing_a),
            granted_at=float(now_t),
            expires_at=float(now_t) + float(lease_ttl_s),
            requested_by=requested_by,
        )
        return lease_id

    def consume_landing_lease(self, lease_id: str) -> bool:
        return self._pending_landings.pop(lease_id, None) is not None

    def pending_landings(self) -> tuple[PendingLanding, ...]:
        return tuple(self._pending_landings.values())

    def _sweep_pending_landings(self, now_t: float) -> None:
        expired = [
            lease_id
            for lease_id, p in self._pending_landings.items()
            if p.expires_at <= now_t
        ]
        for lease_id in expired:
            self._pending_landings.pop(lease_id, None)

    def consume_oldest_pending_landing(self) -> PendingLanding | None:
        """Pop the oldest pending landing — used when a new track is
        admitted but the runtime cannot determine which lease produced
        it (e.g. raw-id mismatch). FIFO matches the physical handoff
        order: the first lease granted is the first piece to arrive."""
        if not self._pending_landings:
            return None
        first_id = next(iter(self._pending_landings))
        return self._pending_landings.pop(first_id, None)

    def is_singleton_in_chute(
        self,
        piece_uuid: str,
        *,
        chute_center_rad: float,
        chute_half_width_rad: float,
        encoder_rad: float,
    ) -> bool:
        """True iff exactly the named piece is inside the chute window
        and no other chute-blocking track overlaps it."""
        target = self._tracks.get(piece_uuid)
        if target is None:
            return False
        occupants = self.chute_window_occupants(
            chute_center_rad=chute_center_rad,
            chute_half_width_rad=chute_half_width_rad,
            encoder_rad=encoder_rad,
        )
        if len(occupants) != 1:
            return False
        return occupants[0].piece_uuid == piece_uuid


# ---------------------------------------------------------------------------
# Outcome reporting


@dataclass(slots=True)
class AssociationOutcome:
    """What ``associate_and_update`` did this frame.

    ``updates`` is a list of (piece_uuid, measurement_index) pairs;
    ``births`` is the count of measurements that produced new tracks.
    Used by the step debugger and by test assertions.
    """

    updates: list[tuple[str, int]] = field(default_factory=list)
    births: int = 0


@dataclass(slots=True)
class PendingLanding:
    """A reserved future landing for a piece in transit toward this ring.

    Created by ``PieceTrackBank.request_landing_lease`` and consumed by
    ``consume_landing_lease`` when the piece actually shows up. Holds a
    place in the bank's chute-spacing reasoning so C4 does not grant
    overlapping leases that would later force the trailing-safety guard
    to defer ejects.

    ``predicted_arrival_t`` is the wall time of expected arrival.
    ``predicted_landing_a`` is the tray-frame angle at which the new
    track is expected to appear (typically the channel's intake angle).
    """

    lease_id: str
    predicted_arrival_t: float
    predicted_landing_a: float
    granted_at: float
    expires_at: float
    requested_by: int | None = None


__all__ = [
    "AssociationOutcome",
    "CameraTrayCalibration",
    "Measurement",
    "MeasurementNoise",
    "PieceLifecycleState",
    "PieceTrack",
    "PieceTrackBank",
    "PieceTrackBankConfig",
    "ProcessNoise",
    "is_chute_blocking",
    "is_dispatch_eligible",
    "wrap_diff_rad",
    "wrap_rad",
]
