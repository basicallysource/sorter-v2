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
# Hex color per codename — picked to evoke the actual color, not the canonical
# LEGO ABS shade (those are too saturated for UI dots). Used to render a small
# colored dot next to the codename in the UI. Derived (no DB column) so we can
# tweak shades centrally without a migration.
CODENAME_COLORS: dict[str, str] = {
    "Aqua": "#5BC2C5", "Amber": "#FFBF00", "Azure": "#3FA9F5", "Apricot": "#FBCEB1",
    "Bronze": "#CD7F32", "Berry": "#A12B5A", "Blush": "#DE5D83", "Blossom": "#F5C6D4",
    "Cherry": "#DE3163", "Coral": "#FF7F50", "Citrine": "#E4D00A", "Crimson": "#DC143C", "Cobalt": "#0047AB",
    "Dune": "#C2B280", "Denim": "#1560BD", "Dahlia": "#A02050",
    "Ember": "#E25822", "Emerald": "#50C878", "Eggshell": "#F0EAD6",
    "Forest": "#228B22", "Flame": "#E25822", "Flax": "#EEDC82", "Fuchsia": "#FF00FF",
    "Garnet": "#733635", "Ginger": "#B06500", "Goldenrod": "#DAA520",
    "Hazel": "#8E7618", "Honey": "#FFC30B",
    "Indigo": "#4B0082", "Ivory": "#FFFFF0",
    "Jade": "#00A86B", "Juniper": "#3A5F0B",
    "Kelp": "#4A5D23", "Khaki": "#C3B091",
    "Lime": "#BFFF00", "Lavender": "#B57EDC", "Lilac": "#C8A2C8", "Lemon": "#FFF44F",
    "Magenta": "#FF00FF", "Maroon": "#800000", "Moss": "#8A9A5B", "Mauve": "#E0B0FF",
    "Nougat": "#B5876A", "Navy": "#000080", "Nutmeg": "#7E481C",
    "Ochre": "#CC7722", "Olive": "#808000", "Onyx": "#353839", "Opal": "#A8C3BC",
    "Pumpkin": "#FF7518", "Peach": "#FFE5B4", "Pearl": "#EAE0C8", "Plum": "#673147", "Poppy": "#E35B5B",
    "Quartz": "#D9D7E8", "Quince": "#D5C97F",
    "Rose": "#FF66CC", "Ruby": "#E0115F", "Russet": "#80461B", "Rust": "#B7410E",
    "Saffron": "#F4C430", "Slate": "#708090", "Sand": "#C2B280", "Sage": "#9CAF88", "Scarlet": "#FF2400",
    "Tangerine": "#F28500", "Teal": "#008080", "Topaz": "#FFC87C", "Tan": "#D2B48C",
    "Umber": "#635147", "Ultramarine": "#3F00FF",
    "Violet": "#7F00FF", "Verdant": "#1E5631", "Vermilion": "#E34234",
    "Wisteria": "#A18BCB", "Wheat": "#F5DEB3", "Walnut": "#5C4033",
    "Zinc": "#7F7F7F", "Zephyr": "#CFD8DC",
}


def color_for(codename: str | None) -> str | None:
    """Hex color for a codename, or None if unknown / unassigned."""
    if not codename:
        return None
    return CODENAME_COLORS.get(codename)


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
