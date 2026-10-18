import os
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

import local_state
import sharing
from server.routers import sharing as sharing_router


def _target(target_id: str, **extra) -> dict:
    return {"id": target_id, "name": target_id, "url": f"https://{target_id}.example", "api_token": "t", "enabled": True, **extra}


class _StateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._old_db = os.environ.get("LOCAL_STATE_DB_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["LOCAL_STATE_DB_PATH"] = os.path.join(self._tmpdir.name, "state.sqlite")
        sharing.invalidate()

    def tearDown(self) -> None:
        sharing.invalidate()
        if self._old_db is None:
            os.environ.pop("LOCAL_STATE_DB_PATH", None)
        else:
            os.environ["LOCAL_STATE_DB_PATH"] = self._old_db
        self._tmpdir.cleanup()

    def hives(self, *targets: dict) -> None:
        local_state.set_hive_config({"targets": list(targets), "primary_target_id": targets[0]["id"] if targets else None})


class SharingTests(_StateTestCase):
    def test_nothing_is_shared_before_consent(self) -> None:
        self.hives(_target("a"))
        sharing.invalidate()
        local_state.set_sharing_state({"every_hive": {}, "targets": {}, "consent": None})
        self.assertFalse(sharing.streamAllowed("a", "machine_telemetry"))
        self.assertTrue(sharing.consentView()["needs_consent"])
        sharing.recordConsent(sharing.CONSENT_VERSION, {"channel_crops": False})
        self.assertTrue(sharing.streamAllowed("a", "machine_telemetry"))
        self.assertTrue(sharing.streamAllowed("a", "piece_images"))
        self.assertFalse(sharing.streamAllowed("a", "channel_crops"))
        self.assertFalse(sharing.consentView()["needs_review"])

    def test_a_fresh_machine_waits_for_consent_and_an_existing_one_is_grandfathered(self) -> None:
        self.assertTrue(sharing.consentView()["needs_consent"])
        sharing.invalidate()
        local_state.set_sharing_state(None)  # type: ignore[arg-type]
        self.hives(_target("a"))
        sharing.invalidate()
        view = sharing.consentView()
        self.assertFalse(view["needs_consent"])
        self.assertTrue(view["needs_review"])
        self.assertTrue(sharing.streamAllowed("a", "piece_records"))

    def test_choices_made_before_move_into_every_hive_or_overrides(self) -> None:
        # As an older version stored them: on each target, under the old keys.
        local_state._write_state(local_state._STATE_KEY_HIVE, {
            "targets": [
                _target("a", telemetry={"upstream_channel_crops": False, "detection_images": False, "machine_specs": False}),
                _target("b", telemetry={"upstream_channel_crops": False}),
            ],
            "primary_target_id": "a",
        })
        self.assertEqual({"channel_crops": False}, sharing._state()["every_hive"])
        self.assertEqual({"piece_images": False}, sharing.targetOverrides("a"))
        self.assertEqual({}, sharing.targetOverrides("b"))
        # Required now, whatever was chosen before.
        self.assertTrue(sharing.effective("a")["machine_telemetry"])
        # The old per-target fields are gone from the Hive config.
        self.assertEqual({}, local_state.get_legacy_hive_telemetry())

    def test_overrides_follow_every_hive_unless_set(self) -> None:
        self.hives(_target("a"), _target("b"))
        sharing.recordConsent(sharing.CONSENT_VERSION)
        sharing.setForTarget("b", {"piece_images": False})
        self.assertEqual({"piece_images": False}, sharing.targetOverrides("b"))
        sharing.setEveryHive({"feeder_logs": False})
        self.assertFalse(sharing.effective("a")["feeder_logs"])
        self.assertFalse(sharing.effective("b")["feeder_logs"])
        self.assertTrue(sharing.effective("a")["piece_images"])
        self.assertFalse(sharing.effective("b")["piece_images"])
        # Every Hive now matches b's override, so it is no override any more.
        sharing.setEveryHive({"piece_images": False})
        self.assertEqual({}, sharing.targetOverrides("b"))
        # Setting a Hive back to every Hive's value removes its override.
        sharing.setForTarget("a", {"feeder_logs": True})
        sharing.setForTarget("a", {"feeder_logs": False})
        self.assertEqual({}, sharing.targetOverrides("a"))
        self.assertEqual(["piece_images", "feeder_logs"], sharing.everyHiveSet())
        sharing.resetEveryHive()
        self.assertEqual(sharing.defaults(), sharing.everyHive())

    def test_required_and_unknown_streams_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            sharing.setEveryHive({"machine_telemetry": False})
        with self.assertRaises(ValueError):
            sharing.setEveryHive({"bogus": True})
        with self.assertRaises(ValueError):
            sharing.recordConsent(sharing.CONSENT_VERSION + 1)

    def test_the_api(self) -> None:
        self.hives(_target("a"), _target("b"))
        sharing.invalidate()
        local_state.set_sharing_state({"every_hive": {}, "targets": {}, "consent": None})
        app = FastAPI()
        app.include_router(sharing_router.router)
        client = TestClient(app)
        view = client.get("/api/sharing").json()
        self.assertEqual("machine_telemetry", view["streams"][0]["key"])
        self.assertTrue(view["streams"][0]["required"])
        self.assertTrue(view["consent"]["needs_consent"])
        values = {key: True for key in sharing.OPTIONAL_KEYS} | {"network": False}
        view = client.post("/api/sharing/consent", json={"version": 1, "values": values}).json()
        self.assertFalse(view["consent"]["needs_consent"])
        self.assertEqual(["network"], view["every_hive_set"])
        view = client.post("/api/sharing", json={"target_id": "b", "values": {"channel_crops": False}}).json()
        b = next(t for t in view["targets"] if t["id"] == "b")
        self.assertEqual({"channel_crops": False}, b["overrides"])
        self.assertFalse(b["effective"]["channel_crops"])
        self.assertTrue(b["effective"]["machine_telemetry"])
        self.assertEqual(404, client.post("/api/sharing", json={"target_id": "nope", "values": {}}).status_code)
        self.assertEqual(400, client.post("/api/sharing", json={"values": {"machine_telemetry": False}}).status_code)
        view = client.post("/api/sharing/reset", json={"target_id": "b"}).json()
        self.assertEqual({}, next(t for t in view["targets"] if t["id"] == "b")["overrides"])
        stats = client.get("/api/sharing/stats?hours=3").json()
        self.assertEqual(3, len(stats["hour_starts"]))
        self.assertEqual(["a", "b"], [t["id"] for t in stats["targets"]])
        self.assertEqual([0, 0, 0], stats["targets"][0]["series"]["piece_images"]["sent"])
        self.assertEqual("telemetry", stats["local"][0]["key"])


if __name__ == "__main__":
    unittest.main()
