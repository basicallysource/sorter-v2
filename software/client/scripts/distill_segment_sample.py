from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from openai import OpenAI
from PIL import Image
from sam2.build_sam import build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor


GEMINI_OPENROUTER_MODEL = "google/gemini-3-flash-preview"
GEMINI_GOOGLE_MODEL = "gemini-2.5-flash"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_DEVICE = "cpu"
COLORS = [
    (0, 255, 0),
    (255, 0, 0),
    (0, 0, 255),
    (255, 255, 0),
    (255, 0, 255),
    (0, 255, 255),
    (128, 255, 0),
    (255, 128, 0),
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Gemini+SAM pseudo-labeling on a single image.")
    parser.add_argument("--input", required=True, help="Input image path")
    parser.add_argument("--result-json", required=True, help="Where to write the result JSON")
    parser.add_argument("--overlay-image", required=True, help="Where to write the rendered overlay JPG")
    parser.add_argument("--yolo-label", required=True, help="Where to write the YOLO segmentation label TXT")
    parser.add_argument(
        "--checkpoint",
        required=True,
        help="Path to the SAM2 checkpoint file",
    )
    parser.add_argument(
        "--device",
        default=DEFAULT_DEVICE,
        help="Torch device to use for SAM2",
    )
    return parser.parse_args()


def _sam_config_path() -> str:
    return "configs/sam2.1/sam2.1_hiera_s.yaml"


def _load_image(path: Path) -> tuple[Image.Image, np.ndarray]:
    pil_img = Image.open(path).convert("RGB")
    return pil_img, np.array(pil_img)


def _image_to_base64_jpeg(pil_img: Image.Image) -> str:
    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=95)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _openrouter_client() -> OpenAI:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")
    return OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)


def _google_gemini_request(prompt: str, image_b64: str) -> dict[str, Any]:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set.")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_GOOGLE_MODEL}:generateContent"
        f"?key={api_key}"
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google Gemini request failed: {exc.code} {detail}") from exc


def _gemini_prompt(width: int, height: int) -> str:
    return f"""You are annotating a cropped tray image from a LEGO sorter classification chamber.

Detect every distinct loose LEGO piece visible in the tray crop.

Rules:
- Detect each separate LEGO piece exactly once.
- Ignore tray walls, tray floor, reflections, highlights, screws, printed markers, and static hardware.
- Ignore shadows unless they are part of the piece body.
- Return tight boxes around the actual piece extents.
- If no pieces are visible, return an empty detections array.

Return ONLY valid JSON, no markdown:
{{"detections":[{{"description":"brief piece description","bbox":[y_min,x_min,y_max,x_max],"confidence":0.0-1.0}}]}}

Coordinates must use a 0-1000 normalized scale for this {width}x{height} image."""


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise RuntimeError("Model response did not contain JSON.")
    return json.loads(match.group())


def _extract_google_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates", [])
    if not candidates:
        raise RuntimeError("Google Gemini response contained no candidates.")
    parts = candidates[0].get("content", {}).get("parts", [])
    text_parts = [part.get("text", "") for part in parts if isinstance(part.get("text"), str)]
    text = "".join(text_parts).strip()
    if not text:
        raise RuntimeError("Google Gemini response did not contain text content.")
    return text


def _get_gemini_detections(width: int, height: int, image_b64: str) -> tuple[list[dict[str, Any]], str]:
    prompt = _gemini_prompt(width, height)
    payload: dict[str, Any]
    model_label: str
    google_api_key = os.getenv("GOOGLE_API_KEY")
    if google_api_key:
        try:
            payload = _extract_json(_extract_google_text(_google_gemini_request(prompt, image_b64)))
            model_label = GEMINI_GOOGLE_MODEL
        except Exception:
            client = _openrouter_client()
            response = client.chat.completions.create(
                model=GEMINI_OPENROUTER_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                        ],
                    }
                ],
                temperature=0.1,
                max_tokens=3000,
            )
            payload = _extract_json(response.choices[0].message.content.strip())
            model_label = GEMINI_OPENROUTER_MODEL
    else:
        client = _openrouter_client()
        response = client.chat.completions.create(
            model=GEMINI_OPENROUTER_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    ],
                }
            ],
            temperature=0.1,
            max_tokens=3000,
        )
        payload = _extract_json(response.choices[0].message.content.strip())
        model_label = GEMINI_OPENROUTER_MODEL

    detections = payload.get("detections", [])
    sx = width / 1000.0
    sy = height / 1000.0
    result: list[dict[str, Any]] = []
    for det in detections:
        bbox = det.get("bbox", [0, 0, 0, 0])
        try:
            y1_n, x1_n, y2_n, x2_n = [float(v) for v in bbox[:4]]
        except (TypeError, ValueError):
            continue
        x1 = int(max(0.0, min(1000.0, x1_n)) * sx)
        y1 = int(max(0.0, min(1000.0, y1_n)) * sy)
        x2 = int(max(0.0, min(1000.0, x2_n)) * sx)
        y2 = int(max(0.0, min(1000.0, y2_n)) * sy)
        if x2 <= x1 or y2 <= y1:
            continue
        result.append(
            {
                "description": str(det.get("description", "piece")).strip() or "piece",
                "bbox": [x1, y1, x2, y2],
                "confidence": float(det.get("confidence", 0.5)),
            }
        )
    return result, model_label


