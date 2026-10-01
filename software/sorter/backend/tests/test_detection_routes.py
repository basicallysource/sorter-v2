import unittest
from types import SimpleNamespace

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server import shared_state
from server.routers import detection


def _synthetic_rotor_frame(phase_deg: float = 22.0) -> np.ndarray:
    image = np.zeros((720, 720, 3), dtype=np.uint8)
    center = (360, 360)
    cv2.circle(image, center, 330, (210, 210, 210), -1)
    cv2.circle(image, center, 125, (0, 0, 0), -1)
    for i in range(5):
        angle = np.deg2rad(phase_deg + i * 72.0)
        inner = (
            int(round(center[0] + np.cos(angle) * 130)),
            int(round(center[1] + np.sin(angle) * 130)),
        )
        outer = (
            int(round(center[0] + np.cos(angle) * 300)),
            int(round(center[1] + np.sin(angle) * 300)),
        )
        cv2.line(image, inner, outer, (105, 105, 105), 10, cv2.LINE_AA)
        cv2.line(image, inner, outer, (245, 245, 245), 3, cv2.LINE_AA)
    cv2.rectangle(image, (330, 360), (395, 720), (0, 0, 0), -1)
    return image


class DetectionRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_gc_ref = shared_state.gc_ref
        self._old_vision_manager = shared_state.vision_manager
        self._old_controller_ref = shared_state.controller_ref

    def tearDown(self) -> None:
        shared_state.gc_ref = self._old_gc_ref
        shared_state.vision_manager = self._old_vision_manager
        shared_state.controller_ref = self._old_controller_ref

    def test_sector_occupancy_waits_for_first_inference(self) -> None:
        perception = SimpleNamespace(read_bboxes_and_frame=lambda channel_id: None)
        shared_state.gc_ref = SimpleNamespace(perception_service=perception)

        with self.assertRaises(HTTPException) as error:
            detection.classification_channel_sector_occupancy()

        self.assertEqual(503, error.exception.status_code)

    def test_classification_channel_sector_occupancy_rolls_candidates_into_sectors(self) -> None:
        frame = _synthetic_rotor_frame(phase_deg=22.0)
        center = (360.0, 360.0)

        def bbox_at_angle(angle_deg: float) -> list[int]:
            radians = np.deg2rad(angle_deg)
            cx = center[0] + np.cos(radians) * 160.0
            cy = center[1] + np.sin(radians) * 160.0
            return [
                int(round(cx - 18.0)),
                int(round(cy - 18.0)),
                int(round(cx + 18.0)),
                int(round(cy + 18.0)),
            ]

        candidates = [
            bbox_at_angle(58.0),
            bbox_at_angle(202.0),
        ]

        calls = []

        class FakePerception:
            def read_bboxes_and_frame(self, channel_id):
                calls.append(channel_id)
                return candidates, SimpleNamespace(bgr=frame)

        shared_state.gc_ref = SimpleNamespace(perception_service=FakePerception())
        shared_state.controller_ref = SimpleNamespace(
            coordinator=SimpleNamespace(
                irl_config=SimpleNamespace(
                    classification_channel_config=SimpleNamespace(
                        intake_angle_deg=305.0,
                        drop_angle_deg=120.0,
                    ),
                    feeder_config=SimpleNamespace(
                        classification_channel_eject=SimpleNamespace(
                            microsteps_per_second=3400,
                            acceleration_microsteps_per_second_sq=2500,
                        )
                    ),
                    c_channel_4_rotor_stepper=SimpleNamespace(microsteps=8),
                )
            )
        )

        payload = detection.classification_channel_sector_occupancy()

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["phase_ok"])
        self.assertGreater(payload["frame_luma"]["mean"], 100.0)
        self.assertEqual(5, payload["sector_count"])
        self.assertEqual(candidates, payload["candidate_bboxes"])
        self.assertEqual([0, 2], [entry["sector_index"] for entry in payload["detections"]])
        self.assertEqual([0, 2], [
            sector["sector_index"]
            for sector in payload["sectors"]
            if sector["state"] == "occupied"
        ])
        self.assertEqual([4], calls)

    def test_classification_channel_sector_occupancy_reports_dark_frame_diagnostics(self) -> None:
        frame = np.zeros((720, 720, 3), dtype=np.uint8)

        class FakePerception:
            def read_bboxes_and_frame(self, channel_id):
                return [], SimpleNamespace(bgr=frame)

        shared_state.gc_ref = SimpleNamespace(perception_service=FakePerception())

        payload = detection.classification_channel_sector_occupancy()

        self.assertFalse(payload["ok"])
        self.assertIn("disc fit failed", payload["message"])
        self.assertEqual(0, payload["frame_luma"]["max"])
        self.assertEqual(0.0, payload["frame_luma"]["nonblack_gt25_ratio"])
        self.assertEqual([], payload["sectors"])
        self.assertEqual([], payload["candidate_bboxes"])
        self.assertEqual([], payload["detections"])

    def test_classification_channel_sector_occupancy_endpoint_reports_dark_frame_diagnostics(self) -> None:
        frame = np.zeros((720, 720, 3), dtype=np.uint8)

        class FakePerception:
            def read_bboxes_and_frame(self, channel_id):
                return [], SimpleNamespace(bgr=frame)

        shared_state.gc_ref = SimpleNamespace(perception_service=FakePerception())
        app = FastAPI()
        app.include_router(detection.router)

        with TestClient(app) as client:
            response = client.post("/api/classification-channel/sector-occupancy")

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("disc fit failed", payload["message"])
        self.assertEqual(0, payload["frame_luma"]["max"])
        self.assertEqual([], payload["sectors"])


if __name__ == "__main__":
    unittest.main()
