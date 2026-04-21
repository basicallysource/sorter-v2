import unittest

from fastapi import HTTPException

from server import shared_state
from server.routers import detection


class _FakeVisionManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def debugFeederDetection(self, role: str, *, include_capture: bool = False):
        self.calls.append((role, include_capture))
        return {
            "camera": role,
            "algorithm": "gemini_sam",
            "found": False,
            "message": "No piece in frame.",
            "frame_resolution": [1280, 720],
            "candidate_bboxes": [],
            "bbox_count": 0,
            "bbox": None,
            "zone_bbox": None,
        }

    def getFeederOpenRouterModel(self) -> str:
        return "google/gemini-3-flash-preview"


class DetectionRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_vision_manager = shared_state.vision_manager

    def tearDown(self) -> None:
        shared_state.vision_manager = self._old_vision_manager

    def test_debug_feeder_detection_accepts_classification_channel_role(self) -> None:
        fake_vision = _FakeVisionManager()
        shared_state.vision_manager = fake_vision

        payload = detection.debug_feeder_detection("carousel")

        self.assertTrue(payload["ok"])
        self.assertEqual("classification_channel", payload["camera"])
        self.assertEqual([("carousel", True)], fake_vision.calls)

    def test_debug_feeder_detection_rejects_unknown_role(self) -> None:
        shared_state.vision_manager = _FakeVisionManager()

        with self.assertRaises(HTTPException) as excinfo:
            detection.debug_feeder_detection("nope")

        self.assertEqual(400, excinfo.exception.status_code)
        self.assertEqual("Unsupported feeder role.", excinfo.exception.detail)


if __name__ == "__main__":
    unittest.main()
