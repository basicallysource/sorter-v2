"""Rules engines: map classifier results to bin decisions.

Registering side-effect only — importing this package makes ``lego_default``
available via ``RULES_ENGINES.create("lego_default", ...)``.
"""

from __future__ import annotations

from . import lego_rules  # noqa: F401 — register side-effect

__all__: list[str] = []
