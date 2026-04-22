from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .classification import ClassifierResult


@dataclass(frozen=True, slots=True)
class BinDecision:
    """Bin routing verdict for one classified piece."""

    bin_id: str | None
    category: str | None
    reason: str


class RulesEngine(Protocol):
    """Domain-specific routing strategy: ClassifierResult + context → BinDecision."""

    key: str

    def decide_bin(
        self,
        classification: ClassifierResult,
        context: dict[str, Any],
    ) -> BinDecision: ...

    def reload(self) -> None: ...
