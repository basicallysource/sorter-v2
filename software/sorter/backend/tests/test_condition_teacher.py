from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

import cv2
import numpy as np

from server.condition_teacher import (
    ConditionAssessment,
    ConditionCropCandidate,
    _condition_prompt,
    condition_crop_stats,
    parse_condition_assessment,
    select_condition_crop_candidates,
)
from server.sample_payloads import build_sample_payload


def _write_image(path: Path, value: int = 128, shape: tuple[int, int, int] = (32, 40, 3)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.full(shape, value, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    path.write_bytes(encoded.tobytes())


class ConditionTeacherTests(unittest.TestCase):
    def test_condition_prompt_defines_composition_and_damage_labels(self) -> None:
        prompt = _condition_prompt(80, 60)

        self.assertIn("single_part", prompt)
        self.assertIn("compound_part", prompt)
        self.assertIn("multi_part", prompt)
        self.assertIn("second part peeking out", prompt)
        self.assertIn("chewed marks", prompt)
        self.assertIn("trash_candidate", prompt)
        self.assertIn("Transparent or translucent parts", prompt)

    def test_parse_condition_assessment_normalizes_aliases_and_flags(self) -> None:
        assessment = parse_condition_assessment(
            {
                "composition": "multiple parts",
                "condition": "trash",
                "part_count_estimate": 3,
                "flags": {"dirty": True},
                "issues": ["bite marks", "", "cracked edge"],
                "visible_evidence": "Several separable pieces are visible.",
                "confidence": 1.7,
            },
            model="google/gemini-3.1-flash-lite-preview",
        )

        self.assertEqual("multi_part", assessment.composition)
        self.assertEqual("trash_candidate", assessment.condition)
        self.assertTrue(assessment.multiple_parts)
        self.assertTrue(assessment.dirty)
        self.assertTrue(assessment.damaged)
        self.assertTrue(assessment.trash_candidate)
        self.assertEqual(("bite marks", "cracked edge"), assessment.issues)
        self.assertEqual(1.0, assessment.confidence)

    def test_select_condition_crop_candidates_skips_existing_and_black_crops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root / "aaaaaaaaaaaa" / "seg0" / "wedge_000.jpg"
            black = root / "bbbbbbbbbbbb" / "seg0" / "wedge_000.jpg"
            _write_image(good, value=120)
            _write_image(black, value=0)

            skipped = select_condition_crop_candidates(
                limit=5,
                piece_crops_root=root,
                existing_source_keys={"piece_crops/aaaaaaaaaaaa/seg0/wedge_000.jpg"},
            )
            forced = select_condition_crop_candidates(
                limit=5,
                piece_crops_root=root,
                existing_source_keys={"piece_crops/aaaaaaaaaaaa/seg0/wedge_000.jpg"},
                force=True,
            )

        self.assertEqual([], skipped)
        self.assertEqual(1, len(forced))
        self.assertEqual("aaaaaaaaaaaa", forced[0].piece_uuid)

    def test_select_condition_crop_candidates_respects_time_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "aaaaaaaaaaaa" / "seg0" / "wedge_000.jpg"
            new = root / "bbbbbbbbbbbb" / "seg0" / "wedge_000.jpg"
            _write_image(old, value=120)
            _write_image(new, value=130)
            now = time.time()
            os.utime(old, (now - 3600, now - 3600))
            os.utime(new, (now, now))

            selected = select_condition_crop_candidates(
                limit=5,
                piece_crops_root=root,
                since_ts=now - 60,
            )

        self.assertEqual(1, len(selected))
        self.assertEqual("bbbbbbbbbbbb", selected[0].piece_uuid)

    def test_build_sample_payload_adds_condition_analysis(self) -> None:
        assessment = ConditionAssessment(
            model="google/gemini-3.1-flash-lite-preview",
            composition="single_part",
            condition="minor_wear",
            confidence=0.82,
            part_count_estimate=1,
            single_part=True,
            compound_part=False,
            multiple_parts=False,
            clean=True,
            dirty=False,
            damaged=False,
            trash_candidate=False,
            issues=("light scratches",),
            visible_evidence="One visible part with light surface scratches.",
            raw_payload={"composition": "single_part"},
        )
        payload = build_sample_payload(
            session_id="session-1",
            sample_id="sample-1",
            session_name="Condition samples",
            metadata={
                "source": "piece_condition_teacher_capture",
                "source_role": "piece_crop",
                "capture_reason": "piece_condition_teacher",
                "condition_sample": True,
                "condition_source_crop_path": "piece_crops/piece-a/seg0/wedge_000.jpg",
                "condition_assessment": assessment.to_metadata(),
            },
        )

        self.assertEqual("condition", payload["sample"]["capture_scope"])
        analyses = payload["analyses"]
        self.assertEqual(1, len(analyses))
        self.assertEqual("condition", analyses[0]["kind"])
        self.assertEqual("part_condition_quality", analyses[0]["stage"])
        self.assertEqual("single_part", analyses[0]["outputs"]["composition"])
        self.assertEqual("minor_wear", analyses[0]["outputs"]["condition"])
        self.assertEqual(
            "piece_crops/piece-a/seg0/wedge_000.jpg",
            payload["provenance"]["condition_sample"]["condition_source_crop_path"],
        )


class _FakeHive:
    def __init__(self) -> None:
        self.queued: list[dict] = []

    def enqueue(self, **kwargs):
        self.queued.append(kwargs)
        return 1


class ConditionSampleArchiveTests(unittest.TestCase):
    def test_save_condition_assessment_capture_archives_crop_only_sample(self) -> None:
        from server import classification_training as training_module

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = root / "condition-session"
            for relative in ("captures", "metadata", "dataset/images", "classification/json"):
                (session_dir / relative).mkdir(parents=True, exist_ok=True)

            source_crop = root / "piece_crops" / "piece-a" / "seg0" / "wedge_000.jpg"
            _write_image(source_crop, value=140)
            candidate = ConditionCropCandidate(
                piece_uuid="piece-a",
                path=source_crop,
                relative_path="piece_crops/piece-a/seg0/wedge_000.jpg",
                segment_sequence=0,
                kind="wedge",
                crop_index=0,
                stats=condition_crop_stats(source_crop),
            )
            assessment = ConditionAssessment(
                model="google/gemini-3.1-flash-lite-preview",
                composition="single_part",
                condition="clean_ok",
                confidence=0.9,
                part_count_estimate=1,
                single_part=True,
                compound_part=False,
                multiple_parts=False,
                clean=True,
                dirty=False,
                damaged=False,
                trash_candidate=False,
                issues=(),
                visible_evidence="One clean LEGO piece is visible.",
                raw_payload={"composition": "single_part"},
            )

            manager = training_module.ClassificationTrainingManager.__new__(
                training_module.ClassificationTrainingManager
            )
            manager._lock = threading.Lock()
            manager._processor = training_module.DEFAULT_PROCESSOR
            manager._session_id = "condition-session"
            manager._session_name = "Condition samples"
            manager._session_dir = session_dir
            manager._created_at = 1.0
            manager._hive = _FakeHive()

            result = manager.saveConditionAssessmentCapture(
                candidate=candidate,
                assessment=assessment,
            )
            metadata_path = session_dir / "metadata" / f"{result['sample_id']}.json"
            metadata = json.loads(metadata_path.read_text())
            input_image_exists = Path(metadata["input_image"]).is_file()

        self.assertEqual("piece_condition_teacher_capture", metadata["source"])
        self.assertEqual("condition", metadata["detection_scope"])
        self.assertEqual("piece-a", metadata["piece_uuid"])
        self.assertTrue(input_image_exists)
        self.assertEqual("condition", metadata["sample_payload"]["sample"]["capture_scope"])
        self.assertEqual("condition", metadata["sample_payload"]["analyses"][0]["kind"])
        self.assertEqual(1, len(manager._hive.queued))
        self.assertEqual(result["sample_id"], manager._hive.queued[0]["sample_id"])


if __name__ == "__main__":
    unittest.main()
