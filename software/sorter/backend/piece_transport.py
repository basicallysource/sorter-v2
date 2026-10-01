from __future__ import annotations

from defs.known_object import KnownObject


class ClassificationChannelTransport:
    """Hands a piece from the classification channel to distribution.

    The classification channel places the piece it has classified in the
    positioning slot, where distribution aims the chute for it. Flinging the
    piece into the chute (``advanceTransport``) moves it to the drop slot, so
    distribution can tell a real drop apart from the positioned piece being
    withdrawn or replaced.
    """

    def __init__(self) -> None:
        self._wait_piece: KnownObject | None = None
        self._exit_piece: KnownObject | None = None

    def advanceTransport(self) -> None:
        self._exit_piece = self._wait_piece
        self._wait_piece = None

    def placePieceForDistribution(self, obj: KnownObject) -> None:
        """Stage the classified piece in the positioning slot so distribution
        aims the chute for it; ``advanceTransport()`` (issued when the piece is
        flung into the chute) promotes it to the drop slot."""
        self._wait_piece = obj

    def clearPieceForDistribution(self, obj: KnownObject | None = None) -> bool:
        """Empty the positioning slot when its piece was abandoned instead of
        flung (forced channel clear, teardown, track lost). With ``obj``, only
        clears when the slot still holds that exact piece. Returns True if the
        slot was cleared."""
        if self._wait_piece is None:
            return False
        if obj is not None and self._wait_piece is not obj:
            return False
        self._wait_piece = None
        return True

    def getPieceForDistributionPositioning(self) -> KnownObject | None:
        return self._wait_piece

    def getPieceForDistributionDrop(self) -> KnownObject | None:
        return self._exit_piece
