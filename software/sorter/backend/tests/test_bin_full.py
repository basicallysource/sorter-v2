"""Bin-full pause: per-bin piece counts persist in local_state, reaching the
layer's ``max_pieces_per_bin`` raises the manual ``distribution_bin_full``
incident and pauses the machine, and only marking that bin emptied (or the
reset-bins flow) resolves it."""

from __future__ import annotations

import os
import queue
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from defs.events import PauseCommandEvent
from defs.known_object import KnownObject
from irl.bin_layout import Bin, BinSection, BinSize, DistributionLayout, Layer
from local_state import (
    get_current_bin_piece_counts,
    initialize_local_state,
    record_piece_distribution,
    start_new_sorting_session,
)
from piece_transport import ClassificationChannelTransport
from runtime_stats import RuntimeStatsCollector
from server import shared_state
from server.routers import detection, hardware
from sorting_profile import SortingProfile
from subsystems.bus import TickBus
from subsystems.distribution.chute import Chute
from subsystems.distribution.incidents import (
    DISTRIBUTION_BIN_FULL_INCIDENT_KIND,
    publish_bin_full_incident,
)
from subsystems.distribution.positioning import Positioning
from subsystems.distribution.sending import CHUTE_SETTLE_MS, Sending
from subsystems.distribution.states import DistributionState
from subsystems.shared_variables import SharedVariables


class _Logger:
    def info(self, *args, **kwargs) -> None:
        pass

    def warning(self, *args, **kwargs) -> None:
        pass

    warn = warning
    error = warning


class _Profiler:
    def hit(self, *args, **kwargs) -> None:
        pass


class _Profile(SortingProfile):
    def getCategoryIdForPart(self, part_id: str, color_id: str = "any_color") -> str:
        return "cat_a"

    def categoryLabel(self, category_id: str) -> str:
        return "Red Bricks" if category_id == "cat_a" else category_id


def _layout(max_pieces_per_bin: int | None) -> DistributionLayout:
    section = BinSection(bins=[Bin(size=BinSize.MEDIUM, category_ids=["cat_a"])])
    return DistributionLayout(layers=[Layer(sections=[section], max_pieces_per_bin=max_pieces_per_bin)])


def _piece(uuid: str) -> dict:
    return {
        "uuid": uuid,
        "destination_bin": [0, 0, 0],
        "distributed_at": time.time(),
        "part_id": "3001",
        "color_id": "5",
        "category_id": "cat_a",
    }


class BinFullTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = {k: os.environ.get(k) for k in ("MACHINE_SPECIFIC_PARAMS_PATH", "LOCAL_STATE_DB_PATH")}
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        (root / "machine_params.toml").write_text("[machine]\nnickname = \"Bench\"\n", encoding="utf-8")
        os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = str(root / "machine_params.toml")
        os.environ["LOCAL_STATE_DB_PATH"] = str(root / "local_state.sqlite")
        initialize_local_state()
        start_new_sorting_session(reason="test")

        self.runtime_stats = RuntimeStatsCollector()
        self.gc = SimpleNamespace(
            logger=_Logger(),
            profiler=_Profiler(),
            runtime_stats=self.runtime_stats,
            run_recorder=SimpleNamespace(recordPiece=lambda piece: None),
            set_progress_tracker=None,
            disable_servos=False,
            use_channel_bus=False,
        )
        self._saved = (shared_state.command_queue, shared_state.gc_ref, shared_state.controller_ref)
        self.cmd_queue: queue.Queue = queue.Queue()
        shared_state.command_queue = self.cmd_queue
        shared_state.gc_ref = self.gc
        shared_state.controller_ref = None

    def tearDown(self) -> None:
        shared_state.command_queue, shared_state.gc_ref, shared_state.controller_ref = self._saved
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmpdir.cleanup()

    # -- counter persistence --------------------------------------------------

    def test_record_piece_distribution_returns_running_count_and_survives_restart(self) -> None:
        self.assertEqual(1, record_piece_distribution(_piece("p1")))
        self.assertEqual(2, record_piece_distribution(_piece("p2")))
        self.assertIsNone(record_piece_distribution(_piece("p2")), "duplicate piece must not count twice")
        self.assertIsNone(record_piece_distribution({"uuid": "p3", "destination_bin": None, "distributed_at": 1.0}))

        initialize_local_state()  # same DB path = process restart
        self.assertEqual({(0, 0, 0): 2}, get_current_bin_piece_counts())

    # -- threshold -> incident + pause ----------------------------------------

    def _commit_piece(self, uuid: str, *, layout: DistributionLayout) -> None:
        transport = ClassificationChannelTransport()
        piece = KnownObject(tracked_global_id=7, part_id="3001", color_id="5")
        piece.uuid = uuid
        piece.category_id = "cat_a"
        piece.destination_bin = (0, 0, 0)
        transport._exit_piece = piece  # noqa: SLF001 — test-only shortcut
        shared = SharedVariables(gc=self.gc, bus=TickBus())
        shared.transport = transport
        shared.set_distribution_gate(False, reason="test")
        vision = SimpleNamespace(getFeederTrackerLiveGlobalIds=lambda role: set(), forceKillCarouselTrack=lambda gid: True)
        sending = Sending(
            SimpleNamespace(),  # type: ignore[arg-type]
            self.gc,  # type: ignore[arg-type]
            shared,
            queue.Queue(),
            layout=layout,
            sorting_profile=_Profile(),
            vision=vision,
        )
        self.assertIsNone(sending.step())
        sending.start_time = time.time() - CHUTE_SETTLE_MS / 1000.0 - 5.0
        sending.step()

    def test_sending_commit_raises_incident_and_pauses_when_limit_reached(self) -> None:
        layout = _layout(max_pieces_per_bin=2)
        self._commit_piece("p1", layout=layout)
        self.assertIsNone(self.runtime_stats.activeIncident())
        self.assertTrue(self.cmd_queue.empty())

        self._commit_piece("p2", layout=layout)
        incident = self.runtime_stats.activeIncident()
        self.assertIsNotNone(incident)
        self.assertEqual(DISTRIBUTION_BIN_FULL_INCIDENT_KIND, incident["kind"])
        self.assertTrue(incident["awaiting_operator"])
        self.assertEqual((0, 0, 0), (incident["layer_index"], incident["section_index"], incident["bin_index"]))
        self.assertEqual("Layer 1 / Section 1 / Bin 1", incident["bin_label"])
        self.assertEqual("cat_a", incident["category_id"])
        self.assertEqual("Red Bricks", incident["category_label"])
        self.assertEqual((2, 2), (incident["piece_count"], incident["max_pieces_per_bin"]))
        self.assertIsInstance(self.cmd_queue.get_nowait(), PauseCommandEvent)
        self.assertEqual({(0, 0, 0): 2}, get_current_bin_piece_counts())

    def test_sending_commit_without_limit_never_raises(self) -> None:
        layout = _layout(max_pieces_per_bin=None)
        for i in range(3):
            self._commit_piece(f"p{i}", layout=layout)
        self.assertIsNone(self.runtime_stats.activeIncident())
        self.assertTrue(self.cmd_queue.empty())
        self.assertEqual({(0, 0, 0): 3}, get_current_bin_piece_counts())

    def test_positioning_holds_piece_when_its_bin_is_already_full(self) -> None:
        # E.g. after a restart with a full bin: the next piece for that
        # category must not spill into another bin but re-raise the incident.
        record_piece_distribution(_piece("p1"))
        layout = _layout(max_pieces_per_bin=1)
        servo = SimpleNamespace(available=True, stopped=True, isClosed=lambda: True, isOpen=lambda: False, open=MagicMock(), close=MagicMock())
        shared = SharedVariables(gc=self.gc, bus=None)
        shared.transport = SimpleNamespace(getPieceForDistributionPositioning=lambda: KnownObject(part_id="3001", color_id="5"))
        chute = MagicMock(spec=Chute)
        chute.isBinReachable = MagicMock(return_value=True)
        positioning = Positioning(
            irl=SimpleNamespace(servos=[servo]),
            gc=self.gc,
            shared=shared,
            chute=chute,
            layout=layout,
            sorting_profile=_Profile(),
            event_queue=queue.Queue(),
        )

        self.assertEqual(DistributionState.IDLE, positioning.step())
        incident = self.runtime_stats.activeIncident()
        self.assertEqual(DISTRIBUTION_BIN_FULL_INCIDENT_KIND, incident["kind"])
        self.assertEqual(["cat_a"], layout.layers[0].sections[0].bins[0].category_ids)
        chute.moveToBin.assert_not_called()
        self.assertIsInstance(self.cmd_queue.get_nowait(), PauseCommandEvent)

    def test_handling_off_falls_back_to_legacy_skip(self) -> None:
        with patch("toml_config.incidentHandlingOff", return_value=True):
            self.assertFalse(
                publish_bin_full_incident(
                    self.gc, layer_index=0, section_index=0, bin_index=0,
                    category_id="cat_a", category_label="Red Bricks", piece_count=2, max_pieces_per_bin=2,
                )
            )
        self.assertIsNone(self.runtime_stats.activeIncident())
        self.assertTrue(self.cmd_queue.empty())

    # -- emptied -> resolved ---------------------------------------------------

    def _raise_full(self) -> None:
        record_piece_distribution(_piece("p1"))
        record_piece_distribution(_piece("p2"))
        self.assertTrue(
            publish_bin_full_incident(
                self.gc, layer_index=0, section_index=0, bin_index=0,
                category_id="cat_a", category_label="Red Bricks", piece_count=2, max_pieces_per_bin=2,
            )
        )
        self.cmd_queue.get_nowait()

    def test_bin_emptied_resets_count_and_resolves_incident(self) -> None:
        self._raise_full()
        result = hardware.mark_bin_emptied(hardware.BinEmptiedPayload(layer_index=0, section_index=0, bin_index=0))
        self.assertTrue(result["incident_resolved"])
        self.assertIsNone(self.runtime_stats.activeIncident())
        self.assertEqual({(0, 0, 0): 0}, get_current_bin_piece_counts())

    def test_emptying_another_bin_keeps_incident(self) -> None:
        self._raise_full()
        result = hardware.mark_bin_emptied(hardware.BinEmptiedPayload(layer_index=0, section_index=1, bin_index=0))
        self.assertFalse(result["incident_resolved"])
        self.assertEqual(DISTRIBUTION_BIN_FULL_INCIDENT_KIND, self.runtime_stats.activeIncident()["kind"])
        self.assertEqual(2, get_current_bin_piece_counts()[(0, 0, 0)])

    def test_generic_distribution_clear_does_not_resolve_bin_full(self) -> None:
        self._raise_full()
        result = detection.distribution_incident_clear()
        self.assertFalse(result["cleared"])
        self.assertEqual(DISTRIBUTION_BIN_FULL_INCIDENT_KIND, self.runtime_stats.activeIncident()["kind"])

    # -- reset clears ----------------------------------------------------------

    def test_reset_bins_clears_all_counts_and_incident(self) -> None:
        self._raise_full()
        record_piece_distribution({**_piece("p3"), "destination_bin": [1, 2, 0]})
        hardware.clear_bin_category_assignments(scope="all")
        self.assertIsNone(self.runtime_stats.activeIncident())
        self.assertEqual({0}, set(get_current_bin_piece_counts().values()))


if __name__ == "__main__":
    unittest.main()
