"""Rank the LEGO colors a piece is likely to be.

Given the colors a classifier predicted for a piece (each with its score) and,
when known, how often the piece's part is sold in each color, every candidate
color gets two numbers and their product:

* closeness, 0 to 1: how near the color is to what was predicted. Each
  prediction spreads its score over the colors around it, falling off as
  exp(-d / KERNEL_SCALE) with the distance d. The share of belief the scores
  leave out (they sum to less than 1) is spread evenly, as UNEXPLAINED.
  d is the CIELAB distance (delta E 1976), plus HUE_WEIGHT for every degree of
  hue between two colors that both have color in them (a gray has no hue to
  compare), plus FINISH_PENALTY when the finishes differ (solid, trans, pearl
  or metallic, glitter or glow). So a darker or lighter shade of the predicted
  hue comes before a different hue the same distance away.
* likelihood, 0 to 1: how likely the part exists in that color, from the pieces
  for sale: the square root of the color's quantity over the part's most sold
  color's, so popularity informs the order without drowning the color match.
  A color with none for sale keeps a floor: higher when the catalog lists the
  part in it, and higher still when the sale data is partial (an absence there
  says little). Partial data that shows the part for sale in at least
  INFORMATIVE_COLORS colors is read as complete: a part sold in many colors and
  not in this one is not in this one. With no sale data and no catalog list,
  every color is 1 and the order is closeness alone.

score = closeness x likelihood. Every stat is returned, so a screen can show
why a color is where it is.

This file is kept byte-identical in the Hive backend and the sorter backend
(the sorter ranks with it when Hive cannot be reached); a test in each fails
when the two copies differ.
"""

from __future__ import annotations

import math
import re
from typing import Any, Collection, Mapping, Sequence

KERNEL_SCALE = 15.0
UNEXPLAINED = 0.05
HUE_WEIGHT = 0.4
CHROMA_HUE_START = 6.0
CHROMA_HUE_FULL = 30.0
FINISH_PENALTY = 18.0
DEFAULT_SCORE = 0.6
FLOOR_KNOWN = 0.15
FLOOR_UNKNOWN = 0.04
FLOOR_PARTIAL_KNOWN = 0.5
FLOOR_PARTIAL_UNKNOWN = 0.3
INFORMATIVE_COLORS = 8
MAX_PREDICTIONS = 12

_SPECIAL = re.compile(r"glitter|glitr|speckle|glow|milky|opal|iridescent|holo", re.IGNORECASE)
_SHINY = re.compile(r"pearl|metallic|chrome|satin|copper|bronze|\bgold\b|\bsilver\b", re.IGNORECASE)


