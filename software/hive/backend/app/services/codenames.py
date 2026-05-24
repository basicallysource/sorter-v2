"""Curated LEGO-color codename pool + auto-assignment helper.

Ubuntu-style human-friendly identifier for detection models. The pool is drawn
from LEGO's published color palette (Bricklink + LEGO's own naming over the
years) — generic color descriptors, not trademarked individually, so we're
clean on the IP side while keeping the LEGO-world association.

Alphabetical assignment ("Aqua" → "Bronze" → "Cherry" → ...) gives an implicit
release order at a glance: later letters = newer model. Within the same letter
we pick the first available alternative.
"""

from __future__ import annotations

from sqlalchemy.orm import Session


# Curated alphabetically. Drop a name if it ever feels off; this list is only
# consulted when a new codename is needed, so removing entries doesn't break
# already-assigned ones.
CODENAME_POOL: tuple[str, ...] = (
    # A
    "Aqua", "Amber", "Azure", "Apricot",
    # B
    "Bronze", "Berry", "Blush", "Blossom",
    # C
    "Cherry", "Coral", "Citrine", "Crimson", "Cobalt",
    # D
    "Dune", "Denim", "Dahlia",
    # E
    "Ember", "Emerald", "Eggshell",
    # F
    "Forest", "Flame", "Flax", "Fuchsia",
    # G
    "Garnet", "Ginger", "Goldenrod",
    # H
    "Hazel", "Honey",
    # I
    "Indigo", "Ivory",
    # J
    "Jade", "Juniper",
    # K
    "Kelp", "Khaki",
    # L
    "Lime", "Lavender", "Lilac", "Lemon",
    # M
    "Magenta", "Maroon", "Moss", "Mauve",
    # N
    "Nougat", "Navy", "Nutmeg",
    # O
    "Ochre", "Olive", "Onyx", "Opal",
    # P
    "Pumpkin", "Peach", "Pearl", "Plum", "Poppy",
    # Q
    "Quartz", "Quince",
    # R
    "Rose", "Ruby", "Russet", "Rust",
    # S
    "Saffron", "Slate", "Sand", "Sage", "Scarlet",
    # T
    "Tangerine", "Teal", "Topaz", "Tan",
    # U
    "Umber", "Ultramarine",
    # V
    "Violet", "Verdant", "Vermilion",
    # W
    "Wisteria", "Wheat", "Walnut",
    # X / Y / Z — scarce, listed but rarely picked
    "Zinc", "Zephyr",
)


def next_codename(db: Session) -> str:
    """Pick the next unused codename in pool order.

    Falls through to a numeric suffix if every name has been used (years away).
    Lookup is one indexed query against detection_models.codename — cheap.
    """
    from app.models.detection_model import DetectionModel

    used: set[str] = {
        row[0]
        for row in db.query(DetectionModel.codename)
        .filter(DetectionModel.codename.isnot(None))
        .all()
    }
    for name in CODENAME_POOL:
        if name not in used:
            return name

    # Pool exhausted — append a numeric suffix until we find a free slot. Should
    # take many years of training cadence before we trip this branch.
    suffix = 2
    while True:
        for name in CODENAME_POOL:
            candidate = f"{name}{suffix}"
            if candidate not in used:
                return candidate
        suffix += 1
