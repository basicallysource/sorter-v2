from __future__ import annotations

import queue
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from defs.known_object import KnownObject, PieceStage
from irl.bin_layout import Bin, BinSection, BinSize, DistributionLayout, Layer
from sorting_profile import MISC_CATEGORY, SortingProfile
from subsystems.distribution.chute import Chute
from subsystems.distribution.positioning import Positioning
from subsystems.distribution.states import DistributionState
from subsystems.shared_variables import SharedVariables


class _Logger:
    def info(self, *args, **kwargs) -> None:
        pass

    def warning(self, *args, **kwargs) -> None:
        pass

    def warn(self, *args, **kwargs) -> None:
        pass

    def error(self, *args, **kwargs) -> None:
        pass


class _Profiler:
    def hit(self, *args, **kwargs) -> None:
        pass


class _MiscProfile(SortingProfile):
    def getCategoryIdForPart(self, part_id: str, color_id: str = "any_color") -> str:
        return MISC_CATEGORY


def _mk_layout() -> DistributionLayout:
    layer = Layer(
        sections=[BinSection(bins=[Bin(size=BinSize.MEDIUM, category_ids=["cat_a"])])],
        enabled=True,
        max_pieces_per_bin=None,
    )
    return DistributionLayout(layers=[layer])


def _mk_servo() -> SimpleNamespace:
    servo = SimpleNamespace(available=True, stopped=True)
    servo.isClosed = lambda: True
    servo.isOpen = lambda: False
    servo.open = MagicMock()
    servo.close = MagicMock()
    return servo


class DistributionPositioningPassthroughTests(unittest.TestCase):
    def _mk_positioning(self) -> tuple[Positioning, KnownObject, SimpleNamespace]:
        piece = KnownObject()
        gc = SimpleNamespace(
            logger=_Logger(),
            disable_servos=False,
            profiler=_Profiler(),
            runtime_stats=SimpleNamespace(
                observeStateTransition=lambda *args, **kwargs: None,
                observeBlockedReason=lambda *args, **kwargs: None,
                setServoBusOffline=lambda *args, **kwargs: None,
                clearServoBusOffline=lambda *args, **kwargs: None,
            ),
            run_recorder=SimpleNamespace(markPaused=lambda: None, markRunning=lambda: None),
            use_channel_bus=False,
        )
        shared = SharedVariables(
            gc=gc,
            bus=None,
        )
        shared.transport = SimpleNamespace(
            getPieceForDistributionPositioning=lambda: piece,
        )
        chute = MagicMock(spec=Chute)
        chute.first_bin_center = 8.25
        chute.moveToAngle = MagicMock(return_value=180)
        chute.moveToBin = MagicMock(return_value=0)
        chute.stepper = SimpleNamespace(stopped=False)
        irl = SimpleNamespace(servos=[_mk_servo()])
        positioning = Positioning(
            irl=irl,
            gc=gc,
            shared=shared,
            chute=chute,
            layout=_mk_layout(),
            sorting_profile=_MiscProfile(),
            event_queue=queue.Queue(),
        )
        return positioning, piece, chute

    def test_passthrough_moves_chute_to_known_angle_before_ready(self) -> None:
        positioning, piece, chute = self._mk_positioning()

        first_step = positioning.step()

        self.assertIsNone(first_step)
        chute.moveToAngle.assert_called_once_with(8.25)
        chute.moveToBin.assert_not_called()
        self.assertEqual(PieceStage.distributing, piece.stage)
        self.assertIsNone(piece.destination_bin)

        chute.stepper.stopped = True
        second_step = positioning.step()

        self.assertEqual(DistributionState.READY, second_step)


if __name__ == "__main__":
    unittest.main()
