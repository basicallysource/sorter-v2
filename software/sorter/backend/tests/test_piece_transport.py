import queue
import unittest
from unittest import mock

from defs.known_object import (
    CarouselMotionSample,
    ClassificationStatus,
    KnownObject,
    PieceStage,
)
from irl.config import ClassificationChannelConfig
import piece_transport
from piece_transport import ClassificationChannelTransport
from subsystems.classification.carousel import Carousel
from subsystems.classification_channel.zone_manager import TrackAngularExtent
from utils.event import knownObjectToEvent


class _Logger:
    def info(self, *args, **kwargs) -> None:
        pass


class ClassificationChannelTransportTests(unittest.TestCase):
    def test_register_resolve_park_and_drop_piece(self) -> None:
        transport = ClassificationChannelTransport()

        piece = transport.registerIncomingPiece()
        self.assertIs(piece, transport.getPieceAtClassification())
        self.assertIsNone(transport.getPieceAtWaitZone())
        self.assertIsNone(transport.getPieceForDistributionPositioning())
        self.assertIsNone(transport.getPieceForDistributionDrop())

        transport.markPendingClassification(piece)
        resolved = transport.resolveClassification(
            piece.uuid,
            "3001",
            "5",
            "Red",
            0.97,
            part_name="Brick 2 x 4",
            part_category="Brick",
        )

        self.assertTrue(resolved)
        self.assertEqual("3001", piece.part_id)
        self.assertEqual("Brick 2 x 4", piece.part_name)
        self.assertEqual("Brick", piece.part_category)
        self.assertEqual("5", piece.color_id)
        self.assertEqual("Red", piece.color_name)
        self.assertEqual(ClassificationStatus.classified, piece.classification_status)

        first_advance = transport.advanceTransport()
        self.assertIsNone(first_advance.piece_at_classification)
        self.assertIsNone(first_advance.piece_for_distribution_drop)
        self.assertIs(piece, transport.getPieceAtWaitZone())
        self.assertIs(piece, transport.getPieceForDistributionPositioning())
        self.assertIsNone(transport.getPieceForDistributionDrop())

        second_advance = transport.advanceTransport()
        self.assertIsNone(second_advance.piece_at_classification)
        self.assertIs(piece, second_advance.piece_for_distribution_drop)
        self.assertIsNone(transport.getPieceAtWaitZone())
        self.assertIs(piece, transport.getPieceForDistributionDrop())
        self.assertIsNone(transport.getPieceAtClassification())

    def test_single_pulse_can_drop_wait_piece_and_park_next_piece(self) -> None:
        transport = ClassificationChannelTransport()

        first = transport.registerIncomingPiece()
        self.assertEqual(1, transport.getActivePieceCount())
        transport.advanceTransport()
        self.assertEqual(1, transport.getActivePieceCount())
        self.assertIs(first, transport.getPieceAtWaitZone())

        second = transport.registerIncomingPiece()
        self.assertEqual(2, transport.getActivePieceCount())
        self.assertIs(second, transport.getPieceAtClassification())

        advance = transport.advanceTransport()
        self.assertIs(first, advance.piece_for_distribution_drop)
        self.assertIs(second, transport.getPieceAtWaitZone())
        self.assertIs(first, transport.getPieceForDistributionDrop())
        self.assertIsNone(transport.getPieceAtClassification())
        # ``first`` has physically dropped into the distribution chute — it
        # no longer occupies the classification channel for admission
        # purposes, so only ``second`` (at wait) counts as active.
        self.assertEqual(1, transport.getActivePieceCount())

    def test_dynamic_mode_tracks_active_pieces_by_track_id(self) -> None:
        transport = ClassificationChannelTransport()
        config = ClassificationChannelConfig()
        transport.configureDynamicMode(config)

        piece = transport.registerIncomingPiece(tracked_global_id=41)
        for ts in (1.0, 2.0, 3.0):
            zones, expired = transport.updateTrackedPieces(
                [
                    TrackAngularExtent(
                        global_id=41,
                        center_deg=24.0,
                        half_width_deg=5.0,
                        last_seen_ts=ts,
                        hit_count=4,
                    )
                ]
            )

        self.assertEqual([], expired)
        self.assertEqual(1, len(zones))
        self.assertEqual(1, transport.getActivePieceCount())
        self.assertIs(piece, transport.pieceForTrack(41))
        self.assertEqual("S", piece.classification_channel_size_class)
        self.assertAlmostEqual(24.0, piece.classification_channel_zone_center_deg)

    def test_dynamic_mode_drop_removes_piece_and_sets_exit_buffer(self) -> None:
        transport = ClassificationChannelTransport()
        config = ClassificationChannelConfig()
        transport.configureDynamicMode(config)

        piece = transport.registerIncomingPiece(tracked_global_id=11)
        transport.updateTrackedPieces(
            [
                TrackAngularExtent(
                    global_id=11,
                    center_deg=178.0,
                    half_width_deg=7.0,
                    last_seen_ts=1.0,
                    hit_count=5,
                )
            ]
        )
        transport.setPositioningPiece(piece.uuid)

        advance = transport.advanceTransport(dropped_uuid=piece.uuid)

        self.assertIs(piece, advance.piece_for_distribution_drop)
        self.assertIs(piece, transport.getPieceForDistributionDrop())
        self.assertIsNone(transport.pieceForTrack(11))
        self.assertEqual(0, transport.getActivePieceCount())
        self.assertIsNone(transport.getPieceForDistributionPositioning())

    def test_dynamic_mode_exit_piece_clears_on_next_advance(self) -> None:
        """``_exit_piece`` must survive until the NEXT advanceTransport.

        The distribution Sending state reads
        ``getPieceForDistributionDrop()`` after the chute-settle timer to
        commit the drop. That read must keep returning the dropped piece
        until the next carousel pulse advances the transport — otherwise
        Sending races against its own commit and loses the reference to
        the piece it was dropping.
        """
        transport = ClassificationChannelTransport()
        config = ClassificationChannelConfig()
        transport.configureDynamicMode(config)

        piece = transport.registerIncomingPiece(tracked_global_id=77)
        transport.updateTrackedPieces(
            [
                TrackAngularExtent(
                    global_id=77,
                    center_deg=30.0,
                    half_width_deg=6.0,
                    last_seen_ts=1.0,
                    hit_count=4,
                )
            ]
        )
        transport.setPositioningPiece(piece.uuid)

        advance = transport.advanceTransport(dropped_uuid=piece.uuid)
        self.assertIs(piece, advance.piece_for_distribution_drop)
        self.assertIs(piece, transport.getPieceForDistributionDrop())

        # Second advance with no new drop: exit buffer must clear on the
        # very next pulse so a subsequent piece's getPieceForDistributionDrop
        # doesn't resurface the already-dropped uuid.
        next_advance = transport.advanceTransport()
        self.assertIsNone(next_advance.piece_for_distribution_drop)
        self.assertIsNone(transport.getPieceForDistributionDrop())

    def test_dynamic_mode_marks_dropped_track_as_lingering_until_tracker_first_seen_changes(self) -> None:
        transport = ClassificationChannelTransport()
        config = ClassificationChannelConfig()
        transport.configureDynamicMode(config)

        piece = transport.registerIncomingPiece(tracked_global_id=77)
        piece.feeding_started_at = 123.4
        transport.updateTrackedPieces(
            [
                TrackAngularExtent(
                    global_id=77,
                    center_deg=30.0,
                    half_width_deg=6.0,
                    last_seen_ts=1.0,
                    hit_count=4,
                    first_seen_ts=123.4,
                )
            ]
        )
        transport.setPositioningPiece(piece.uuid)

        transport.advanceTransport(dropped_uuid=piece.uuid)

        self.assertTrue(
            transport.shouldIgnoreRecoveredTrack(
                77,
                first_seen_ts=123.4,
            )
        )
        self.assertTrue(
            transport.shouldIgnoreRecoveredTrack(
                77,
                first_seen_ts=124.1,
            )
        )
        self.assertFalse(
            transport.shouldIgnoreRecoveredTrack(
                77,
                first_seen_ts=130.0,
            )
        )

    def test_fallback_classification_clears_previous_distribution_target(self) -> None:
        transport = ClassificationChannelTransport()
        config = ClassificationChannelConfig()
        transport.configureDynamicMode(config)

        piece = transport.registerIncomingPiece(tracked_global_id=21)
        piece.category_id = "plates"
        piece.destination_bin = (0, 1, 2)
        transport.markPendingClassification(piece)

        resolved = transport.resolveFallbackClassification(
            piece.uuid,
            status=ClassificationStatus.multi_drop_fail,
        )

        self.assertTrue(resolved)
        self.assertIsNone(piece.part_id)
        self.assertIsNone(piece.category_id)
        self.assertIsNone(piece.destination_bin)
        self.assertEqual(ClassificationStatus.multi_drop_fail, piece.classification_status)

    def test_dynamic_mode_expires_untracked_piece_after_zone_timeout(self) -> None:
        transport = ClassificationChannelTransport()
        config = ClassificationChannelConfig()
        config.stale_zone_timeout_s = 0.1
        transport.configureDynamicMode(config)

        piece = transport.registerIncomingPiece(tracked_global_id=33)
        transport.updateTrackedPieces(
            [
                TrackAngularExtent(
                    global_id=33,
                    center_deg=12.0,
                    half_width_deg=6.0,
                    last_seen_ts=1.0,
                    hit_count=4,
                )
            ]
        )

        self.assertEqual(1, transport.getActivePieceCount())
        _zones, expired = transport.updateTrackedPieces([])

        # Still provisionally alive until the zone timeout elapses.
        self.assertEqual(1, transport.getActivePieceCount())
        self.assertEqual([], expired)

        import time

        time.sleep(0.12)
        _zones, expired = transport.updateTrackedPieces([])

        self.assertEqual(0, transport.getActivePieceCount())
        self.assertIsNone(transport.pieceForTrack(33))
        self.assertIsNone(transport.getPieceAtClassification())
        # The expired piece must be returned so the caller can broadcast a
        # terminal KnownObject event, but a zone-loss must NOT masquerade as
        # a successful physical distribution.
        self.assertEqual(1, len(expired))
        self.assertIs(piece, expired[0])
        self.assertEqual(PieceStage.created, expired[0].stage)
        self.assertIsNone(expired[0].distributed_at)
        self.assertEqual("lost", expired[0].classification_channel_zone_state)

    def test_dynamic_mode_reset_clears_virtual_transport_state(self) -> None:
        transport = ClassificationChannelTransport()
        config = ClassificationChannelConfig()
        transport.configureDynamicMode(config)

        piece = transport.registerIncomingPiece(tracked_global_id=55)
        transport.setPositioningPiece(piece.uuid)
        transport.advanceTransport(dropped_uuid=piece.uuid)

        self.assertIsNotNone(transport.getPieceForDistributionDrop())
        transport.resetDynamicState()

        self.assertEqual(0, transport.getActivePieceCount())
        self.assertIsNone(transport.getPieceForDistributionDrop())
        self.assertIsNone(transport.getPieceAtClassification())
        self.assertIsNone(transport.getPieceForDistributionPositioning())

    def test_dynamic_mode_tracks_piece_motion_sync_against_carousel_rotation(self) -> None:
        transport = ClassificationChannelTransport()
        config = ClassificationChannelConfig()
        transport.configureDynamicMode(config)

        piece = transport.registerIncomingPiece(tracked_global_id=91)
        transport.updateTrackedPieces(
            [
                TrackAngularExtent(
                    global_id=91,
                    center_deg=10.0,
                    half_width_deg=6.0,
                    last_seen_ts=1.0,
                    hit_count=4,
                )
            ],
            carousel_angle_deg=100.0,
        )
        transport.updateTrackedPieces(
            [
                TrackAngularExtent(
                    global_id=91,
                    center_deg=16.0,
                    half_width_deg=6.0,
                    last_seen_ts=2.0,
                    hit_count=5,
                )
            ],
            carousel_angle_deg=106.0,
        )
        transport.updateTrackedPieces(
            [
                TrackAngularExtent(
                    global_id=91,
                    center_deg=19.0,
                    half_width_deg=6.0,
                    last_seen_ts=3.0,
                    hit_count=6,
                )
            ],
            carousel_angle_deg=112.0,
        )

        self.assertEqual(2, piece.carousel_motion_sample_count)
        self.assertEqual(1, piece.carousel_motion_under_sync_sample_count)
        self.assertEqual(0, piece.carousel_motion_over_sync_sample_count)
        self.assertAlmostEqual(0.75, piece.carousel_motion_sync_ratio_avg)
        self.assertAlmostEqual(0.5, piece.carousel_motion_sync_ratio_min)
        self.assertAlmostEqual(1.0, piece.carousel_motion_sync_ratio_max)
        self.assertAlmostEqual(0.825, piece.carousel_motion_sync_ratio)
        self.assertAlmostEqual(3.0, piece.carousel_motion_piece_speed_deg_per_s)
        self.assertAlmostEqual(6.0, piece.carousel_motion_platter_speed_deg_per_s)
        self.assertEqual(2, len(piece.carousel_motion_samples))
        self.assertAlmostEqual(0.5, piece.carousel_motion_samples[-1].sync_ratio)


