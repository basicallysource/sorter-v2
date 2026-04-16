import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from irl.bin_layout import BinLayoutConfig, LayerConfig
from server.routers import hardware


class BinResetActionTests(unittest.TestCase):
    def test_empty_bin_contents_keeps_category_assignments(self) -> None:
        categories = [[[["set-1"], []]]]
        runtime_stats = SimpleNamespace(clearBinContents=unittest.mock.Mock())
        gc_ref = SimpleNamespace(runtime_stats=runtime_stats)

        with (
            patch("server.routers.hardware._current_bin_categories", return_value=copy.deepcopy(categories)),
            patch("server.routers.hardware._apply_and_persist_bin_categories") as persist_mock,
            patch(
                "server.routers.hardware.clear_current_session_bins",
                return_value={"ok": True, "cleared_bins": 1},
            ) as clear_mock,
            patch.object(hardware.shared_state, "gc_ref", gc_ref),
        ):
            result = hardware.clear_bin_contents(
                scope="bin",
                layer_index=0,
                section_index=0,
                bin_index=0,
            )

        persist_mock.assert_not_called()
        clear_mock.assert_called_once_with(
            scope="bin",
            layer_index=0,
            section_index=0,
            bin_index=0,
        )
        runtime_stats.clearBinContents.assert_called_once_with(
            scope="bin",
            layer_index=0,
            section_index=0,
            bin_index=0,
        )
        self.assertEqual("Emptied bin 1 on layer 1 without changing its assignment.", result["message"])
        self.assertEqual(1, result["cleared_bins"])

    def test_reset_layer_clears_assignments_and_contents(self) -> None:
        categories = [[[["set-1"], ["set-2"]]], [[["set-3"]]]]
        runtime_stats = SimpleNamespace(clearBinContents=unittest.mock.Mock())
        gc_ref = SimpleNamespace(runtime_stats=runtime_stats)

        with (
            patch("server.routers.hardware._current_bin_categories", return_value=copy.deepcopy(categories)),
            patch("server.routers.hardware._apply_and_persist_bin_categories") as persist_mock,
            patch(
                "server.routers.hardware.clear_current_session_bins",
                return_value={"ok": True, "cleared_bins": 2},
            ) as clear_mock,
            patch.object(hardware.shared_state, "gc_ref", gc_ref),
        ):
            result = hardware.clear_bin_category_assignments(scope="layer", layer_index=0)

        persist_mock.assert_called_once()
        persisted_categories = persist_mock.call_args.args[0]
        self.assertEqual([[[], []]], persisted_categories[0])
        self.assertEqual([[["set-3"]]], persisted_categories[1])
        runtime_stats.clearBinContents.assert_called_once_with(
            scope="layer",
            layer_index=0,
            section_index=None,
            bin_index=None,
        )
        clear_mock.assert_called_once_with(scope="layer", layer_index=0)
        self.assertEqual(
            "Reset all bins on layer 1 and cleared their assignments.",
            result["message"],
        )
        self.assertEqual(2, result["cleared_bins"])

    def test_empty_bin_contents_uses_layout_fallback_without_name_error(self) -> None:
        runtime_stats = SimpleNamespace(clearBinContents=unittest.mock.Mock())
        gc_ref = SimpleNamespace(runtime_stats=runtime_stats)
        layout = BinLayoutConfig(layers=[LayerConfig(sections=[["medium", "medium"]])])

        with (
            patch("server.routers.hardware._runtime_distribution_layout", return_value=None),
            patch("server.routers.hardware.getBinCategories", return_value=None),
            patch("server.routers.hardware.getBinLayout", return_value=layout),
            patch(
                "server.routers.hardware.clear_current_session_bins",
                return_value={"ok": True, "cleared_bins": 0},
            ) as clear_mock,
            patch.object(hardware.shared_state, "gc_ref", gc_ref),
        ):
            result = hardware.clear_bin_contents(
                scope="bin",
                layer_index=0,
                section_index=0,
                bin_index=1,
            )

        clear_mock.assert_called_once_with(
            scope="bin",
            layer_index=0,
            section_index=0,
            bin_index=1,
        )
        runtime_stats.clearBinContents.assert_called_once_with(
            scope="bin",
            layer_index=0,
            section_index=0,
            bin_index=1,
        )
        self.assertEqual(0, result["cleared_bins"])
        self.assertEqual(
            "Emptied bin 2 on layer 1 without changing its assignment.",
            result["message"],
        )


if __name__ == "__main__":
    unittest.main()
