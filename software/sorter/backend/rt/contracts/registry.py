from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING, Any, Callable, Generic, TypeVar

if TYPE_CHECKING:
    from .admission import AdmissionStrategy
    from .calibration import CalibrationStrategy
    from .classification import Classifier
    from .detection import Detector
    from .ejection import EjectionTimingStrategy
    from .filters import Filter
    from .rules import RulesEngine
    from .tracking import Tracker


T = TypeVar("T")


class StrategyRegistry(Generic[T]):
    """Name-keyed registry of factory callables for a strategy kind."""

    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._entries: dict[str, Callable[..., T]] = {}
        self._lock = Lock()

    def register(self, key: str, factory: Callable[..., T]) -> None:
        with self._lock:
            if key in self._entries:
                raise ValueError(
                    f"{self._kind} strategy {key!r} already registered"
                )
            self._entries[key] = factory

    def create(self, key: str, **kwargs: Any) -> T:
        try:
            factory = self._entries[key]
        except KeyError:
            raise LookupError(f"Unknown {self._kind} strategy: {key!r}") from None
        return factory(**kwargs)

    def keys(self) -> frozenset[str]:
        return frozenset(self._entries)

    def kind(self) -> str:
        return self._kind


DETECTORS: "StrategyRegistry[Detector]" = StrategyRegistry("detector")
TRACKERS: "StrategyRegistry[Tracker]" = StrategyRegistry("tracker")
FILTERS: "StrategyRegistry[Filter]" = StrategyRegistry("filter")
CLASSIFIERS: "StrategyRegistry[Classifier]" = StrategyRegistry("classifier")
CALIBRATIONS: "StrategyRegistry[CalibrationStrategy]" = StrategyRegistry("calibration")
ADMISSION_STRATEGIES: "StrategyRegistry[AdmissionStrategy]" = StrategyRegistry("admission")
EJECTION_TIMING_STRATEGIES: "StrategyRegistry[EjectionTimingStrategy]" = StrategyRegistry(
    "ejection_timing"
)
RULES_ENGINES: "StrategyRegistry[RulesEngine]" = StrategyRegistry("rules_engine")


def _make_decorator(registry: StrategyRegistry[Any]) -> Callable[[str], Callable[[Any], Any]]:
    def decorator(key: str) -> Callable[[Any], Any]:
        def wrap(cls: Any) -> Any:
            registry.register(key, cls)
            return cls

        return wrap

    return decorator


register_detector = _make_decorator(DETECTORS)
register_tracker = _make_decorator(TRACKERS)
register_filter = _make_decorator(FILTERS)
register_classifier = _make_decorator(CLASSIFIERS)
register_calibration = _make_decorator(CALIBRATIONS)
register_admission = _make_decorator(ADMISSION_STRATEGIES)
register_ejection_timing = _make_decorator(EJECTION_TIMING_STRATEGIES)
register_rules_engine = _make_decorator(RULES_ENGINES)


__all__ = [
    "StrategyRegistry",
    "DETECTORS",
    "TRACKERS",
    "FILTERS",
    "CLASSIFIERS",
    "CALIBRATIONS",
    "ADMISSION_STRATEGIES",
    "EJECTION_TIMING_STRATEGIES",
    "RULES_ENGINES",
    "register_detector",
    "register_tracker",
    "register_filter",
    "register_classifier",
    "register_calibration",
    "register_admission",
    "register_ejection_timing",
    "register_rules_engine",
]
