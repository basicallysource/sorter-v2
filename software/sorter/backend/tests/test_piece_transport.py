import queue
import unittest

from defs.known_object import ClassificationStatus
from piece_transport import ClassificationChannelTransport
from subsystems.classification.carousel import Carousel


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
        )

        self.assertTrue(resolved)
        self.assertEqual("3001", piece.part_id)
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
        self.assertEqual(2, transport.getActivePieceCount())


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


if __name__ == "__main__":
    unittest.main()
