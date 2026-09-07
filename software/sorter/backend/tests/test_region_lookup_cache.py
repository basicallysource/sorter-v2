"""The zone → region table must follow a live zone edit.

Regression: the table was cached per channel id and never dropped, so after
the operator redrew the C4 zones (camera remount) a piece resting in the new
DROP arc was still coded by the old layout, was never captured, and went to
misc as a "stray head".
"""
from types import SimpleNamespace

from perception.arcs import _region_lookup


def _channel(drop, exit_, precise):
    return SimpleNamespace(
        channel_id=4,
        drop_sections=frozenset(drop),
        exit_sections=frozenset(exit_) | frozenset(precise),
        precise_sections=frozenset(precise),
    )


def test_same_channel_id_with_new_zones_gets_a_new_table() -> None:
    before = _region_lookup(_channel(drop=range(0, 10), exit_=range(20, 30), precise=range(25, 30)))
    after = _region_lookup(_channel(drop=range(40, 50), exit_=range(60, 70), precise=range(65, 70)))
    assert before[5] == 1 and after[5] == 0
    assert after[45] == 1
    assert after[62] == 2 and after[67] == 3


def test_identical_zones_reuse_the_cached_table() -> None:
    a = _region_lookup(_channel(drop=range(0, 5), exit_=range(10, 20), precise=range(15, 20)))
    b = _region_lookup(_channel(drop=range(0, 5), exit_=range(10, 20), precise=range(15, 20)))
    assert a is b
