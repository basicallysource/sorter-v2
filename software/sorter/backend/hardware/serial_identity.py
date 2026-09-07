"""Stable serial-port identity helpers.

Linux numbers /dev/ttyACM* by enumeration order, so the same USB adapter can
land on a different node after a replug or reboot (the "port lottery"). udev
also publishes /dev/serial/by-id/* symlinks that encode the USB device
identity and therefore survive re-numbering. These helpers translate between
the two forms; they deliberately avoid any pyserial dependency.
"""

from __future__ import annotations

import os
from pathlib import Path

_BY_ID_DIR = Path("/dev/serial/by-id")


def canonical_port_path(path: str) -> str:
    """Resolve symlinks so by-id paths and their /dev/tty* targets compare equal."""
    return os.path.realpath(path)


def stable_port_path(device: str) -> str:
    """Return the /dev/serial/by-id symlink for ``device`` when one exists.

    Falls back to ``device`` unchanged when no symlink resolves to the same
    node (non-Linux, no udev entry, or the by-id directory is absent).
    """
    target = canonical_port_path(device)
    try:
        links = sorted(_BY_ID_DIR.iterdir())
    except OSError:
        return device
    for link in links:
        if os.path.realpath(link) == target:
            return str(link)
    return device
