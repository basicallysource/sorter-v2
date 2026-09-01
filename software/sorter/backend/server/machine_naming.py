"""Machine naming vocabulary shared by the Tailscale hostname and the Hive link.

One scheme, two renderings: `sorter-dark-azure-brick-0ffbef` as a hostname,
"Dark Azure Brick" as the name a person reads in Hive. A machine that already
carries a generated hostname reuses those words for Hive, so the same sorter
looks like itself everywhere.

Keep the word lists in sync with sorteros-firstboot.py's copy so machines named
at firstboot and machines named from the UI draw from the same vocabulary.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

# SystemRandom so the picks stay OS-seeded no matter what else in the process
# has touched the shared random module.
_rng = random.SystemRandom()

LEGO_COLORS = [
    "aqua", "azure", "black", "blue", "bright-green", "bright-pink",
    "brown", "coral", "dark-azure", "dark-blue", "dark-brown", "dark-gray",
    "dark-green", "dark-orange", "dark-pink", "dark-purple", "dark-red",
    "dark-tan", "dark-turquoise", "gray", "green", "lavender", "light-aqua",
    "light-blue", "light-gray", "light-pink", "light-purple", "light-yellow",
    "lime", "magenta", "medium-azure", "medium-blue", "medium-green",
    "medium-lavender", "medium-nougat", "nougat", "olive", "orange", "pink",
    "purple", "red", "reddish-brown", "sand-blue", "sand-green", "tan",
    "teal", "warm-gold", "white", "yellow",
]

LEGO_PIECES = [
    "antenna", "arch", "axle", "baseplate", "beam", "bracket", "brick",
    "bushing", "clip", "cone", "cylinder", "dish", "dome", "door", "fence",
    "flag", "gear", "grille", "hinge", "hose", "jumper", "ladder", "lever",
    "minifig", "panel", "pin", "plate", "propeller", "rail", "ramp", "rod",
    "roof", "slope", "sprocket", "stud", "technic", "tile", "tube",
    "turntable", "wedge", "wheel", "windscreen", "wing",
]

_HOSTNAME_PREFIX = "sorter-"
_MAC_SUFFIX_RE = re.compile(r"^[0-9a-f]{6}$")


def mac_suffix() -> str:
    """Last six hex digits of the first real NIC — stable across regenerations."""
    net = Path("/sys/class/net")
    if net.exists():
        for iface in sorted(net.iterdir()):
            if iface.name == "lo":
                continue
            addr_file = iface / "address"
            if addr_file.exists():
                mac = addr_file.read_text().strip().replace(":", "")
                if mac and mac != "000000000000":
                    return mac[-6:].lower()
    return format(_rng.randint(0, 0xFFFFFF), "06x")


def generate_hostname() -> str:
    """A fresh Tailscale device name, e.g. `sorter-dark-azure-brick-0ffbef`."""
    return f"{_HOSTNAME_PREFIX}{_rng.choice(LEGO_COLORS)}-{_rng.choice(LEGO_PIECES)}-{mac_suffix()}"


def random_display_name() -> str:
    """A fresh human-facing name, e.g. "Dark Azure Brick"."""
    return _titleize(f"{_rng.choice(LEGO_COLORS)}-{_rng.choice(LEGO_PIECES)}")


def display_name_from_hostname(hostname: str | None) -> str | None:
    """Read a generated hostname back as a display name, or None if it is not one.

    Only a hostname this scheme actually produced counts: the words have to be a
    real colour followed by a real piece. A machine that never ran firstboot,
    or whose device name is whatever the OS image shipped with ("orangepi",
    "ubuntu", a hand-typed "sorter-01"), has nothing worth reusing, and a
    freshly rolled name beats a scrap of someone's infrastructure.

    The MAC suffix is dropped: it disambiguates devices on a tailnet, but it
    only makes noise in a machine list someone actually reads.
    """
    raw = (hostname or "").strip().lower()
    if not raw.startswith(_HOSTNAME_PREFIX):
        return None

    words = [word for word in raw[len(_HOSTNAME_PREFIX):].split("-") if word]
    if len(words) > 1 and _MAC_SUFFIX_RE.match(words[-1]):
        words = words[:-1]
    if len(words) < 2 or words[-1] not in LEGO_PIECES:
        return None
    if "-".join(words[:-1]) not in LEGO_COLORS:
        return None
    return _titleize("-".join(words))


def _titleize(slug: str) -> str:
    return " ".join(word.capitalize() for word in slug.split("-") if word)
