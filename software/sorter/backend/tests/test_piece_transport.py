import queue
import unittest

from defs.known_object import ClassificationStatus, KnownObject, PieceStage
from irl.config import ClassificationChannelConfig
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
        # terminal KnownObject event; ``stage`` + ``distributed_at`` are
        # already stamped so the frontend drops it from the upcoming list
        # the moment the re-acquired track spawns a fresh uuid.
        self.assertEqual(1, len(expired))
        self.assertIs(piece, expired[0])
        self.assertEqual(PieceStage.distributed, expired[0].stage)
        self.assertIsNotNone(expired[0].distributed_at)

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


if __name__ == "__main__":
    unittest.main()
