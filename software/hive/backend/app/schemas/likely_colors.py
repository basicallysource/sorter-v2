"""The likely-colors response, the same for people (/api/labeling/likely-colors)
and machines (/api/machine/parts/{part}/likely-colors). How the numbers are
made: app/services/color_rank.py."""

from pydantic import BaseModel


class LikelyColor(BaseModel):
    color_id: int
    color_name: str | None = None
    rgb: str | None = None
    is_trans: bool = False
    rank: int
    # closeness x likelihood.
    score: float
    # 0..1: how near the color is to the predictions.
    closeness: float
    # 0..1: how likely the part exists in this color, from its sales.
    likelihood: float
    # Distance (delta E plus the hue and finish terms) and hue difference in
    # degrees to the nearest predicted color; None without one to compare.
    distance: float | None = None
    hue_diff: float | None = None
    # One of the predictions, and the score it was given (None if none was).
    predicted: bool = False
    predicted_score: float | None = None
    # Pieces and lots for sale on BrickLink, and this color's share of the
    # part's pieces for sale; None when there is no sale data for the part.
    qty: int | None = None
    lots: int | None = None
    share: float | None = None
    # Sold, or listed in the catalog, in this color.
    known_in: bool = False


class LikelyColorPrediction(BaseModel):
    color_id: int
    score: float | None = None


class LikelyColorsResponse(BaseModel):
    part_id: str | None = None
    item_no: str | None = None
    # live (priced across the palette now), cache (parts.db, partial) or none.
    source: str
    updated_at: str | None = None
    total_qty: int = 0
    predictions: list[LikelyColorPrediction]
    colors: list[LikelyColor]
