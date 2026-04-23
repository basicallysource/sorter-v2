"""Integration: rt PIECE_* events → local_state dossier table → UI list.

Verifies the full pipe from EventBus publish through the real
``rt.projections.piece_dossier.install`` subscriber into
``remember_piece_dossier`` and out via ``list_piece_dossiers``. This is the
test that would have caught the 2026-04-22 audit findings (H1 + H2) at
cutover time.
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
from rt.projections.piece_dossier import (
    install as install_piece_dossier,
    refresh_piece_preview_and_push,
)


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
            get_recent_known_objects,
            initialize_local_state,
            list_piece_dossiers,
            remember_piece_segment,
            start_new_sorting_session,
        )

        self._get_piece_dossier = get_piece_dossier
        self._get_recent_known_objects = get_recent_known_objects
        self._list_piece_dossiers = list_piece_dossiers
        self._remember_piece_segment = remember_piece_segment

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
        install_piece_dossier(bus)

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
                        "meta": {
                            "name": "Brick 2 x 4",
                            "color_name": "Red",
                            "preview_url": "https://example.test/3001.jpg",
                        },
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
        self.assertEqual("brick", dossier.get("part_category"))
        self.assertEqual("Brick 2 x 4", dossier.get("part_name"))
        self.assertEqual("Red", dossier.get("color_name"))
        self.assertEqual(
            "https://example.test/3001.jpg",
            dossier.get("brickognize_preview_url"),
        )

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
        self.assertEqual([0, 0, 2], dossier.get("destination_bin"))
        self.assertEqual("brick", dossier.get("category_id"))
        self.assertEqual("ok", dossier.get("distribution_reason"))
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
        install_piece_dossier(bus)

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

    def test_projection_mirrors_into_recent_known_objects(self) -> None:
        """Regression: after the dossier upsert the projection must also
        push the merged payload into ``recent_known_objects`` so that a
        reconnecting WS client picks the piece up on replay and the
        dashboard's Recent Pieces panel isn't left empty between full
        reloads.
        """
        bus = InProcessEventBus()
        install_piece_dossier(bus)

        piece_uuid = "rt-recent-piece-1"
        bus.publish(
            self._event(
                PIECE_REGISTERED,
                {
                    "piece_uuid": piece_uuid,
                    "tracked_global_id": 9001,
                    "confirmed_real": True,
                    "dossier": {
                        "classification_channel_zone_center_deg": 90.0,
                        "first_carousel_seen_ts": 123.456,
                    },
                },
            )
        )
        bus.drain()

        recent = self._get_recent_known_objects()
        uuids = [entry.get("uuid") for entry in recent]
        self.assertIn(piece_uuid, uuids)
        entry = next(e for e in recent if e.get("uuid") == piece_uuid)
        self.assertEqual("registered", entry.get("stage"))
        self.assertEqual(123.456, entry.get("first_carousel_seen_ts"))

    def test_preview_refresh_updates_recent_pending_piece(self) -> None:
        bus = InProcessEventBus()
        install_piece_dossier(bus)

        piece_uuid = "rt-preview-refresh-1"
        bus.publish(
            self._event(
                PIECE_REGISTERED,
                {
                    "piece_uuid": piece_uuid,
                    "tracked_global_id": 9002,
                    "confirmed_real": True,
                    "dossier": {
                        "classification_channel_zone_center_deg": 42.0,
                        "first_carousel_seen_ts": 123.456,
                    },
                },
            )
        )
        bus.drain()

        self._remember_piece_segment(
            piece_uuid,
            "carousel",
            0,
            {
                "tracked_global_id": 9002,
                "first_seen_ts": 123.456,
                "last_seen_ts": 125.0,
                "hit_count": 4,
                "snapshot_path": f"piece_crops/{piece_uuid}/seg0/snapshot_000.jpg",
                "sector_snapshots": [],
            },
        )

        refreshed = refresh_piece_preview_and_push(piece_uuid, broadcast=False)

        assert refreshed is not None
        self.assertEqual(
            f"piece_crops/{piece_uuid}/seg0/snapshot_000.jpg",
            refreshed.get("preview_jpeg_path"),
        )
        recent = self._get_recent_known_objects()
        entry = next(e for e in recent if e.get("uuid") == piece_uuid)
        self.assertEqual(
            f"piece_crops/{piece_uuid}/seg0/snapshot_000.jpg",
            entry.get("preview_jpeg_path"),
        )

    def test_event_without_piece_uuid_is_ignored(self) -> None:
        bus = InProcessEventBus()
        install_piece_dossier(bus)

        # Missing both piece_uuid and uuid — must be a silent no-op, not
        # a crash that poisons the dispatcher thread.
        bus.publish(
            self._event(PIECE_CLASSIFIED, {"tracked_global_id": 42})
        )
        bus.drain()

        self.assertEqual([], self._list_piece_dossiers(limit=50))


if __name__ == "__main__":
    unittest.main()
