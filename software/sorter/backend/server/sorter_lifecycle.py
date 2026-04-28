"""Sorter lifecycle port — single object holding hardware/runtime callbacks.

Replaces the four module-level ``_hardware_*_fn`` globals and their
setter functions in ``shared_state.py``. ``main.py`` builds the port
after homing/reset closures are defined; the ``/api/system/*`` router
reads the callables off the port. The field names carry the intent the
old global names only hinted at (``home_hardware`` instead of
``_hardware_start_fn``), so router code no longer has to parse
underscore conventions to decide which callable does what.

All fields are optional — the router handles a missing callable by
returning a 4xx-style payload rather than crashing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(slots=True, kw_only=True)
class SorterLifecyclePort:
    """Named slots for the four callbacks ``/api/system/*`` drives."""

    home_hardware: Callable[[], None] | None = None
    initialize_hardware: Callable[[], None] | None = None
    reset_hardware: Callable[[], None] | None = None
    prepare_rt_handle: Callable[[], None] | None = None


__all__ = ["SorterLifecyclePort"]
