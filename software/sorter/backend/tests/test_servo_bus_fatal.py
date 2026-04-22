"""Fail-fast behavior when the Waveshare servo bus is unreachable.

The backend used to log a one-line warning and keep running when the
Waveshare bus failed to open — every piece silently fell into the
discard bucket. These tests verify the new fail-fast path:

1. Positioning notices that every configured layer servo is offline,
   pauses the controller via the command queue, sets a red banner, and
   records the fault on ``runtime_stats``.
2. A single-layer servo failure (the other layer's servo is healthy)
   does **not** trip the fatal banner.
3. Once any servo reports healthy again, the banner auto-clears so a
   Resume after reconnecting the bus recovers without a full restart.
"""

from __future__ import annotations

import queue
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from defs.events import PauseCommandEvent
from defs.known_object import KnownObject
from irl.bin_layout import Bin, BinSection, BinSize, DistributionLayout, Layer
from runtime_stats import RuntimeStatsCollector
from server import shared_state
from sorting_profile import MISC_CATEGORY, SortingProfile
from subsystems.distribution.chute import BinAddress, Chute
from subsystems.distribution.positioning import (
    CHUTE_JAM_ALERT_PREFIX,
    Positioning,
    SERVO_BUS_ALERT_PREFIX,
)
from subsystems.shared_variables import SharedVariables


class _Logger:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def info(self, msg: str, *args, **kwargs) -> None:
        self.messages.append(("info", str(msg)))

    def warning(self, msg: str, *args, **kwargs) -> None:
        self.messages.append(("warning", str(msg)))

    def warn(self, msg: str, *args, **kwargs) -> None:
        self.messages.append(("warn", str(msg)))

    def error(self, msg: str, *args, **kwargs) -> None:
        self.messages.append(("error", str(msg)))


class _Profiler:
    def hit(self, *_args, **_kwargs) -> None:
        return


class _AllCategoriesProfile(SortingProfile):
    def __init__(self, category_id: str = "cat_a") -> None:
        self._category_id = category_id

    def getCategoryIdForPart(self, part_id: str, color_id: str = "any_color") -> str:
        return self._category_id


def _mk_offline_servo() -> SimpleNamespace:
    servo = SimpleNamespace(available=False, stopped=True)
    servo.isClosed = lambda: False
    servo.isOpen = lambda: False
    servo.open = MagicMock(side_effect=RuntimeError("bus offline"))
    servo.close = MagicMock(side_effect=RuntimeError("bus offline"))
    return servo


def _mk_healthy_servo() -> SimpleNamespace:
    servo = SimpleNamespace(available=True, stopped=True)
    servo.isClosed = lambda: True
    servo.isOpen = lambda: False
    servo.open = MagicMock()
    servo.close = MagicMock()
    return servo


def _mk_layout(num_layers: int = 2) -> DistributionLayout:
    layers: list[Layer] = []
    for _ in range(num_layers):
        section = BinSection(bins=[Bin(size=BinSize.MEDIUM, category_ids=["cat_a"])])
        layer = Layer(sections=[section])
        layer.enabled = True
        layer.max_pieces_per_bin = None
        layers.append(layer)
    return DistributionLayout(layers=layers)


def _mk_piece() -> KnownObject:
    return KnownObject(part_id="3001", color_id="5")


class ServoBusFatalTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_error = shared_state.hardware_error
        self._saved_state = shared_state.hardware_state
        self._saved_queue = shared_state.command_queue
        shared_state.hardware_error = None
        shared_state.hardware_state = "standby"
        self.cmd_queue: queue.Queue = queue.Queue()
        shared_state.command_queue = self.cmd_queue

        self.runtime_stats = RuntimeStatsCollector()
        self.logger = _Logger()
        self.gc = SimpleNamespace(
            logger=self.logger,
            disable_servos=False,
            profiler=_Profiler(),
            runtime_stats=self.runtime_stats,
            run_recorder=SimpleNamespace(markPaused=lambda: None, markRunning=lambda: None),
            use_channel_bus=False,
        )

    def tearDown(self) -> None:
        shared_state.hardware_error = self._saved_error
        shared_state.hardware_state = self._saved_state
        shared_state.command_queue = self._saved_queue

    def _mk_positioning(
        self,
        servos: list[SimpleNamespace],
        *,
        layout: DistributionLayout | None = None,
    ) -> Positioning:
        layout = layout or _mk_layout(num_layers=len(servos))
        irl = SimpleNamespace(servos=servos)
        piece = _mk_piece()
        transport = SimpleNamespace(
            getPieceForDistributionPositioning=lambda: piece,
        )
        shared = SharedVariables(gc=self.gc, bus=None)
        shared.transport = transport
        chute = MagicMock(spec=Chute)
        chute.isBinReachable = MagicMock(return_value=True)
        chute.moveToBin = MagicMock(return_value=250)
        chute.stepper = SimpleNamespace(stopped=True)
        positioning = Positioning(
            irl=irl,
            gc=self.gc,
            shared=shared,
            chute=chute,
            layout=layout,
            sorting_profile=_AllCategoriesProfile(),
            event_queue=queue.Queue(),
        )
        return positioning

    def test_all_layers_offline_raises_fatal_and_pauses(self) -> None:
        positioning = self._mk_positioning(
            servos=[_mk_offline_servo(), _mk_offline_servo()]
        )
        positioning.step()

        # Fatal banner set + distinct from chute-jam prefix.
        self.assertIsNotNone(shared_state.hardware_error)
        assert shared_state.hardware_error is not None
        self.assertTrue(shared_state.hardware_error.startswith(SERVO_BUS_ALERT_PREFIX))
        self.assertFalse(shared_state.hardware_error.startswith(CHUTE_JAM_ALERT_PREFIX))

        # A pause command was enqueued for the main-thread handler.
        self.assertFalse(self.cmd_queue.empty())
        event = self.cmd_queue.get_nowait()
        self.assertIsInstance(event, PauseCommandEvent)

        # Runtime stats recorded the fault timestamp for the UI.
        self.assertIsNotNone(self.runtime_stats.servo_bus_offline_since_ts)
        snap = self.runtime_stats.snapshot()
        self.assertIsNotNone(snap.get("servo_bus_offline_since_ts"))

    def test_single_offline_layer_does_not_trip_fatal(self) -> None:
        # Layer 0 is offline but layer 1's servo is healthy — Positioning
        # must keep running on the remaining layer, NOT raise the fatal
        # bus-offline banner.
        positioning = self._mk_positioning(
            servos=[_mk_offline_servo(), _mk_healthy_servo()]
        )
        positioning.step()

        self.assertIsNone(shared_state.hardware_error)
        self.assertTrue(self.cmd_queue.empty())
        self.assertIsNone(self.runtime_stats.servo_bus_offline_since_ts)

    def test_repeat_detection_does_not_spam_error_or_queue(self) -> None:
        # Re-entering Positioning while the bus is still offline must not
        # enqueue a second pause or re-log the banner on every tick.
        positioning = self._mk_positioning(
            servos=[_mk_offline_servo(), _mk_offline_servo()]
        )
        positioning.step()
        first_stamp = self.runtime_stats.servo_bus_offline_since_ts

        positioning._phase = "init"
        positioning.step()
        positioning._phase = "init"
        positioning.step()

        drained: list = []
        while not self.cmd_queue.empty():
            drained.append(self.cmd_queue.get_nowait())
        self.assertEqual(1, len(drained))
        # Timestamp must not be reset on each observation.
        self.assertEqual(first_stamp, self.runtime_stats.servo_bus_offline_since_ts)

    def test_banner_clears_when_servo_comes_back_online(self) -> None:
        # Simulate mid-run failure: first step finds every layer offline →
        # banner + pause. Then the bus recovers (both servos flip back
        # to available=True) and a follow-up step is allowed to proceed,
        # which clears the banner.
        servos = [_mk_offline_servo(), _mk_offline_servo()]
        positioning = self._mk_positioning(servos=servos)
        positioning.step()
        self.assertTrue(
            (shared_state.hardware_error or "").startswith(SERVO_BUS_ALERT_PREFIX)
        )

        # Bus recovered: flip the servos back to healthy.
        for servo in servos:
            servo.available = True
            servo.isClosed = lambda: True
            servo.open = MagicMock()
            servo.close = MagicMock()

        positioning._phase = "init"
        positioning.step()

        self.assertIsNone(shared_state.hardware_error)
        self.assertIsNone(self.runtime_stats.servo_bus_offline_since_ts)


class MainBootServoHealthCheckTests(unittest.TestCase):
    """Boot-time: main.py's ``_checkServoBusHealth`` flips the red banner
    if every configured servo comes back with ``available=False`` after
    the ``servo.open()`` pass. A successful boot (at least one healthy
    servo) must NOT set any error.
    """

    def setUp(self) -> None:
        self._saved_error = shared_state.hardware_error
        shared_state.hardware_error = None
        self.runtime_stats = RuntimeStatsCollector()
        self.logger = _Logger()
        self.gc = SimpleNamespace(
            logger=self.logger,
            runtime_stats=self.runtime_stats,
        )

    def tearDown(self) -> None:
        shared_state.hardware_error = self._saved_error

    def _run_check(self, servos: list[SimpleNamespace]) -> None:
        from main import _checkServoBusHealth

        irl = SimpleNamespace(servos=servos)
        _checkServoBusHealth(self.gc, irl)

    def test_boot_with_all_offline_sets_fatal_banner(self) -> None:
        self._run_check([_mk_offline_servo(), _mk_offline_servo()])
        self.assertIsNotNone(shared_state.hardware_error)
        assert shared_state.hardware_error is not None
        self.assertTrue(shared_state.hardware_error.startswith(SERVO_BUS_ALERT_PREFIX))
        self.assertIsNotNone(self.runtime_stats.servo_bus_offline_since_ts)

    def test_boot_with_at_least_one_online_leaves_error_clear(self) -> None:
        self._run_check([_mk_offline_servo(), _mk_healthy_servo()])
        self.assertIsNone(shared_state.hardware_error)
        self.assertIsNone(self.runtime_stats.servo_bus_offline_since_ts)

    def test_boot_with_no_servos_configured_is_a_noop(self) -> None:
        self._run_check([])
        self.assertIsNone(shared_state.hardware_error)


if __name__ == "__main__":
    unittest.main()
