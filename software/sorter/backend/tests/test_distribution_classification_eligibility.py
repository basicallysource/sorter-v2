"""Only accepted recognition results can select a category bin."""
import queue
from types import SimpleNamespace

import pytest

from defs.known_object import ClassificationStatus, KnownObject
from sorting_profile import MISC_CATEGORY
from subsystems.distribution.positioning import Positioning
from subsystems.shared_variables import SharedVariables
from tests.test_sample_collection_mode_doors import _GlobalConfig, _Transport


@pytest.mark.parametrize("status", list(ClassificationStatus))
def test_bin_selection_requires_classified_status_even_with_old_part_and_value(status):
    piece = KnownObject(part_id="3001", color_id="1", confidence=0.9,
                        classification_status=status, moving_avg_price=100.0)
    shared = SharedVariables()
    shared.transport = _Transport(piece)
    profile = SimpleNamespace(
        getCategoryIdForPart=lambda *args: "bricks",
        highValueCategoryId=lambda price: "valuable",
    )
    state = Positioning(SimpleNamespace(servos=[]), _GlobalConfig(), shared,
                        SimpleNamespace(), SimpleNamespace(layers=[]), profile, queue.Queue())
    categories = []

    class Selected(Exception):
        pass

    def select(category, **kwargs):
        categories.append(category)
        raise Selected

    state._findOrAssignBinForCategory = select
    with pytest.raises(Selected):
        state.step()
    assert categories == ["valuable" if status == ClassificationStatus.classified else MISC_CATEGORY]
