"""Tests for the leader-wins multi-drop collision policy.

When the drop candidate has a trailing interferer inside the clearance
window, the old behavior flipped BOTH to ``multi_drop_fail``. Leader-wins
keeps the trailer pending and drops only the classified leader.
"""

from __future__ import annotations

from types import SimpleNamespace

from defs.known_object import ClassificationStatus, KnownObject
from subsystems.classification_channel.running import Running
from subsystems.classification_channel.zone_manager import ZoneManager


class _Logger:
    def debug(self, *args, **kwargs) -> None:
        pass

    def info(self, *args, **kwargs) -> None:
        pass

    def warning(self, *args, **kwargs) -> None:
        pass

    def error(self, *args, **kwargs) -> None:
        pass


class _RuntimeStats:
    def __init__(self) -> None:
        self.leader_wins_events: list[dict[str, object]] = []
        self.blocked_reasons: list[tuple[str, str]] = []

    def observeStateTransition(self, *args, **kwargs) -> None:
        pass

    def observeBlockedReason(self, channel: str, reason: str) -> None:
        self.blocked_reasons.append((str(channel), str(reason)))

    def observeMultiDropLeaderWins(self, **meta) -> None:
        self.leader_wins_events.append(dict(meta))


class _Stepper:
    stopped = True

    def degrees_for_microsteps(self, steps: int) -> float:
        return float(steps) / 10.0

    def move_degrees(self, degrees: float) -> bool:
        return True

    def set_speed_limits(self, *args, **kwargs) -> None:
        pass

    def set_acceleration(self, *args, **kwargs) -> None:
        pass


class _Transport:
    """Fake transport where the ``zone_manager`` is a real ``ZoneManager``.

    ``_pickDropCandidate`` queries the zone manager directly, so supplying
    a real one is the tightest loop for exercising the collision policy.
    """

    def __init__(self, zone_manager: ZoneManager, pieces: list[KnownObject]) -> None:
        self.zone_manager = zone_manager
        self._pieces = {piece.uuid: piece for piece in pieces}
        self.fallbacks: list[tuple[str, ClassificationStatus]] = []

    def activePieces(self) -> list[KnownObject]:
        return list(self._pieces.values())

    def resolveFallbackClassification(
        self,
        uuid: str,
        *,
        status: ClassificationStatus,
    ) -> bool:
        piece = self._pieces.get(uuid)
        if piece is None:
            return False
        if piece.classification_status not in {
            ClassificationStatus.pending,
            ClassificationStatus.classifying,
        }:
            return False
        piece.classification_status = status
        self.fallbacks.append((uuid, status))
        return True


class _Shared:
    distribution_ready = True

    def set_classification_gate(self, *args, **kwargs) -> None:
        pass

    def set_distribution_gate(self, *args, **kwargs) -> None:
        pass


def _make_config(
    *,
    leader_wins_policy: bool = True,
    leader_wins_requires_classified: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        use_dynamic_zones=True,
        intake_angle_deg=305.0,
        intake_body_half_width_deg=10.0,
        intake_guard_deg=28.0,
        drop_angle_deg=30.0,
        drop_tolerance_deg=14.0,
        point_of_no_return_deg=18.0,
        recognition_window_deg=60.0,
        positioning_window_deg=48.0,
        max_zones=4,
        hood_dwell_ms=1200,
        size_downgrade_confirmations=3,
        stale_zone_timeout_s=3.0,
        exit_release_overlap_ratio=0.5,
        exit_release_shimmy_amplitude_deg=1.5,
        exit_release_shimmy_cycles=2,
        exit_release_shimmy_microsteps_per_second=4200,
        exit_release_shimmy_acceleration_microsteps_per_second_sq=9000,
        leader_wins_policy=leader_wins_policy,
        leader_wins_requires_classified=leader_wins_requires_classified,
        size_classes=(
            SimpleNamespace(
                name="M",
                max_measured_half_width_deg=360.0,
                body_half_width_deg=4.0,
                soft_guard_deg=2.0,
                hard_guard_deg=3.0,
            ),
        ),
    )


def _register_zone(
    zone_manager: ZoneManager,
    *,
    piece_uuid: str,
    center_deg: float,
    status: ClassificationStatus,
) -> None:
    zone_manager.register_provisional_piece(
        piece_uuid=piece_uuid,
        track_global_id=None,
        classification_status=status,
        now_mono=0.0,
    )
    zone = zone_manager.zone_for_piece(piece_uuid)
    assert zone is not None
    # Overwrite with desired center_deg / small body so interferer math is
    # unambiguous.
    from subsystems.classification_channel.zone_manager import ExclusionZone

    zone_manager._zones_by_piece_uuid[piece_uuid] = ExclusionZone(
        piece_uuid=piece_uuid,
        track_global_id=None,
        center_deg=center_deg,
        measured_half_width_deg=4.0,
        size_class="M",
        body_half_width_deg=4.0,
        soft_guard_deg=2.0,
        hard_guard_deg=3.0,
        last_seen_mono=0.0,
        stale=False,
        classification_status=status,
    )


