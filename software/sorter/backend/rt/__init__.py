from __future__ import annotations

from rt.config.schema import SorterConfig
from rt.context import RuntimeContext
from rt.contracts import registry


def build_runtime(config: SorterConfig) -> RuntimeContext:
    """Assemble and return the RuntimeContext for the running sorter.

    Phase 1 scaffold stub — full orchestrator wiring (PerceptionRunners,
    Runtimes, CapacitySlots, hardware workers) lands in Phase 2+.
    """
    raise NotImplementedError("runtime not built yet; scaffold only")


__all__ = ["RuntimeContext", "SorterConfig", "build_runtime", "registry"]
