"""Perception layer: feeds, zones, detectors, trackers, filters, pipeline.

Importing this package eagerly imports the detector/tracker/filter
subpackages so their @register_* decorators run before callers touch the
strategy registries.
"""

from . import detectors  # noqa: F401
from . import filters  # noqa: F401
from . import trackers  # noqa: F401


__all__ = ["detectors", "filters", "trackers"]
