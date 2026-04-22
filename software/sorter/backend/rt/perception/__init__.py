"""Perception layer: feeds, zones, detectors, trackers, filters, pipeline.

Importing this package eagerly imports the detector/tracker/filter
subpackages so their @register_* decorators run before callers touch the
strategy registries. Classifiers live under the perception tree as well
because the runtime bootstrap expects a single eager import to register
every detector/tracker/filter/classifier strategy it needs.
"""

from . import classifiers  # noqa: F401
from . import detectors  # noqa: F401
from . import filters  # noqa: F401
from . import trackers  # noqa: F401


__all__ = ["classifiers", "detectors", "filters", "trackers"]
