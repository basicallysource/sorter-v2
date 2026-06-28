"""mergeNearbyBboxes: collapse the detector's over-segmentation of one piece."""

from perception.arcs import mergeNearbyBboxes


def test_overlapping_boxes_merge_to_union():
    clusters = mergeNearbyBboxes([(10, 10, 30, 30), (20, 20, 40, 40)], gap_px=0)
    assert len(clusters) == 1
    merged, members = clusters[0]
    assert merged == (10, 10, 40, 40)
    assert len(members) == 2


def test_far_apart_boxes_stay_separate():
    clusters = mergeNearbyBboxes([(0, 0, 10, 10), (100, 100, 110, 110)], gap_px=5)
    assert len(clusters) == 2


def test_adjacent_within_gap_merges():
    # 4px gap between them, tolerance 6 -> one piece.
    clusters = mergeNearbyBboxes([(0, 0, 10, 10), (14, 0, 24, 10)], gap_px=6)
    assert len(clusters) == 1
    assert clusters[0][0] == (0, 0, 24, 10)


def test_adjacent_beyond_gap_stays_split():
    # 10px gap, tolerance 5 -> two pieces.
    clusters = mergeNearbyBboxes([(0, 0, 10, 10), (20, 0, 30, 10)], gap_px=5)
    assert len(clusters) == 2


def test_transitive_chain_merges_all():
    # A~B and B~C but A not directly near C — union-find still fuses all three
    # (a multi-coloured brick drawn as a row of boxes).
    clusters = mergeNearbyBboxes(
        [(0, 0, 10, 10), (12, 0, 22, 10), (24, 0, 34, 10)], gap_px=4
    )
    assert len(clusters) == 1
    merged, members = clusters[0]
    assert merged == (0, 0, 34, 10)
    assert len(members) == 3


def test_single_box_passes_through():
    assert mergeNearbyBboxes([(5, 5, 15, 15)], gap_px=10) == [
        ((5, 5, 15, 15), [(5, 5, 15, 15)])
    ]


def test_empty():
    assert mergeNearbyBboxes([], gap_px=10) == []


def test_two_separated_pieces_not_merged_realistic():
    # A real two-drop: two pieces ~150px apart on the channel must NOT fuse, so
    # genuine multi-drops are still detected (one piece per box).
    clusters = mergeNearbyBboxes([(100, 800, 380, 1180), (2100, 1950, 2400, 2120)], gap_px=14)
    assert len(clusters) == 2
