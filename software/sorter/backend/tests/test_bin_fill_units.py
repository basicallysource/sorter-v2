import os
import tempfile
import unittest
from unittest.mock import patch

import db
import bin_fill_store
from bin_contents import (
    clear_current_session_bins,
    get_current_bin_contents_snapshot,
    get_current_bin_fill_units,
    get_current_bin_piece_counts,
    record_piece_distribution,
    refresh_bin_state_caches,
    start_new_sorting_session,
)
from irl.bin_layout import getBinLayout, saveBinLayout
from bin_layout_store import set_bin_layout


def _distribute(uuid: str, destination_bin: list[int], part_id: str | None = None) -> None:
    record_piece_distribution(
        {"uuid": uuid, "destination_bin": destination_bin, "distributed_at": 1.0, "part_id": part_id}
    )


class BinFillStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        env = patch.dict(os.environ, {"LOCAL_STATE_DB_PATH": os.path.join(tmpdir.name, "local_state.sqlite")})
        env.start()
        self.addCleanup(env.stop)
        bin_fill_store.cache_invalidate()

    def test_defaults_and_normalization(self) -> None:
        config = bin_fill_store.get_fill_config()
        self.assertEqual(1.0, config["default_units"])
        self.assertEqual({}, config["parts"])
        self.assertEqual(1.0, bin_fill_store.part_volume("3001"))
        self.assertEqual(1.0, bin_fill_store.part_volume(None))

    def test_set_and_part_volume(self) -> None:
        config = bin_fill_store.set_fill_config(default_units=1.5, parts={"3001": 3.0, "": 9.9})
        self.assertEqual(1.5, config["default_units"])
        self.assertEqual({"3001": 3.0}, config["parts"])
        self.assertEqual(3.0, bin_fill_store.part_volume("3001"))
        self.assertEqual(1.5, bin_fill_store.part_volume("3002"))
        self.assertEqual(1.5, bin_fill_store.part_volume(None))

    def test_invalid_values_rejected(self) -> None:
        with self.assertRaises(ValueError):
            bin_fill_store.set_fill_config(default_units=0)
        with self.assertRaises(ValueError):
            bin_fill_store.set_fill_config(parts={"3001": 0})
        # A rejected write must leave the previous config intact.
        bin_fill_store.set_fill_config(parts={"3001": 2.0})
        with self.assertRaises(ValueError):
            bin_fill_store.set_fill_config(parts={"3002": -1})
        self.assertEqual({"3001": 2.0}, bin_fill_store.get_fill_config()["parts"])

    def test_config_survives_cache_invalidation(self) -> None:
        bin_fill_store.set_fill_config(parts={"3062b": 0.4})
        bin_fill_store.cache_invalidate()
        self.assertEqual({"3062b": 0.4}, bin_fill_store.get_fill_config()["parts"])


class BinFillComputationTests(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        env = patch.dict(os.environ, {"LOCAL_STATE_DB_PATH": os.path.join(tmpdir.name, "local_state.sqlite")})
        env.start()
        self.addCleanup(env.stop)
        bin_fill_store.cache_invalidate()

    def test_fill_units_follow_distributions(self) -> None:
        bin_fill_store.set_fill_config(default_units=1.0, parts={"3001": 3.0, "3062b": 0.5})
        start_new_sorting_session(reason="test")
        _distribute("piece-a", [0, 0, 0], part_id="3001")
        _distribute("piece-b", [0, 0, 0], part_id="3062b")
        _distribute("piece-c", [0, 0, 0], part_id="3062b")
        _distribute("piece-d", [0, 0, 0])  # unknown part -> default 1.0
        with patch.object(db, "_open", side_effect=AssertionError("fill reads the database")):
            self.assertAlmostEqual(5.0, get_current_bin_fill_units()[(0, 0, 0)])

        snapshot = get_current_bin_contents_snapshot()
        self.assertAlmostEqual(5.0, snapshot["bins"][0]["fill_units"])
        self.assertEqual(4, snapshot["bins"][0]["piece_count"])

    def test_revalued_volumes_refresh_existing_contents(self) -> None:
        start_new_sorting_session(reason="test")
        _distribute("piece-a", [0, 0, 0], part_id="3001")
        self.assertAlmostEqual(1.0, get_current_bin_fill_units()[(0, 0, 0)])
        bin_fill_store.set_fill_config(parts={"3001": 4.0})
        refresh_bin_state_caches()
        self.assertAlmostEqual(4.0, get_current_bin_fill_units()[(0, 0, 0)])

    def test_clearing_a_bin_resets_its_fill(self) -> None:
        start_new_sorting_session(reason="test")
        _distribute("piece-a", [0, 0, 0], part_id="3001")
        _distribute("piece-b", [1, 0, 2], part_id="3001")
        clear_current_session_bins(scope="bin", layer_index=0, section_index=0, bin_index=0)
        fills = get_current_bin_fill_units()
        self.assertAlmostEqual(0.0, fills.get((0, 0, 0), 0.0))
        self.assertAlmostEqual(1.0, fills.get((1, 0, 2), 0.0))

    def test_fill_survives_session_carry_forward(self) -> None:
        start_new_sorting_session(reason="test")
        _distribute("piece-a", [0, 0, 0], part_id="3001")
        start_new_sorting_session(reason="test")
        self.assertAlmostEqual(1.0, get_current_bin_fill_units()[(0, 0, 0)])


class BinLayoutFillLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        env = patch.dict(os.environ, {"LOCAL_STATE_DB_PATH": os.path.join(tmpdir.name, "local_state.sqlite")})
        env.start()
        self.addCleanup(env.stop)
        bin_fill_store.cache_invalidate()

    def test_max_fill_units_round_trips_through_the_layout(self) -> None:
        set_bin_layout(
            {
                "layers": [
                    {
                        "sections": [["medium", "medium"]],
                        "max_pieces_per_bin": 200,
                        "max_fill_units": 350.5,
                    },
                    {"sections": [["medium", "medium"]]},
                ]
            }
        )
        layout = getBinLayout()
        self.assertEqual(350.5, layout.layers[0].max_fill_units)
        self.assertEqual(200, layout.layers[0].max_pieces_per_bin)
        self.assertIsNone(layout.layers[1].max_fill_units)

    def test_invalid_fill_units_are_ignored(self) -> None:
        set_bin_layout({"layers": [{"sections": [["medium"]], "max_fill_units": -5}]})
        layout = getBinLayout()
        self.assertIsNone(layout.layers[0].max_fill_units)

    def test_save_bin_layout_persists_fill_units(self) -> None:
        from irl.bin_layout import BinLayoutConfig, LayerConfig

        config = BinLayoutConfig(
            layers=[LayerConfig(sections=[["medium"]], max_fill_units=120.0)]
        )
        saveBinLayout(config)
        layout = getBinLayout()
        self.assertEqual(120.0, layout.layers[0].max_fill_units)


if __name__ == "__main__":
    unittest.main()