def _build_running(
    config: SimpleNamespace,
    pieces: list[KnownObject],
    zone_setup: list[tuple[str, float, ClassificationStatus]],
) -> tuple[Running, _Transport, _RuntimeStats]:
    zone_manager = ZoneManager(config)  # type: ignore[arg-type]
    for piece_uuid, center_deg, status in zone_setup:
        _register_zone(
            zone_manager,
            piece_uuid=piece_uuid,
            center_deg=center_deg,
            status=status,
        )
    transport = _Transport(zone_manager, pieces)
    runtime_stats = _RuntimeStats()
    running = Running(
        irl=SimpleNamespace(carousel_stepper=_Stepper()),
        irl_config=SimpleNamespace(
            classification_channel_config=config,
            feeder_config=SimpleNamespace(
                classification_channel_eject=SimpleNamespace(
                    steps_per_pulse=90,
                    microsteps_per_second=3400,
                    acceleration_microsteps_per_second_sq=2500,
                )
            ),
        ),
        gc=SimpleNamespace(
            logger=_Logger(),
            runtime_stats=runtime_stats,
        ),
        shared=_Shared(),
        transport=transport,
        vision=None,
        event_queue=None,
    )
    return running, transport, runtime_stats


def test_a_classified_leader_with_trailing_pending_interferer_spares_trailer() -> None:
    config = _make_config()
    leader = KnownObject(
        uuid="leader",
        classification_status=ClassificationStatus.classified,
        part_id="3001",
    )
    trailer = KnownObject(
        uuid="trailer",
        classification_status=ClassificationStatus.pending,
    )
    running, transport, stats = _build_running(
        config,
        [leader, trailer],
        [
            ("leader", 30.0, ClassificationStatus.classified),
            # 23° = drop - 7° → strictly behind leader (approach side)
            ("trailer", 23.0, ClassificationStatus.pending),
        ],
    )

    drop_uuid = running._pickDropCandidate()

    assert drop_uuid == "leader"
    assert trailer.classification_status == ClassificationStatus.pending
    assert leader.classification_status == ClassificationStatus.classified
    assert transport.fallbacks == []
    assert len(stats.leader_wins_events) == 1
    assert stats.leader_wins_events[0] == {"reason": "drop_window_collision"}


def test_b_pending_leader_with_trailing_interferer_marks_both_fail() -> None:
    config = _make_config()
    leader = KnownObject(
        uuid="leader",
        classification_status=ClassificationStatus.pending,
    )
    trailer = KnownObject(
        uuid="trailer",
        classification_status=ClassificationStatus.pending,
    )
    running, transport, stats = _build_running(
        config,
        [leader, trailer],
        [
            ("leader", 30.0, ClassificationStatus.pending),
            ("trailer", 23.0, ClassificationStatus.pending),
        ],
    )

    running._pickDropCandidate()

    fallback_statuses = {uuid: status for uuid, status in transport.fallbacks}
    assert fallback_statuses.get("leader") == ClassificationStatus.multi_drop_fail
    assert fallback_statuses.get("trailer") == ClassificationStatus.multi_drop_fail
    assert stats.leader_wins_events == []


def test_c_classified_leader_with_two_interferers_marks_all_fail() -> None:
    config = _make_config()
    leader = KnownObject(
        uuid="leader",
        classification_status=ClassificationStatus.classified,
        part_id="3001",
    )
    trailer_one = KnownObject(
        uuid="trailer_one",
        classification_status=ClassificationStatus.pending,
    )
    trailer_two = KnownObject(
        uuid="trailer_two",
        classification_status=ClassificationStatus.pending,
    )
    running, transport, stats = _build_running(
        config,
        [leader, trailer_one, trailer_two],
        [
            ("leader", 30.0, ClassificationStatus.classified),
            ("trailer_one", 24.0, ClassificationStatus.pending),
            ("trailer_two", 22.0, ClassificationStatus.pending),
        ],
    )

    running._pickDropCandidate()

    fallback_statuses = {uuid: status for uuid, status in transport.fallbacks}
    # Leader is classified so resolveFallbackClassification won't flip it,
    # but the two trailers must flip.
    assert fallback_statuses.get("trailer_one") == ClassificationStatus.multi_drop_fail
    assert fallback_statuses.get("trailer_two") == ClassificationStatus.multi_drop_fail
    assert leader.classification_status == ClassificationStatus.classified
    assert stats.leader_wins_events == []


def test_d_interferer_ahead_of_leader_marks_both_fail() -> None:
    config = _make_config()
    leader = KnownObject(
        uuid="leader",
        classification_status=ClassificationStatus.classified,
        part_id="3001",
    )
    ahead = KnownObject(
        uuid="ahead",
        classification_status=ClassificationStatus.pending,
    )
    running, transport, stats = _build_running(
        config,
        [leader, ahead],
        [
            ("leader", 30.0, ClassificationStatus.classified),
            # 35° = drop + 5° → ahead of leader in carousel motion
            ("ahead", 35.0, ClassificationStatus.pending),
        ],
    )

    running._pickDropCandidate()

    fallback_statuses = {uuid: status for uuid, status in transport.fallbacks}
    assert fallback_statuses.get("ahead") == ClassificationStatus.multi_drop_fail
    assert stats.leader_wins_events == []


def test_e_leader_wins_policy_disabled_falls_back_to_old_behavior() -> None:
    config = _make_config(leader_wins_policy=False)
    leader = KnownObject(
        uuid="leader",
        classification_status=ClassificationStatus.classified,
        part_id="3001",
    )
    trailer = KnownObject(
        uuid="trailer",
        classification_status=ClassificationStatus.pending,
    )
    running, transport, stats = _build_running(
        config,
        [leader, trailer],
        [
            ("leader", 30.0, ClassificationStatus.classified),
            ("trailer", 23.0, ClassificationStatus.pending),
        ],
    )

    running._pickDropCandidate()

    fallback_statuses = {uuid: status for uuid, status in transport.fallbacks}
    assert fallback_statuses.get("trailer") == ClassificationStatus.multi_drop_fail
    assert stats.leader_wins_events == []
