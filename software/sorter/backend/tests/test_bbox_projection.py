import unittest

from subsystems.classification.bbox_projection import (
    translate_bbox_to_crop,
    translate_bboxes_to_crop,
)


class BboxProjectionTests(unittest.TestCase):
    def test_translate_bbox_to_crop_offsets_into_crop_space(self) -> None:
        bbox = (936, 1135, 1157, 1217)
        crop_bbox = (540, 472, 1555, 1695)

        translated = translate_bbox_to_crop(bbox, crop_bbox)

        self.assertEqual((396, 663, 617, 745), translated)

    def test_translate_bbox_to_crop_clips_and_drops_invalid_boxes(self) -> None:
        crop_bbox = (100, 200, 400, 500)

        self.assertEqual((0, 0, 20, 30), translate_bbox_to_crop((80, 180, 120, 230), crop_bbox))
        self.assertIsNone(translate_bbox_to_crop((10, 20, 20, 30), crop_bbox))

    def test_translate_bboxes_to_crop_filters_empty_results(self) -> None:
        crop_bbox = (100, 200, 400, 500)

        translated = translate_bboxes_to_crop(
            [
                (120, 210, 180, 260),
                (0, 0, 50, 50),
            ],
            crop_bbox,
        )

        self.assertEqual([(20, 10, 80, 60)], translated)


if __name__ == "__main__":
    unittest.main()
