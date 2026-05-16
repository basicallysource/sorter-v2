from vision.gemini_sam_detector import _extract_json, _get_detections


def test_extract_json_salvages_valid_detections_from_malformed_response() -> None:
    raw = (
        '{"detections": ['
        '{"kind": "lego", "description": "red brick", "bbox": [28, 218, 150, 375], "confidence": 0.98}, '
        '{"kind": "lego", "description": "blue plate", "bbox": [73, 277, 160, 365], "confidence": 0.97}, '
        '{"point": {"kind": "lego", "description": "white other", "bbox": [828, 717, 897, 790], "confidence": 0.93}, '
        '{"kind": "lego", "description": "bad bbox", "bbox": {"810, "xmin": 217}, "confidence": 0.97}'
        "]}"
    )

    payload = _extract_json(raw)

    assert [
        detection["description"] for detection in payload["detections"]
    ] == ["red brick", "blue plate", "white other"]


def test_get_detections_accepts_salvaged_payload(monkeypatch) -> None:
    def fake_call_openrouter(prompt: str, image_b64: str, *, model: str):
        return _extract_json(
            '{"detections": ['
            '{"kind": "lego", "description": "red brick", "bbox": [100, 200, 300, 400], "confidence": 0.9}, '
            '{"point": {"kind": "foreign", "description": "metal screw", "bbox": [500, 600, 700, 800], "confidence": 0.8}'
            "]}"
        )

    monkeypatch.setattr("vision.gemini_sam_detector._call_openrouter", fake_call_openrouter)

    detections = _get_detections(
        1000,
        500,
        "unused",
        openrouter_model="google/gemini-3-flash-preview",
        zone="c_channel",
    )

    assert [
        detection["bbox"] for detection in detections
    ] == [(200, 50, 400, 150), (600, 250, 800, 350)]