def hex_to_lab(rgb: Any) -> tuple[float, float, float] | None:
    """A hex color ("FE8A18" or "#FE8A18") in CIELAB (D65), or None."""
    if not isinstance(rgb, str):
        return None
    text = rgb.strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        channels = [int(text[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    except ValueError:
        return None
    r, g, b = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883
    fx, fy, fz = [t ** (1.0 / 3.0) if t > 0.008856 else 7.787 * t + 16.0 / 116.0 for t in (x, y, z)]
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def finish(name: Any, is_trans: Any) -> str:
    """solid, trans, shiny (pearl, metallic, chrome) or special (glitter, glow, milky)."""
    text = str(name or "")
    if is_trans or text.lower().startswith("trans-"):
        return "trans"
    if _SPECIAL.search(text):
        return "special"
    if _SHINY.search(text):
        return "shiny"
    return "solid"


def _hue_weight(chroma_a: float, chroma_b: float) -> float:
    low = min(chroma_a, chroma_b)
    return max(0.0, min(1.0, (low - CHROMA_HUE_START) / (CHROMA_HUE_FULL - CHROMA_HUE_START)))


def color_distance(a: Mapping[str, Any], b: Mapping[str, Any]) -> tuple[float, float | None] | None:
    """(distance, hue difference in degrees or None) between two palette colors,
    or None when either has no usable rgb."""
    lab_a = hex_to_lab(a.get("rgb"))
    lab_b = hex_to_lab(b.get("rgb"))
    if lab_a is None or lab_b is None:
        return None
    distance = math.dist(lab_a, lab_b)
    hue_diff: float | None = None
    weight = _hue_weight(math.hypot(lab_a[1], lab_a[2]), math.hypot(lab_b[1], lab_b[2]))
    if weight > 0:
        hue_a = math.degrees(math.atan2(lab_a[2], lab_a[1]))
        hue_b = math.degrees(math.atan2(lab_b[2], lab_b[1]))
        hue_diff = abs((hue_a - hue_b + 180.0) % 360.0 - 180.0)
        distance += HUE_WEIGHT * hue_diff * weight
    if finish(a.get("name"), a.get("is_trans")) != finish(b.get("name"), b.get("is_trans")):
        distance += FINISH_PENALTY
    return distance, hue_diff


def parse_predictions(text: str | None) -> list[tuple[int, float | None]]:
    """'11:0.82,86:0.1,5' -> [(11, 0.82), (86, 0.1), (5, None)]. Entries that are
    not a color id (with an optional score from 0 to 1) are skipped."""
    out: list[tuple[int, float | None]] = []
    for part in str(text or "").split(","):
        color_text, _, score_text = part.strip().partition(":")
        try:
            color_id = int(color_text)
        except ValueError:
            continue
        score: float | None = None
        if score_text:
            try:
                score = float(score_text)
            except ValueError:
                continue
            if not math.isfinite(score) or score < 0:
                continue
            score = min(score, 1.0)
        out.append((color_id, score))
        if len(out) >= MAX_PREDICTIONS:
            break
    return out


def format_predictions(predictions: Sequence[tuple[Any, float | None]]) -> str:
    """The inverse of parse_predictions, for a query string."""
    parts = []
    for color_id, score in predictions:
        parts.append(str(color_id) if score is None else f"{color_id}:{round(float(score), 4)}")
    return ",".join(parts)


def _merge(predictions: Sequence[tuple[int, float | None]]) -> dict[int, float | None]:
    """One score per color: the highest given, or None when none was given."""
    merged: dict[int, float | None] = {}
    for color_id, score in predictions:
        before = merged.get(color_id)
        if score is None:
            merged.setdefault(color_id, None)
        else:
            merged[color_id] = float(score) if before is None else max(before, float(score))
    return merged


def _weights(merged: Mapping[int, float | None]) -> dict[int, float]:
    weights = {color_id: DEFAULT_SCORE if score is None else score for color_id, score in merged.items()}
    total = sum(weights.values())
    if total > 1.0:
        weights = {color_id: value / total for color_id, value in weights.items()}
    return weights


def rank_colors(
    palette: Sequence[Mapping[str, Any]],
    predictions: Sequence[tuple[int, float | None]],
    *,
    lookup: Mapping[int, Mapping[str, Any]] | None = None,
    quantities: Mapping[int, Mapping[str, Any]] | None = None,
    complete: bool = False,
    known_in: Collection[int] = (),
) -> list[dict[str, Any]]:
    """Every color in `palette` ({id, name, rgb, is_trans}), best first.

    predictions: (color id, score 0..1 or None); a predicted color that is not
        in the palette is found in `lookup` (the whole palette) for its rgb.
    quantities: color id -> {"qty", "lots"} for sale, for the part; None when
        there is no sale data.
    complete: the quantities cover every palette color, so a missing color has
        none for sale (rather than no record).
    known_in: the colors the catalog lists the part in.
    """
    by_id = {int(c["id"]): c for c in palette}
    given = _merge(predictions)
    weights = _weights(given)
    sources = []
    for color_id, weight in weights.items():
        color = by_id.get(color_id) or (lookup or {}).get(color_id)
        if color is not None:
            sources.append((color, weight))
    explained = sum(weight for _, weight in sources)
    leftover = max(0.0, 1.0 - explained) * UNEXPLAINED if sources else 1.0

    sold = {
        int(color_id): int(row.get("qty") or 0)
        for color_id, row in (quantities or {}).items()
        if int(row.get("qty") or 0) > 0
    }
    total_qty = sum(sold.values())
    top_qty = max(sold.values(), default=0)
    known = {int(color_id) for color_id in known_in} | set(sold)
    has_data = bool(sold) or bool(known)
    if complete or len(sold) >= INFORMATIVE_COLORS:
        floor_known, floor_unknown = FLOOR_KNOWN, FLOOR_UNKNOWN
    else:
        floor_known, floor_unknown = FLOOR_PARTIAL_KNOWN, FLOOR_PARTIAL_UNKNOWN

    ranked: list[dict[str, Any]] = []
    for color in palette:
        color_id = int(color["id"])
        closeness = leftover
        nearest: tuple[float, float | None] | None = None
        for source, weight in sources:
            measured = color_distance(color, source)
            if measured is None:
                if int(source["id"]) != color_id:
                    continue
                measured = (0.0, None)
            closeness += weight * math.exp(-measured[0] / KERNEL_SCALE)
            if nearest is None or measured[0] < nearest[0]:
                nearest = measured

        qty = sold.get(color_id, 0)
        is_known = color_id in known
        if not has_data:
            likelihood = 1.0
        else:
            floor = floor_known if is_known else floor_unknown
            base = math.sqrt(qty / top_qty) if top_qty else (1.0 if is_known else 0.0)
            likelihood = floor + (1.0 - floor) * base

        lots = (quantities or {}).get(color_id, {}).get("lots") if quantities else None
        ranked.append(
            {
                "color_id": color_id,
                "color_name": color.get("name"),
                "rgb": color.get("rgb"),
                "is_trans": bool(color.get("is_trans", False)),
                "score": round(closeness * likelihood, 6),
                "closeness": round(closeness, 4),
                "likelihood": round(likelihood, 4),
                "distance": None if nearest is None else round(nearest[0], 2),
                "hue_diff": None if nearest is None or nearest[1] is None else round(nearest[1], 1),
                "predicted": color_id in given,
                "predicted_score": None if given.get(color_id) is None else round(given[color_id], 4),
                "qty": qty if quantities is not None else None,
                "lots": int(lots) if isinstance(lots, (int, float)) else None,
                "share": round(qty / total_qty, 4) if total_qty else None,
                "known_in": is_known,
            }
        )

    ranked.sort(key=lambda c: (-c["score"], c["distance"] if c["distance"] is not None else 1e9, c["color_id"]))
    for index, entry in enumerate(ranked, start=1):
        entry["rank"] = index
    return ranked
