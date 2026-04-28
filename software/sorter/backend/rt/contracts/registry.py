from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING, Any, Callable, Generic, Mapping, TypeVar

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
    """Name-keyed registry of factory callables for a strategy kind.

    Each entry may optionally carry a metadata mapping alongside the factory
    (used by detectors to record declared ``scopes`` from ``run.json`` so
    UI helpers can filter/default without instantiating the detector).
    """

    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._entries: dict[str, Callable[..., T]] = {}
        self._metadata: dict[str, Mapping[str, Any]] = {}
        self._lock = Lock()

    def register(
        self,
        key: str,
        factory: Callable[..., T],
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        with self._lock:
            if key in self._entries:
                raise ValueError(
                    f"{self._kind} strategy {key!r} already registered"
                )
            self._entries[key] = factory
            if metadata is not None:
                self._metadata[key] = dict(metadata)

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

    def metadata(self, key: str) -> Mapping[str, Any]:
        """Return the metadata dict recorded at register time (empty if none)."""
        return self._metadata.get(key, {})

    def set_metadata(self, key: str, metadata: Mapping[str, Any]) -> None:
        """Attach or overwrite metadata for an already-registered key."""
        with self._lock:
            if key not in self._entries:
                raise LookupError(f"Unknown {self._kind} strategy: {key!r}")
            self._metadata[key] = dict(metadata)


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


# ---------------------------------------------------------------------------
# Detector ↔ UI-scope mapping
# ---------------------------------------------------------------------------
#
# Single source of truth for the model-scope (from ``run.json``) to
# UI-scope (settings dropdowns) relation. Consumers must never duplicate
# this mapping — always go through ``ui_scopes_for_detector`` /
# ``default_detector_slug_for_ui_scope``.
#
# Hardware rationale (Marc):
#   - The Feeder is physically a C-Channel carousel and shares optics with
#     the classification C-Channel (C3), so both UI scopes ("feeder",
#     "classification_channel") surface the same detector family.
#   - "Carousel" is a separate hardware type (the real carousel).
#   - "Classification Chamber" is the C4 top/bottom chamber.
#   - Models whose ``scopes`` are missing / ``None`` / empty are legacy
#     leftovers and must not be offered anywhere.
_MODEL_SCOPE_TO_UI_SCOPES: dict[str, frozenset[str]] = {
    "c_channel": frozenset({"feeder", "classification_channel"}),
    "carousel": frozenset({"carousel"}),
    "classification_chamber": frozenset({"classification"}),
}

# Per UI-scope defaults. ``None`` means "pick the best-available (lowest
# alphabetical slug)" rather than hardcoding a specific detector.
_UI_SCOPE_DEFAULT_SLUG: dict[str, str | None] = {
    "feeder": "hive:c-channel-yolo11n-416",
    "classification_channel": "hive:c-channel-yolo11n-416",
    "carousel": None,
    "classification": None,
}


def _detector_model_scopes(slug: str) -> frozenset[str]:
    meta = DETECTORS.metadata(slug)
    raw = meta.get("scopes") if isinstance(meta, Mapping) else None
    if not raw:
        return frozenset()
    return frozenset(str(s).lower() for s in raw if isinstance(s, str) and s)


def ui_scopes_for_detector(slug: str) -> frozenset[str]:
    """Which UI dropdowns should show this detector. Empty set → hidden.

    Derived from the detector's declared ``scopes`` (attached as metadata
    at registration time — sourced from ``run.json``). A detector with no
    declared scope (legacy leftover) resolves to an empty set.
    """
    if slug not in DETECTORS.keys():
        return frozenset()
    ui: set[str] = set()
    for model_scope in _detector_model_scopes(slug):
        ui.update(_MODEL_SCOPE_TO_UI_SCOPES.get(model_scope, frozenset()))
    return frozenset(ui)


def default_detector_slug_for_ui_scope(ui_scope: str) -> str | None:
    """Default detector slug for a UI scope.

    Returns the pre-declared default when its detector is registered with
    a matching scope; otherwise falls back to the first detector whose
    ``ui_scopes_for_detector`` includes ``ui_scope``. ``None`` when no
    detector currently covers the scope.
    """
    if not ui_scope:
        return None
    preferred = _UI_SCOPE_DEFAULT_SLUG.get(ui_scope)
    if preferred and preferred in DETECTORS.keys():
        if ui_scope in ui_scopes_for_detector(preferred):
            return preferred
    # Fallback: first registered detector (sorted) whose scopes cover the UI scope.
    for slug in sorted(DETECTORS.keys()):
        if ui_scope in ui_scopes_for_detector(slug):
            return slug
    return None


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
    "ui_scopes_for_detector",
    "default_detector_slug_for_ui_scope",
]