class RegisterIncomingPieceIdempotencyTests(unittest.TestCase):
    """Phase 1: registerIncomingPiece must not mint a second uuid for the
    same physical piece across tracker glitches."""

    def _make_dynamic_transport(self) -> ClassificationChannelTransport:
        transport = ClassificationChannelTransport()
        config = ClassificationChannelConfig()
        transport.configureDynamicMode(config)
        return transport

    def test_register_same_global_id_returns_same_piece(self) -> None:
        transport = self._make_dynamic_transport()
        # No DB dossier; make both helpers return None so the cascade
        # falls through to the active-pieces lookup / fresh-uuid branch.
        with mock.patch.object(
            piece_transport.ClassificationChannelTransport,
            "_rehydrateFromDossierByTrackedGlobalId",
            return_value=None,
        ), mock.patch.object(
            piece_transport.ClassificationChannelTransport,
            "_rehydrateFromDossierByPieceUuid",
            return_value=None,
        ):
            first = transport.registerIncomingPiece(tracked_global_id=42)
            second = transport.registerIncomingPiece(tracked_global_id=42)

        self.assertIs(first, second)
        self.assertEqual(first.uuid, second.uuid)
        self.assertEqual(1, len(transport.activePieces()))

    def test_recover_existing_piece_rehydrates_from_dossier(self) -> None:
        transport = self._make_dynamic_transport()
        dossier_payload = {
            "uuid": "abc",
            "tracked_global_id": 7,
            "created_at": 1000.0,
            "updated_at": 1100.0,
            "stage": "created",
            "classification_status": "classified",
            "part_id": "3001",
            "part_name": "Brick 2 x 4",
            "color_id": "4",
            "color_name": "Red",
            "confidence": 0.91,
            "destination_bin": [1, 2, 3],
            "first_carousel_seen_ts": 1050.0,
            "first_carousel_seen_angle_deg": 42.5,
            "carousel_motion_samples": [
                {
                    "observed_at": 1060.0,
                    "piece_angle_deg": 10.0,
                    "carousel_angle_deg": 20.0,
                    "piece_speed_deg_per_s": 1.0,
                    "carousel_speed_deg_per_s": 2.0,
                    "sync_ratio": 0.5,
                }
            ],
        }

        def _by_gid(gid: int):
            return dossier_payload if int(gid) == 7 else None

        def _by_uuid(piece_uuid: str):
            return dossier_payload if piece_uuid == "abc" else None

        with mock.patch.object(
            piece_transport.ClassificationChannelTransport,
            "_rehydrateFromDossierByPieceUuid",
            side_effect=lambda self_, piece_uuid: None,
            autospec=True,
        ):
            with mock.patch(
                "local_state.get_piece_dossier_by_tracked_global_id",
                side_effect=_by_gid,
            ):
                obj = transport.registerIncomingPiece(tracked_global_id=7)

        self.assertEqual("abc", obj.uuid)
        self.assertEqual(7, obj.tracked_global_id)
        self.assertEqual("3001", obj.part_id)
        self.assertEqual("Brick 2 x 4", obj.part_name)
        self.assertEqual((1, 2, 3), obj.destination_bin)
        self.assertEqual(
            ClassificationStatus.classified, obj.classification_status
        )
        self.assertAlmostEqual(1050.0, obj.first_carousel_seen_ts)
        self.assertAlmostEqual(42.5, obj.first_carousel_seen_angle_deg)
        self.assertEqual(1, len(obj.carousel_motion_samples))
        self.assertAlmostEqual(0.5, obj.carousel_motion_samples[0].sync_ratio)
        self.assertIs(obj, transport.pieceForTrack(7))
        self.assertEqual(1, len(transport.activePieces()))

    def test_resume_existing_piece_hydrates_from_db(self) -> None:
        transport = self._make_dynamic_transport()
        dossier_payload = {
            "uuid": "abc",
            "tracked_global_id": 11,
            "created_at": 500.0,
            "updated_at": 600.0,
            "stage": "created",
            "classification_status": "pending",
            "feeding_started_at": 510.0,
        }

        with mock.patch(
            "local_state.get_piece_dossier",
            return_value=dossier_payload,
        ):
            obj = transport.resumeExistingPiece("abc")

        self.assertIsNotNone(obj)
        assert obj is not None
        self.assertEqual("abc", obj.uuid)
        self.assertEqual(11, obj.tracked_global_id)
        self.assertAlmostEqual(510.0, obj.feeding_started_at)
        self.assertIs(obj, transport.pieceForTrack(11))
        self.assertEqual(
            "abc", transport.get_piece_uuid_for_tracked_global_id(11)
        )

        # Subsequent registerIncomingPiece(gid=11) must NOT mint a new uuid.
        with mock.patch(
            "local_state.get_piece_dossier_by_tracked_global_id",
            return_value=dossier_payload,
        ):
            repeated = transport.registerIncomingPiece(tracked_global_id=11)
        self.assertIs(obj, repeated)
        self.assertEqual(1, len(transport.activePieces()))

    def test_resume_existing_piece_returns_none_when_dossier_missing(
        self,
    ) -> None:
        transport = self._make_dynamic_transport()
        with mock.patch(
            "local_state.get_piece_dossier",
            return_value=None,
        ):
            self.assertIsNone(transport.resumeExistingPiece("no-such-uuid"))

    def test_register_with_explicit_piece_uuid_uses_it(self) -> None:
        """Phase 4: when the C3 tracker early-bound a piece_uuid and passes
        it through the extent, ``registerIncomingPiece`` must reuse that
        uuid instead of minting a fresh one."""
        transport = self._make_dynamic_transport()
        # No DB dossier for this gid / uuid — the cascade must fall through
        # to the explicit-uuid branch and create the piece with that uuid.
        with mock.patch.object(
            piece_transport.ClassificationChannelTransport,
            "_rehydrateFromDossierByTrackedGlobalId",
            return_value=None,
        ), mock.patch.object(
            piece_transport.ClassificationChannelTransport,
            "_rehydrateFromDossierByPieceUuid",
            return_value=None,
        ):
            obj = transport.registerIncomingPiece(
                tracked_global_id=99,
                piece_uuid="phase4-uuid",
            )

        self.assertEqual("phase4-uuid", obj.uuid)
        self.assertEqual(99, obj.tracked_global_id)
        self.assertEqual(
            "phase4-uuid", transport.get_piece_uuid_for_tracked_global_id(99)
        )
        self.assertEqual(1, len(transport.activePieces()))


