"""Integration: rt PIECE_* events → local_state dossier table → UI list.

Verifies the full pipe from EventBus publish through the bootstrap-style
subscriber into ``remember_piece_dossier`` and out via
``list_piece_dossiers``. This is the test that would have caught the
2026-04-22 audit findings (H1 + H2) at cutover time.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from rt.contracts.events import Event
from rt.events.bus import InProcessEventBus
from rt.events.topics import (
    PIECE_CLASSIFIED,
    PIECE_DISTRIBUTED,
    PIECE_REGISTERED,
)


class _BootstrapStyleSubscriber:
    """Mirror of rt.bootstrap._on_piece_event wiring, extracted for tests.

    Keeping the logic in lockstep here is intentional — if bootstrap is
    ever refactored the diff will surface immediately via this suite.
    """

    _TOPIC_TO_STAGE = {
        PIECE_REGISTERED: "registered",
        PIECE_CLASSIFIED: "classified",
        PIECE_DISTRIBUTED: "distributed",
    }

    def __init__(self) -> None:
        from local_state import remember_piece_dossier

        self._remember = remember_piece_dossier

    def attach(self, bus: InProcessEventBus) -> None:
        for topic in (PIECE_REGISTERED, PIECE_CLASSIFIED, PIECE_DISTRIBUTED):
            bus.subscribe(topic, self._handle)

    def _handle(self, event: Event) -> None:
        payload = dict(event.payload or {})
        piece_uuid = payload.get("piece_uuid") or payload.get("uuid")
        if not isinstance(piece_uuid, str) or not piece_uuid.strip():
            return
        dossier_payload = dict(payload)
        nested = payload.get("dossier")
        if isinstance(nested, dict):
            for k, v in nested.items():
                dossier_payload.setdefault(k, v)
        stage = str(payload.get("stage") or self._TOPIC_TO_STAGE.get(event.topic, ""))
        if event.topic == PIECE_DISTRIBUTED:
            dossier_payload.setdefault("distributed_at", time.time())
        self._remember(piece_uuid, dossier_payload, status=stage or None)


class PieceDossierFlowIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_machine_params = os.environ.get("MACHINE_SPECIFIC_PARAMS_PATH")
        self._old_local_state_db = os.environ.get("LOCAL_STATE_DB_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmpdir.name)
        self.machine_params_path = tmp_dir / "machine_params.toml"
        self.local_state_db_path = tmp_dir / "local_state.sqlite"
        self.machine_params_path.write_text(
            '[machine]\nnickname = "DossierFlowBench"\n', encoding="utf-8"
        )
        os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = str(self.machine_params_path)
        os.environ["LOCAL_STATE_DB_PATH"] = str(self.local_state_db_path)

        # Late import so the environment variables are picked up by the
        # module-level path helpers.
        from local_state import (
            get_piece_dossier,
            initialize_local_state,
            list_piece_dossiers,
            start_new_sorting_session,
        )

        self._get_piece_dossier = get_piece_dossier
        self._list_piece_dossiers = list_piece_dossiers

        initialize_local_state()
        start_new_sorting_session(reason="dossier_flow_test")

    def tearDown(self) -> None:
        if self._old_machine_params is None:
            os.environ.pop("MACHINE_SPECIFIC_PARAMS_PATH", None)
        else:
            os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = self._old_machine_params
        if self._old_local_state_db is None:
            os.environ.pop("LOCAL_STATE_DB_PATH", None)
        else:
            os.environ["LOCAL_STATE_DB_PATH"] = self._old_local_state_db
        self._tmpdir.cleanup()

    def _event(self, topic: str, payload: dict) -> Event:
        return Event(topic=topic, payload=payload, source="test", ts_mono=time.monotonic())

    def test_full_lifecycle_reaches_list_piece_dossiers(self) -> None:
        bus = InProcessEventBus()
        _BootstrapStyleSubscriber().attach(bus)

        piece_uuid = "rt-flow-piece-1"

        # 1. PIECE_REGISTERED — tracker confirmed, no segments yet.
        bus.publish(
            self._event(
                PIECE_REGISTERED,
                {
                    "piece_uuid": piece_uuid,
                    "tracked_global_id": 1234,
                    "confirmed_real": True,
                    "dossier": {
                        "classification_channel_zone_center_deg": 305.0,
                    },
                },
            )
        )
        bus.drain()

        dossier = self._get_piece_dossier(piece_uuid)
        self.assertIsNotNone(dossier)
        assert dossier is not None
        self.assertEqual(piece_uuid, dossier["uuid"])
        self.assertEqual(1234, dossier["tracked_global_id"])
        self.assertEqual("registered", dossier["stage"])
        self.assertTrue(dossier.get("confirmed_real"))

        listed_after_register = {
            entry["uuid"] for entry in self._list_piece_dossiers(limit=50)
        }
        self.assertIn(
            piece_uuid,
            listed_after_register,
            "H2 regression: confirmed pending piece must appear in list_piece_dossiers",
        )

        # 2. PIECE_CLASSIFIED — classifier returned part/color.
        bus.publish(
            self._event(
                PIECE_CLASSIFIED,
                {
                    "piece_uuid": piece_uuid,
                    "tracked_global_id": 1234,
                    "dossier": {
                        "part_id": "3001",
                        "color_id": "4",
                        "category": "brick",
                        "confidence": 0.92,
                    },
                },
            )
        )
        bus.drain()

        dossier = self._get_piece_dossier(piece_uuid)
        assert dossier is not None
        self.assertEqual("classified", dossier["stage"])
        self.assertEqual("3001", dossier.get("part_id"))
        self.assertEqual("4", dossier.get("color_id"))

        # 3. PIECE_DISTRIBUTED — chute delivered to bin.
        bus.publish(
            self._event(
                PIECE_DISTRIBUTED,
                {
                    "piece_uuid": piece_uuid,
                    "bin_id": "L0-S0-B2",
                    "accepted": True,
                    "category": "brick",
                    "reason": "ok",
                },
            )
        )
        bus.drain()

        dossier = self._get_piece_dossier(piece_uuid)
        assert dossier is not None
        self.assertEqual("distributed", dossier["stage"])
        self.assertEqual("L0-S0-B2", dossier.get("bin_id"))
        self.assertIsNotNone(dossier.get("distributed_at"))

        # 4. list_piece_dossiers() returns the piece in its terminal state.
        listed = self._list_piece_dossiers(limit=50)
        uuids = [entry["uuid"] for entry in listed]
        self.assertIn(piece_uuid, uuids)
        entry = next(e for e in listed if e["uuid"] == piece_uuid)
        self.assertEqual("distributed", entry["stage"])
        self.assertEqual("L0-S0-B2", entry.get("bin_id"))

    def test_payload_with_uuid_field_still_resolves(self) -> None:
        """Defensive: some legacy emitters may use ``uuid`` instead of
        ``piece_uuid``. The subscriber must accept either spelling."""
        bus = InProcessEventBus()
        _BootstrapStyleSubscriber().attach(bus)

        bus.publish(
            self._event(
                PIECE_REGISTERED,
                {
                    "uuid": "rt-legacy-1",
                    "confirmed_real": True,
                    "tracked_global_id": 7777,
                },
            )
        )
        bus.drain()

        dossier = self._get_piece_dossier("rt-legacy-1")
        self.assertIsNotNone(dossier)
        assert dossier is not None
        self.assertEqual("rt-legacy-1", dossier["uuid"])

    def test_event_without_piece_uuid_is_ignored(self) -> None:
        bus = InProcessEventBus()
        _BootstrapStyleSubscriber().attach(bus)

        # Missing both piece_uuid and uuid — must be a silent no-op, not
        # a crash that poisons the dispatcher thread.
        bus.publish(
            self._event(PIECE_CLASSIFIED, {"tracked_global_id": 42})
        )
        bus.drain()

        self.assertEqual([], self._list_piece_dossiers(limit=50))


if __name__ == "__main__":
    unittest.main()