def _get_gemini_detections_legacy(client: OpenAI, image_path: Path, width: int, height: int) -> list[dict[str, Any]]:
    pil_img = Image.open(image_path).convert("RGB")
    img_b64 = _image_to_base64_jpeg(pil_img)
    response = client.chat.completions.create(
        model=GEMINI_OPENROUTER_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _gemini_prompt(width, height)},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                ],
            }
        ],
        temperature=0.1,
        max_tokens=3000,
    )
    payload = _extract_json(response.choices[0].message.content.strip())
    return payload.get("detections", [])


def _load_predictor(checkpoint_path: Path, device: str) -> SAM2ImagePredictor:
    model = build_sam2(_sam_config_path(), str(checkpoint_path), device=device)
    return SAM2ImagePredictor(model)


def _segment(predictor: SAM2ImagePredictor, image_rgb: np.ndarray, boxes: list[list[int]]) -> list[np.ndarray]:
    predictor.set_image(image_rgb)
    masks_out: list[np.ndarray] = []
    for box in np.array(boxes, dtype=np.float32):
        masks, scores, _ = predictor.predict(box=box, multimask_output=True)
        best_idx = int(np.argmax(scores))
        masks_out.append(masks[best_idx])
    return masks_out


def _largest_polygon(mask: np.ndarray) -> list[list[int]]:
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    contour = max(contours, key=cv2.contourArea)
    epsilon = 0.005 * cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
    if len(approx) < 3:
        return []
    return [[int(x), int(y)] for x, y in approx]


def _write_overlay(image_rgb: np.ndarray, detections: list[dict[str, Any]], masks: list[np.ndarray], output_path: Path) -> None:
    vis = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
    overlay = vis.copy()
    for index, (det, mask) in enumerate(zip(detections, masks)):
        color = COLORS[index % len(COLORS)]
        mask_bool = mask.astype(bool)
        overlay[mask_bool] = color
        contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(vis, contours, -1, color, 2)
        x1, y1, x2, y2 = det["bbox"]
        cv2.rectangle(vis, (x1, y1), (x2, y2), color, 1)
        label = f"{det['description'][:28]} {det['confidence']:.2f}"
        cv2.putText(
            vis,
            label,
            (x1, max(y1 - 8, 15)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            2,
        )
    blended = cv2.addWeighted(overlay, 0.35, vis, 0.65, 0)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), blended)


def _write_yolo_label(image_rgb: np.ndarray, detections: list[dict[str, Any]], output_path: Path) -> None:
    height, width = image_rgb.shape[:2]
    lines: list[str] = []
    for det in detections:
        polygon = det.get("polygon", [])
        if len(polygon) < 3:
            continue
        coords: list[str] = []
        for x, y in polygon:
            coords.append(f"{x / width:.6f}")
            coords.append(f"{y / height:.6f}")
        lines.append("0 " + " ".join(coords))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines))


def main() -> int:
    args = _parse_args()
    image_path = Path(args.input).resolve()
    result_json = Path(args.result_json).resolve()
    overlay_image = Path(args.overlay_image).resolve()
    yolo_label = Path(args.yolo_label).resolve()
    checkpoint_path = Path(args.checkpoint).resolve()

    pil_img, image_rgb = _load_image(image_path)
    width, height = pil_img.size

    image_b64 = _image_to_base64_jpeg(pil_img)
    detections, model_name = _get_gemini_detections(width, height, image_b64)

    predictor = _load_predictor(checkpoint_path, args.device)
    masks: list[np.ndarray] = _segment(predictor, image_rgb, [det["bbox"] for det in detections]) if detections else []

    results: list[dict[str, Any]] = []
    for det, mask in zip(detections, masks):
        polygon = _largest_polygon(mask)
        results.append(
            {
                "description": det["description"],
                "bbox": det["bbox"],
                "confidence": det["confidence"],
                "polygon": polygon,
                "mask_area": int(np.count_nonzero(mask)),
            }
        )

    _write_overlay(image_rgb, results, masks, overlay_image)
    _write_yolo_label(image_rgb, results, yolo_label)

    payload = {
        "ok": True,
        "image": str(image_path),
        "width": width,
        "height": height,
        "model": model_name,
        "detections": results,
    }
    result_json.parent.mkdir(parents=True, exist_ok=True)
    result_json.write_text(json.dumps(payload, indent=2))
    print(json.dumps({"ok": True, "detections": len(results), "result_json": str(result_json)}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        raise
