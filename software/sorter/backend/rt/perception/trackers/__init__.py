"""Tracker implementations. Import triggers registry self-registration."""

from . import boxmot_reid  # noqa: F401
from . import polar  # noqa: F401
from . import roboflow  # noqa: F401
from . import turntable_groundplane  # noqa: F401


__all__ = ["boxmot_reid", "polar", "roboflow", "turntable_groundplane"]