class CarouselTransportTests(unittest.TestCase):
    def test_carousel_transport_interface_maps_existing_positions(self) -> None:
        transport = Carousel(_Logger(), queue.Queue())
        self.assertEqual(0, transport.getActivePieceCount())

        piece = transport.registerIncomingPiece()
        self.assertEqual(1, transport.getActivePieceCount())
        self.assertIsNone(transport.getPieceAtClassification())

        first_advance = transport.advanceTransport()
        self.assertIs(piece, first_advance.piece_at_classification)
        self.assertIs(piece, transport.getPieceAtClassification())
        self.assertIsNone(transport.getPieceForDistributionPositioning())
        self.assertIsNone(transport.getPieceForDistributionDrop())

        second_advance = transport.advanceTransport()
        self.assertIsNone(second_advance.piece_at_classification)
        self.assertIs(piece, transport.getPieceForDistributionPositioning())

        third_advance = transport.advanceTransport()
        self.assertIs(piece, third_advance.piece_for_distribution_drop)
        self.assertIs(piece, transport.getPieceForDistributionDrop())
        self.assertEqual(1, transport.getActivePieceCount())


class KnownObjectDropSnapshotTests(unittest.TestCase):
    def test_drop_snapshot_defaults_to_none(self) -> None:
        piece = KnownObject()
        self.assertIsNone(piece.drop_snapshot)

    def test_drop_snapshot_propagates_to_event(self) -> None:
        piece = KnownObject()
        # A trivial base64 payload is enough — the event layer just passes
        # the string through to the WS payload without decoding.
        piece.drop_snapshot = "iVBORw0KGgoFAKE=="
        event = knownObjectToEvent(piece)
        self.assertEqual("iVBORw0KGgoFAKE==", event.data.drop_snapshot)

    def test_drop_snapshot_omitted_serializes_as_none(self) -> None:
        piece = KnownObject()
        event = knownObjectToEvent(piece)
        self.assertIsNone(event.data.drop_snapshot)

    def test_carousel_motion_metrics_propagate_to_event(self) -> None:
        piece = KnownObject(
            carousel_motion_sync_ratio=0.92,
            carousel_motion_sync_ratio_avg=0.88,
            carousel_motion_sync_ratio_min=0.61,
            carousel_motion_sync_ratio_max=1.08,
            carousel_motion_piece_speed_deg_per_s=5.5,
            carousel_motion_platter_speed_deg_per_s=6.0,
            carousel_motion_sample_count=4,
            carousel_motion_under_sync_sample_count=2,
            carousel_motion_over_sync_sample_count=0,
        )
        piece.carousel_motion_samples.append(
            CarouselMotionSample(
                observed_at=123.0,
                piece_angle_deg=41.0,
                carousel_angle_deg=84.0,
                piece_speed_deg_per_s=5.5,
                carousel_speed_deg_per_s=6.0,
                sync_ratio=0.92,
            )
        )

        event = knownObjectToEvent(piece)

        self.assertAlmostEqual(0.92, event.data.carousel_motion_sync_ratio)
        self.assertAlmostEqual(0.88, event.data.carousel_motion_sync_ratio_avg)
        self.assertEqual(4, event.data.carousel_motion_sample_count)
        self.assertEqual(1, len(event.data.carousel_motion_samples))
        self.assertAlmostEqual(0.92, event.data.carousel_motion_samples[0].sync_ratio)


if __name__ == "__main__":
    unittest.main()
