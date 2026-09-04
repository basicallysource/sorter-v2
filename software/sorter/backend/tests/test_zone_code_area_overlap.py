"""A piece straddling the drop arc's rear edge is a DROP piece.

Regression (C4, 2026-09-04): the two-piece handler codes zones from
``orderedPieceObservations``; a piece resting across the drop arc's rear edge
had its bbox centre one section outside, so the handler saw a forward
"stray" while the area-based ``in_drop`` gate stayed closed — a deadlock that
ended in the stall watchdog and a good piece sent to misc.
"""
import numpy as np

from perception.arcs import SECTION_COUNT, SECTION_DEG, orderedPieceObservations
from perception.channel import ChannelDef


def _channel() -> ChannelDef:
    mask = np.zeros((400, 400), dtype=np.uint8)
    mask[:, :] = 255
    drop = frozenset(range(20, 40))
    precise = frozenset(range(2, 6))
    exit_ = frozenset(range(6, 12)) | precise
    return ChannelDef(
        channel_id=4,
        camera_source_id="carousel",
        center=(200.0, 200.0),
        radius1_angle_image=0.0,
        mask=mask,
        drop_sections=drop,
        exit_sections=exit_,
        precise_sections=precise,
    )


def _bbox_centred_at_angle(deg: float, radius: float, half: int) -> tuple[int, int, int, int]:
    cx = 200.0 + radius * np.cos(np.radians(deg))
    cy = 200.0 + radius * np.sin(np.radians(deg))
    return (int(cx - half), int(cy - half), int(cx + half), int(cy + half))


def test_piece_across_drop_rear_edge_is_coded_drop() -> None:
    ch = _channel()
    rear_edge = 40 * SECTION_DEG  # first section OUTSIDE the drop arc
    bbox = _bbox_centred_at_angle(rear_edge + 0.5 * SECTION_DEG, 120.0, 30)
    obs = orderedPieceObservations([bbox], ch)
    assert len(obs) == 1
    _gap, sec, code, _ = obs[0]
    assert sec not in ch.drop_sections  # centre lies outside the drop arc
    assert code == 1


def test_piece_well_outside_drop_keeps_its_centre_zone() -> None:
    ch = _channel()
    bbox = _bbox_centred_at_angle(8 * SECTION_DEG, 120.0, 4)  # small piece in exit-only
    obs = orderedPieceObservations([bbox], ch)
    assert obs[0][2] == 2
    assert SECTION_COUNT > 40
