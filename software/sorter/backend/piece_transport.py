from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import time
from typing import Optional

from defs.known_object import ClassificationStatus, KnownObject


@dataclass(frozen=True)
class TransportAdvanceResult:
    exiting_piece: KnownObject | None
    piece_at_classification: KnownObject | None
    piece_for_distribution_drop: KnownObject | None


class PieceTransport(ABC):
    @abstractmethod
    def registerIncomingPiece(self) -> KnownObject:
        """Create and stage a new piece at this setup's classification input."""

    @abstractmethod
    def advanceTransport(self) -> TransportAdvanceResult:
        """Advance the hardware transport after its stepper movement completed."""

    @abstractmethod
    def getPieceAtClassification(self) -> KnownObject | None:
        """Return the piece currently occupying the classification station."""

    @abstractmethod
    def getPieceForDistributionPositioning(self) -> KnownObject | None:
        """Return the piece whose target bin should be prepared next."""

    @abstractmethod
    def getPieceForDistributionDrop(self) -> KnownObject | None:
        """Return the piece that has already dropped into the distribution chute."""

    @abstractmethod
    def markPendingClassification(self, obj: KnownObject) -> None:
        """Mark a piece as waiting for asynchronous classification completion."""

    @abstractmethod
    def resolveClassification(
        self,
        uuid: str,
        part_id: Optional[str],
        color_id: str,
        color_name: str,
        confidence: Optional[float] = None,
    ) -> bool:
        """Write an asynchronous classification result back onto a tracked piece."""

    def getActivePieceCount(self) -> int:
        """Return the number of pieces still staged in this transport."""
        return 0


class ClassificationChannelTransport(PieceTransport):
    """Two-stage transport for the dedicated classification C-channel.

    A single classification-channel pulse advances every staged piece by one
    logical slot:

    - classification hood -> wait zone
    - wait zone -> distribution drop

    This lets the machine free the hood for the next part while a previously
    classified part is already parked near the exit.
    """

    def __init__(self) -> None:
        self._classification_piece: KnownObject | None = None
        self._wait_piece: KnownObject | None = None
        self._exit_piece: KnownObject | None = None
        self._pending_classifications: dict[str, KnownObject] = {}

    def registerIncomingPiece(self) -> KnownObject:
        obj = KnownObject()
        self._classification_piece = obj
        return obj

    def advanceTransport(self) -> TransportAdvanceResult:
        exiting = self._exit_piece
        self._exit_piece = self._wait_piece
        self._wait_piece = self._classification_piece
        self._classification_piece = None
        return TransportAdvanceResult(
            exiting_piece=exiting,
            piece_at_classification=None,
            piece_for_distribution_drop=self._exit_piece,
        )

    def getPieceAtClassification(self) -> KnownObject | None:
        return self._classification_piece

    def getPieceAtWaitZone(self) -> KnownObject | None:
        return self._wait_piece

    def getPieceForDistributionPositioning(self) -> KnownObject | None:
        return self._wait_piece

    def getPieceForDistributionDrop(self) -> KnownObject | None:
        return self._exit_piece

    def getActivePieceCount(self) -> int:
        return sum(
            1
            for piece in (
                self._classification_piece,
                self._wait_piece,
                self._exit_piece,
            )
            if piece is not None
        )

    def markPendingClassification(self, obj: KnownObject) -> None:
        self._pending_classifications[obj.uuid] = obj

    def resolveClassification(
        self,
        uuid: str,
        part_id: Optional[str],
        color_id: str,
        color_name: str,
        confidence: Optional[float] = None,
    ) -> bool:
        obj = self._pending_classifications.pop(uuid, None)
        if obj is None:
            return False

        obj.part_id = part_id
        obj.color_id = color_id
        obj.color_name = color_name
        obj.confidence = confidence
        obj.classification_status = (
            ClassificationStatus.classified if part_id else ClassificationStatus.unknown
        )
        obj.classified_at = time.time()
        obj.updated_at = time.time()
        return True
