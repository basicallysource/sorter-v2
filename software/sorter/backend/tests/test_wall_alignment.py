"""Wall alignment before the next drop: shorter way, never over the lip,
never back into the drop zone."""
from subsystems.classification_channel.two_piece import wallAlignmentMove


def test_shorter_direction_is_chosen_and_small_offsets_are_left_alone() -> None:
    assert wallAlignmentMove(70.0, 82.0, [], 3.0) == 12.0          # forward 12
    assert wallAlignmentMove(20.0, 82.0, [], 3.0) == -10.0         # 82-20 = 62 -> back 10 (mod 72)
    assert wallAlignmentMove(80.0, 82.0, [], 3.0) is None          # within tolerance
    assert wallAlignmentMove(154.0, 82.0, [], 3.0) is None         # 72 apart = aligned


def test_forward_turn_must_not_push_the_head_towards_the_lip() -> None:
    # head 20° short of the exit-only band: forward 12 would leave 8 (< 15 margin)
    assert wallAlignmentMove(70.0, 82.0, [20.0], 3.0) == -60.0     # the other way round instead
    # ...unless the other way would carry a holding piece back into the drop zone
    assert wallAlignmentMove(70.0, 82.0, [20.0, 150.0], 3.0) is None


def test_backward_turn_must_not_carry_a_holding_piece_into_the_drop_zone() -> None:
    assert wallAlignmentMove(20.0, 82.0, [165.0], 3.0) == 62.0     # back 10 would exceed 170 -> forward 62
    assert wallAlignmentMove(20.0, 82.0, [165.0, 100.0], 3.0) == 62.0
    assert wallAlignmentMove(20.0, 82.0, [165.0, 70.0], 3.0) is None  # forward 62 would leave 8 for the second piece
