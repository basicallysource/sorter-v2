"""Default admission / ejection-timing strategies for Phase 3+4 runtimes.

Importing this package triggers registration side-effects. Available keys:
  * admission: ``"always"``, ``"c4"``
  * ejection_timing: ``"constant"``, ``"c4"``
"""

from __future__ import annotations

from .admission_always import AlwaysAdmit
from .admission_c4 import C4Admission
from .ejection_c4 import C4EjectionTiming
from .ejection_constant import ConstantPulseEjection
from .purge_c4 import C4StartupPurgeStrategy
from .purge_generic import GenericPurgeStrategy, PurgeTickResult


__all__ = [
    "AlwaysAdmit",
    "C4Admission",
    "C4EjectionTiming",
    "ConstantPulseEjection",
    "C4StartupPurgeStrategy",
    "GenericPurgeStrategy",
    "PurgeTickResult",
]
