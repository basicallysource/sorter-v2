import unittest

from defs.known_object import KnownObject
from piece_transport import ClassificationChannelTransport
from utils.event import knownObjectToEvent


class ClassificationChannelTransportTests(unittest.TestCase):
    def test_placed_piece_moves_to_the_drop_slot_when_flung(self) -> None:
        transport = ClassificationChannelTransport()
        piece = KnownObject()

        transport.placePieceForDistribution(piece)
        self.assertIs(piece, transport.getPieceForDistributionPositioning())
        self.assertIsNone(transport.getPieceForDistributionDrop())

        transport.advanceTransport()
        self.assertIsNone(transport.getPieceForDistributionPositioning())
        self.assertIs(piece, transport.getPieceForDistributionDrop())

    def test_next_piece_replaces_the_dropped_one_on_the_next_fling(self) -> None:
        transport = ClassificationChannelTransport()
        first, second = KnownObject(), KnownObject()

        transport.placePieceForDistribution(first)
        transport.advanceTransport()
        transport.placePieceForDistribution(second)
        self.assertIs(first, transport.getPieceForDistributionDrop())

        transport.advanceTransport()
        self.assertIs(second, transport.getPieceForDistributionDrop())

    def test_clear_only_removes_the_named_piece(self) -> None:
        transport = ClassificationChannelTransport()
        piece, other = KnownObject(), KnownObject()
        transport.placePieceForDistribution(piece)

        self.assertFalse(transport.clearPieceForDistribution(other))
        self.assertIs(piece, transport.getPieceForDistributionPositioning())
        self.assertTrue(transport.clearPieceForDistribution(piece))
        self.assertIsNone(transport.getPieceForDistributionPositioning())
        self.assertFalse(transport.clearPieceForDistribution())


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
