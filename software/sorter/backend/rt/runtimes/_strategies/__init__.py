"""Default admission / ejection-timing strategies for Phase 3 runtimes.

Importing this package triggers registration side-effects: ``AlwaysAdmit``
and ``ConstantPulseEjection`` become available via the strategy registries
under keys ``"always"`` and ``"constant"`` respectively.
"""

from __future__ import annotations

from .admission_always import AlwaysAdmit
from .ejection_constant import ConstantPulseEjection


__all__ = ["AlwaysAdmit", "ConstantPulseEjection"]
