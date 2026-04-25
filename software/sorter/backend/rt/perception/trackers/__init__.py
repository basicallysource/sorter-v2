"""Production tracker implementations.

Importing this package registers only the BoxMot production path. Legacy
trackers remain importable from their modules for tests and replay benchmarks,
but they no longer self-register into the runtime by default.
"""

from . import boxmot_bytetrack  # noqa: F401
from . import boxmot_reid  # noqa: F401


__all__ = ["boxmot_bytetrack", "boxmot_reid"]
