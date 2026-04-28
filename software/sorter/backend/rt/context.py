from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from rt.config.schema import SorterConfig
from rt.contracts.events import EventBus


@dataclass(slots=True)
class RuntimeContext:
    """Explicit DI container — replaces the 27 globals in `shared_state.py`.

    Service refs beyond the four core fields (camera_service, hardware,
    run_recorder, ...) will land as later phases introduce them; the context
    is intentionally mutable during bootstrap so the orchestrator can wire
    services in stages before freezing.
    """

    config: SorterConfig
    logger: logging.Logger
    event_bus: EventBus
    camera_service: Any | None = None
    hardware: Any | None = None
    run_recorder: Any | None = None


__all__ = ["RuntimeContext"]
