"""LLM-guided camera calibration loop via OpenRouter.

Agentic chat-completion loop: the model sees each cropped working-zone
frame + its own earlier reasoning + applied changes, and calls
``apply_camera_settings`` / ``finish_calibration`` tools in turn. The
loop tracks the best-scoring settings so a non-converged run still
returns the highest-quality frame seen.

Also owns:

- the reference-image cache (``llm_calibration_reference_image_b64``);
- the small OpenRouter-JSON extraction + chat-content helpers used both
  inside the loop and by ``run_llm_final_review``;
- the post-calibration sign-off review that asks the model to approve or
  flag concerns on the final CCM-corrected frame.

Frame capture + dashboard crop still live in the router (they need the
Android-camera HTTP bridge + the ``preview_camera_device_settings``
endpoint); both are injected as keyword-only ``Callable`` parameters so
the service stays router-agnostic.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List

import cv2
import numpy as np
from fastapi import HTTPException

from irl.config import cameraDeviceSettingsToDict, parseCameraDeviceSettings
from server.services.camera_calibration.common import (
    CALIBRATION_METHOD_LLM_GUIDED,
    as_number,
    calibration_selection_value,
    camera_calibration_allowed_controls,
    camera_calibration_analysis_summary,
    clamp_control,
    compute_calibration_neutral_baseline,
)

_LOG = logging.getLogger(__name__)


DEFAULT_LLM_CALIBRATION_MODEL = "google/gemini-3.1-pro-preview"
DEFAULT_LLM_CALIBRATION_MAX_ITERATIONS = 10


# ---------------------------------------------------------------------------
# Input normalisation
# ---------------------------------------------------------------------------


def normalize_llm_calibration_model(value: str | None) -> str:
    try:
        from vision.gemini_sam_detector import SUPPORTED_OPENROUTER_MODELS
    except Exception:
        return DEFAULT_LLM_CALIBRATION_MODEL
    if isinstance(value, str):
        normalized = value.strip()
        if normalized in SUPPORTED_OPENROUTER_MODELS:
            return normalized
    return DEFAULT_LLM_CALIBRATION_MODEL


def normalize_llm_calibration_iterations(value: int | None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_LLM_CALIBRATION_MAX_ITERATIONS
    # Hard ceiling at 10 — beyond that we're wasting tokens. Model is
    # expected to return status="done" as soon as exposure looks clean.
    return max(2, min(10, int(value)))


# ---------------------------------------------------------------------------
# OpenRouter chat helpers
# ---------------------------------------------------------------------------


def extract_openrouter_json(text: str) -> Dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        excerpt = re.sub(r"\s+", " ", text or "").strip()
        if len(excerpt) > 220:
            excerpt = excerpt[:217] + "..."
        raise RuntimeError(
            "Model response did not contain JSON."
            + (f" Response excerpt: {excerpt}" if excerpt else "")
        )
    raw = match.group()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
        parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise RuntimeError("Model response did not contain a JSON object.")
    return parsed


def openrouter_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                text_parts.append(str(item["text"]))
        return "\n".join(text_parts)
    return str(content or "")


def frame_to_openrouter_jpeg(frame: np.ndarray, *, quality: int = 88) -> str:
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("Failed to encode calibration frame for OpenRouter.")
    return base64.b64encode(encoded.tobytes()).decode("ascii")


@lru_cache(maxsize=1)
def llm_calibration_reference_image_b64() -> str | None:
    reference_path = (
        Path(__file__).resolve().parents[4]
        / "frontend"
        / "static"
        / "setup"
        / "color-checker-reference.png"
    )
    if not reference_path.exists():
        return None
    try:
        return base64.b64encode(reference_path.read_bytes()).decode("ascii")
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Tool schema seen by the model during the loop
# ---------------------------------------------------------------------------


LLM_CALIBRATION_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "apply_camera_settings",
            "description": (
                "Apply one or more camera setting changes and capture a fresh frame "
                "for review. The system replies with the new frame and analyzer numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Short sentence explaining why these changes are being made.",
                    },
                    "changes": {
                        "type": "array",
                        "description": "List of setting changes to apply (max 3 per call).",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {
                                    "type": "string",
                                    "description": "Setting key from the allowed_controls list.",
                                },
                                "value": {
                                    "description": "New value (number, boolean, or enum string per the control's kind).",
                                },
                                "reason": {
                                    "type": "string",
                                    "description": "Why this specific change.",
                                },
                            },
                            "required": ["key", "value"],
                        },
                    },
                },
                "required": ["changes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_calibration",
            "description": (
                "Call this when exposure is clean (white patch ~235-245, black ~15-30, "
                "no clipping) and you are satisfied with the result. Ends the loop."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Short sentence describing the final state.",
                    },
                },
                "required": ["summary"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def build_llm_calibration_system_prompt(
    *,
    role: str,
    provider: str,
    max_iterations: int,
    allowed_controls: Dict[str, Any],
    baseline_reset_keys: List[str] | None = None,
) -> str:
    baseline_note = ""
    if baseline_reset_keys:
        baseline_note = (
            "\nBefore your first iteration, the system reset these post-processing controls to firmware defaults: "
            + ", ".join(sorted(baseline_reset_keys))
            + ". Prefer exposure/gain first — but if the defaults look clearly wrong, you MAY re-tune them.\n"
        )
    return (
        "You are an iterative camera calibration agent for a sorting machine.\n"
        "You will see a sequence of frames from the camera, each cropped to the working zone. "
        "The scene ideally contains a 6-color LEGO calibration plate (white, black, blue, red, green, yellow). "
        "You also have a clean reference image of the intended plate appearance.\n\n"
        "YOUR JOB:\n"
        "- AFTER your tuning, the system applies a per-camera color correction matrix (CCM) + gamma profile "
        "derived from the calibration plate. That stage handles fine color accuracy and WB neutrality.\n"
        "- Your PRIMARY focus: deliver a CLEAN, WELL-EXPOSED RAW SIGNAL — exposure (exposure_time / exposure_compensation), "
        "gain / ISO, brightness as fallback.\n"
        "- SECONDARY: if the raw image is clearly unusable (colors indistinguishable, extreme cast, crushed contrast), "
        "you MAY tune saturation, contrast, sharpness, gamma, or white balance — small, conservative nudges.\n"
        "- Do NOT fuss over small color/WB drift — the CCM cleans that up.\n\n"
        "EXPOSURE PRIORITY:\n"
        "- Aim for white patch ~235–245 (NEVER clip), black patch ~15–30 (don't crush).\n"
        "- If `clipped_white_fraction` > 0.02, lower exposure/gain immediately.\n"
        "- When unsure between brighter and darker, choose darker.\n\n"
        "TOOL USE (you MUST use tools — do not reply with plain text):\n"
        "- Call `apply_camera_settings` to change settings — you'll get the new frame back as a follow-up user message.\n"
        "- Call `finish_calibration` as soon as exposure is clean. Do NOT keep tweaking for cosmetic gains.\n"
        f"- Maximum {max_iterations} `apply_camera_settings` calls before the loop force-stops.\n"
        "- Each call: at most 3 changes, only keys from `allowed_controls`, exact enum values for enum controls.\n"
        "- Avoid oscillation: don't undo a previous change unless the new image clearly demands it.\n\n"
        f"Camera role: {role}\n"
        f"Provider: {provider}\n"
        f"Max iterations: {max_iterations}\n"
        f"{baseline_note}"
        f"\nAllowed controls:\n{json.dumps(allowed_controls, indent=2, sort_keys=True)}"
    )


def build_llm_calibration_user_text(
    *,
    iteration: int,
    max_iterations: int,
    current_settings: Dict[str, Any],
    analysis_summary: Dict[str, Any],
    is_initial: bool,
) -> str:
    header = (
        "First frame for calibration. Cropped working-zone view + clean reference image attached."
        if is_initial
        else f"Frame after iteration {iteration - 1}."
    )
    return (
        f"{header}\n"
        f"Iteration {iteration} of {max_iterations}.\n\n"
        f"Current device settings:\n{json.dumps(current_settings, indent=2, sort_keys=True)}\n\n"
        f"Analyzer summary:\n{json.dumps(analysis_summary, indent=2, sort_keys=True)}\n\n"
        "Either call `apply_camera_settings` with the next changes or `finish_calibration` if exposure is clean."
    )


def build_llm_final_review_prompt(
    *,
    role: str,
    final_settings: Dict[str, Any],
    profile_present: bool,
    last_loop_summary: str,
) -> str:
    profile_note = (
        "A per-camera color correction matrix (CCM) and gamma profile derived from the calibration plate "
        "have just been applied to the image you are reviewing."
        if profile_present
        else "No new color profile was generated — the image you are reviewing only reflects the LLM-tuned device settings."
    )
    summary_note = f"Loop summary so far: {last_loop_summary}\n" if last_loop_summary else ""
    return (
        "You are signing off on a finished camera calibration for a sorting machine.\n\n"
        "WHAT HAPPENED:\n"
        "- The LLM tuning loop finished adjusting exposure / gain / processing controls.\n"
        f"- {profile_note}\n"
        f"{summary_note}"
        "\nWHAT TO CHECK in the final image (cropped to the working zone):\n"
        "- Exposure: white patch around 235–245, no clipping; black patch around 15–30, not crushed.\n"
        "- Color separation: red, green, blue, yellow patches are clearly distinct after CCM.\n"
        "- White balance: white patch looks neutral (no obvious blue/yellow/green cast).\n"
        "- Overall: image looks usable for color-based piece sorting.\n\n"
        f"Final device settings:\n{json.dumps(final_settings, indent=2, sort_keys=True)}\n\n"
        "Return ONLY valid JSON with this exact shape:\n"
        '{"status":"approved|concerns","summary":"one short sentence","concerns":["short bullet","..."]}\n\n'
        "Rules:\n"
        "- Use status \"approved\" if the image is good enough for downstream sorting.\n"
        "- Use status \"concerns\" if real issues remain — list them in concerns[] (max 3, short phrases).\n"
        "- Do NOT propose new setting changes — calibration is finished.\n"
        "- No markdown, no code fences, no prose outside the JSON object."
    )


# ---------------------------------------------------------------------------
# One-shot OpenRouter advisor call (used by the final-review step)
# ---------------------------------------------------------------------------


def call_openrouter_calibration_advisor(
    prompt: str,
    image_b64: str,
    *,
    model: str,
    reference_image_b64: str | None = None,
) -> Dict[str, Any]:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="OpenRouter API key is not configured for LLM-guided calibration.",
        )
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"openai package is required for LLM-guided calibration: {exc}",
        )

    from vision.gemini_sam_detector import OPENROUTER_BASE_URL

    client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    content: List[Dict[str, Any]] = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
    ]
    if reference_image_b64:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{reference_image_b64}"},
            }
        )

    model_name = normalize_llm_calibration_model(model)
    last_error: Exception | None = None
    last_text = ""

    base_messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "Return only a valid JSON object. "
                "Do not include markdown, explanation, code fences, or any text before or after the JSON."
            ),
        },
        {
            "role": "user",
            "content": content,
        },
    ]

    retry_messages: List[Dict[str, Any]] = [
        *base_messages,
        {
            "role": "user",
            "content": (
                "Your previous reply was not valid JSON. "
                "Reply again using only a single raw JSON object with keys status, summary, and changes."
            ),
        },
    ]

    for messages in (base_messages, retry_messages):
        try:
            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=0.1,
                    max_tokens=1400,
                    timeout=25.0,
                    response_format={"type": "json_object"},
                )
            except Exception:
                # Fallback for providers that reject JSON mode but still support plain chat completions.
                response = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=0.1,
                    max_tokens=1400,
                    timeout=25.0,
                )

            last_text = openrouter_message_text(response.choices[0].message.content)
            return extract_openrouter_json(last_text)
        except Exception as exc:
            last_error = exc
            continue

    excerpt = re.sub(r"\s+", " ", last_text or "").strip()
    if len(excerpt) > 220:
        excerpt = excerpt[:217] + "..."
    if last_error is None:
        raise RuntimeError("OpenRouter calibration advisor failed without an error.")
    raise RuntimeError(
        f"OpenRouter calibration advisor failed after retry: {last_error}"
        + (f" Response excerpt: {excerpt}" if excerpt else "")
    )


# ---------------------------------------------------------------------------
# Apply advisor-suggested changes (coerce + clamp)
# ---------------------------------------------------------------------------


def _coerce_llm_boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
    return None


def apply_llm_calibration_changes(
    provider: str,
    current_settings: Dict[str, Any],
    current_response: Dict[str, Any],
    advisor_payload: Dict[str, Any],
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    next_settings = dict(current_settings)
    applied_changes: List[Dict[str, Any]] = []

    raw_changes = advisor_payload.get("changes")
    if not isinstance(raw_changes, list):
        settings_patch = advisor_payload.get("settings")
        if isinstance(settings_patch, dict):
            raw_changes = [{"key": key, "value": value} for key, value in settings_patch.items()]
        else:
            raw_changes = []

    if provider == "android-camera-app":
        capabilities = current_response.get("capabilities") if isinstance(current_response.get("capabilities"), dict) else {}
        for change in raw_changes:
            if not isinstance(change, dict) or not isinstance(change.get("key"), str):
                continue
            key = change["key"].strip()
            reason = str(change.get("reason") or "").strip()
            raw_value = change.get("value")
            if key == "exposure_compensation":
                if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float, str)):
                    continue
                try:
                    numeric = int(round(float(raw_value)))
                except (TypeError, ValueError):
                    continue
                exp_min = int(capabilities.get("exposure_compensation_min", numeric))
                exp_max = int(capabilities.get("exposure_compensation_max", numeric))
                coerced: Any = max(exp_min, min(exp_max, numeric))
            elif key == "white_balance_mode":
                allowed = {
                    str(mode)
                    for mode in capabilities.get("white_balance_modes", [])
                    if isinstance(mode, str) and mode
                }
                if not isinstance(raw_value, str) or raw_value not in allowed:
                    continue
                coerced = raw_value
            elif key == "processing_mode":
                allowed = {
                    str(mode)
                    for mode in capabilities.get("processing_modes", [])
                    if isinstance(mode, str) and mode
                }
                if not isinstance(raw_value, str) or raw_value not in allowed:
                    continue
                coerced = raw_value
            elif key == "ae_lock":
                if not bool(capabilities.get("supports_ae_lock")):
                    continue
                coerced = _coerce_llm_boolean(raw_value)
                if coerced is None:
                    continue
            elif key == "awb_lock":
                if not bool(capabilities.get("supports_awb_lock")):
                    continue
                coerced = _coerce_llm_boolean(raw_value)
                if coerced is None:
                    continue
            else:
                continue

            if next_settings.get(key) == coerced:
                continue
            next_settings[key] = coerced
            applied_changes.append({"key": key, "value": coerced, "reason": reason})
        return next_settings, applied_changes

    controls = current_response.get("controls")
    if not isinstance(controls, list):
        return next_settings, applied_changes
    controls_by_key = {
        str(control.get("key")): control
        for control in controls
        if isinstance(control, dict) and isinstance(control.get("key"), str)
    }

    for change in raw_changes:
        if not isinstance(change, dict) or not isinstance(change.get("key"), str):
            continue
        key = change["key"].strip()
        control = controls_by_key.get(key)
        if control is None:
            continue
        reason = str(change.get("reason") or "").strip()
        raw_value = change.get("value")
        if control.get("kind") == "boolean":
            coerced_bool = _coerce_llm_boolean(raw_value)
            if coerced_bool is None or next_settings.get(key) == coerced_bool:
                continue
            next_settings[key] = coerced_bool
            applied_changes.append({"key": key, "value": coerced_bool, "reason": reason})
            continue

        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float, str)):
            continue
        try:
            numeric = float(raw_value)
        except (TypeError, ValueError):
            continue
        coerced_numeric = clamp_control(numeric, control)
        step = as_number(control.get("step"))
        coerced_value: Any
        if step is not None and step >= 1:
            coerced_value = int(round(coerced_numeric))
        else:
            coerced_value = float(coerced_numeric)
        if next_settings.get(key) == coerced_value:
            continue
        next_settings[key] = coerced_value
        applied_changes.append({"key": key, "value": coerced_value, "reason": reason})

    return next_settings, applied_changes


# ---------------------------------------------------------------------------
# Types for injected router helpers
# ---------------------------------------------------------------------------


AnalyzeFrame = Callable[
    [str, int | str | None, Dict[str, Any]],
    tuple[Dict[str, Any], Dict[str, Any] | None, np.ndarray | None],
]
DashboardCropSpec = Callable[[str, int, int], Any]
ApplyDashboardCrop = Callable[[np.ndarray, Any], np.ndarray]
ReportProgress = Callable[[str, float, str, Dict[str, Any] | None], None]
ReportTrace = Callable[[List[Dict[str, Any]]], None]


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def calibrate_camera_device_settings_with_llm(
    role: str,
    provider: str,
    source: int | str | None,
    current_response: Dict[str, Any],
    *,
    openrouter_model: str,
    max_iterations: int,
    analyze_frame: AnalyzeFrame,
    dashboard_crop_spec: DashboardCropSpec,
    apply_dashboard_crop: ApplyDashboardCrop,
    report_progress: ReportProgress | None = None,
    report_trace: ReportTrace | None = None,
    gallery_dir: Path | None = None,
) -> tuple[Dict[str, Any], Dict[str, Any] | None, Dict[str, Any]]:
    """Agentic LLM calibration loop.

    Maintains a multi-turn chat with the model: each ``apply_camera_settings``
    tool call is followed by a tool reply + a fresh user message containing
    the new captured frame. The model sees the full conversation history
    (its own earlier reasoning, applied changes, and resulting frames) —
    not a text-summarized recap.
    """
    current_settings = (
        dict(current_response.get("settings"))
        if provider == "android-camera-app" and isinstance(current_response.get("settings"), dict)
        else cameraDeviceSettingsToDict(parseCameraDeviceSettings(current_response.get("settings")))
    )
    if not current_settings:
        current_settings = {}

    allowed_controls = camera_calibration_allowed_controls(provider, current_response)

    # Reset color/processing controls to firmware defaults so the LLM and
    # the downstream CCM start from a clean, neutral signal. Exposure/gain
    # controls are preserved (real sensor properties — let the LLM tune them).
    baseline_settings, reset_keys = compute_calibration_neutral_baseline(
        provider, current_response, current_settings
    )
    if reset_keys:
        _LOG.info(
            "LLM calibration: reset %d post-processing control(s) to firmware defaults: %s",
            len(reset_keys),
            ", ".join(sorted(reset_keys)),
        )

    history: List[Dict[str, Any]] = []
    active_settings = dict(baseline_settings)
    best_settings = dict(baseline_settings)
    best_analysis: Dict[str, Any] | None = None
    best_selection_value = float("-inf")
    last_summary = ""
    gallery_step = 0

    def _report(stage: str, progress: float, message: str, analysis: Dict[str, Any] | None = None) -> None:
        if report_progress is None:
            return
        report_progress(stage, max(0.0, min(0.9, float(progress))), message, analysis)

    def _save_gallery(
        frame: np.ndarray | None,
        stage: str,
        iteration: int,
        settings: Dict[str, Any],
        *,
        analysis: Dict[str, Any] | None = None,
        advisor_payload: Dict[str, Any] | None = None,
        summary: str | None = None,
    ) -> str | None:
        nonlocal gallery_step
        if gallery_dir is None or frame is None:
            return None
        gallery_step += 1
        prefix = f"step_{gallery_step:03d}_{stage}"
        image_name = f"{prefix}.jpg"
        ok = cv2.imwrite(str(gallery_dir / image_name), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            _LOG.warning("Failed to write calibration gallery frame %s", image_name)
            return None
        meta: Dict[str, Any] = {
            "stage": stage,
            "iteration": iteration,
            "step": gallery_step,
            "settings": settings,
        }
        if analysis is not None:
            meta["analysis"] = analysis
        if advisor_payload is not None:
            meta["advisor_payload"] = advisor_payload
        if summary:
            meta["summary"] = summary
        (gallery_dir / f"{prefix}.json").write_text(json.dumps(meta, indent=2, default=str))
        task_id = gallery_dir.name
        return f"/api/cameras/device-settings/{role}/calibrate-target/{task_id}/gallery/{image_name}"

    def _track_best(applied_settings: Dict[str, Any], analysis: Dict[str, Any] | None) -> None:
        nonlocal best_analysis, best_settings, best_selection_value
        if analysis is not None:
            sel = calibration_selection_value(analysis)
            if best_analysis is None or sel > best_selection_value:
                best_analysis = analysis
                best_settings = dict(applied_settings)
                best_selection_value = sel
        elif best_analysis is None:
            best_settings = dict(applied_settings)

    def _capture_review_frame(
        settings_to_apply: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Dict[str, Any] | None, np.ndarray]:
        applied_settings, analysis, frame = analyze_frame(role, source, settings_to_apply)
        if frame is None:
            raise HTTPException(
                status_code=400,
                detail="Could not capture a live frame for LLM-guided calibration.",
            )
        frame_h, frame_w = frame.shape[:2]
        crop_spec = dashboard_crop_spec(role, frame_w, frame_h)
        cropped_frame = apply_dashboard_crop(frame, crop_spec) if crop_spec else frame
        return applied_settings, analysis, cropped_frame

    # ----- One-time OpenAI client setup ----------------------------------
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="OpenRouter API key is not configured for LLM-guided calibration.",
        )
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - runtime dependency guard
        raise HTTPException(
            status_code=500,
            detail=f"openai package is required for LLM-guided calibration: {exc}",
        )
    from vision.gemini_sam_detector import OPENROUTER_BASE_URL

    client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    model_name = normalize_llm_calibration_model(openrouter_model)
    reference_image_b64 = llm_calibration_reference_image_b64()

    system_prompt = build_llm_calibration_system_prompt(
        role=role,
        provider=provider,
        max_iterations=max_iterations,
        allowed_controls=allowed_controls,
        baseline_reset_keys=reset_keys,
    )
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    # ----- Initial frame -------------------------------------------------
    _report("llm_capture", 0.08, "Capturing initial frame for LLM review.", None)
    applied_settings, analysis, cropped_frame = _capture_review_frame(active_settings)
    _track_best(applied_settings, analysis)
    analysis_summary = camera_calibration_analysis_summary(analysis)
    iteration_index = 1
    input_frame_url = _save_gallery(
        cropped_frame, "llm_capture", iteration_index, applied_settings, analysis=analysis
    )

    initial_user_text = build_llm_calibration_user_text(
        iteration=iteration_index,
        max_iterations=max_iterations,
        current_settings=applied_settings,
        analysis_summary=analysis_summary,
        is_initial=True,
    )
    initial_content: List[Dict[str, Any]] = [
        {"type": "text", "text": initial_user_text},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{frame_to_openrouter_jpeg(cropped_frame)}"},
        },
    ]
    if reference_image_b64:
        initial_content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{reference_image_b64}"},
            }
        )
    messages.append({"role": "user", "content": initial_content})

    pending_entry: Dict[str, Any] = {
        "iteration": iteration_index,
        "status": "pending",
        "summary": "",
        "input": {
            "current_settings": dict(applied_settings),
            "analysis_summary": dict(analysis_summary),
            "reference_image_provided": reference_image_b64 is not None,
            "allowed_controls": dict(allowed_controls),
        },
        "response": None,
        "changes": [],
        "resulting_settings": dict(applied_settings),
        "analysis": analysis_summary,
        "input_image_url": input_frame_url,
    }
    history.append(pending_entry)
    if report_trace is not None:
        report_trace([dict(entry) for entry in history])

    done = False
    error_message: str | None = None
    safety_turn_cap = max_iterations + 4

    for _turn in range(safety_turn_cap):
        review_progress = 0.12 + (iteration_index / max_iterations) * 0.58
        _report(
            "llm_review",
            review_progress,
            f"LLM reviewing iteration {iteration_index} of {max_iterations}.",
            analysis,
        )

        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                tools=LLM_CALIBRATION_TOOLS,
                tool_choice="auto",
                temperature=0.1,
                max_tokens=1400,
                timeout=30.0,
            )
        except Exception as exc:
            error_message = f"OpenRouter call failed: {exc}"
            _LOG.warning("LLM calibration chat failed: %s", exc)
            history[-1] = {
                **history[-1],
                "status": "error",
                "summary": error_message,
                "response": {"error": str(exc)},
            }
            if report_trace is not None:
                report_trace([dict(entry) for entry in history])
            break

        msg = response.choices[0].message
        tool_calls = list(getattr(msg, "tool_calls", None) or [])
        text_reply = openrouter_message_text(getattr(msg, "content", None)).strip()

        assistant_entry: Dict[str, Any] = {
            "role": "assistant",
            "content": getattr(msg, "content", None) or "",
        }
        if tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "{}",
                    },
                }
                for tc in tool_calls
            ]
        messages.append(assistant_entry)

        if not tool_calls:
            summary_text = text_reply or "LLM ended calibration without using a tool."
            history[-1] = {
                **history[-1],
                "status": "done",
                "summary": summary_text,
                "response": {"text": text_reply},
            }
            if report_trace is not None:
                report_trace([dict(entry) for entry in history])
            _save_gallery(
                cropped_frame,
                "llm_review",
                iteration_index,
                applied_settings,
                analysis=analysis,
                summary=summary_text,
            )
            last_summary = summary_text
            break

        apply_handled_this_turn = False

        for tc in tool_calls:
            name = tc.function.name or ""
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if name == "finish_calibration":
                summary_text = str(args.get("summary") or "").strip() or "LLM signaled calibration complete."
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": "Calibration finished."}
                )
                history[-1] = {
                    **history[-1],
                    "status": "done",
                    "summary": summary_text,
                    "response": {"tool": name, "args": args},
                }
                if report_trace is not None:
                    report_trace([dict(entry) for entry in history])
                _save_gallery(
                    cropped_frame,
                    "llm_review",
                    iteration_index,
                    applied_settings,
                    analysis=analysis,
                    advisor_payload={"tool": name, "args": args},
                    summary=summary_text,
                )
                last_summary = summary_text
                done = True
                break

            if name == "apply_camera_settings":
                if apply_handled_this_turn:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": "Ignored: only one apply_camera_settings is honored per turn.",
                        }
                    )
                    continue

                summary_text = str(args.get("summary") or "").strip()
                advisor_payload_compat: Dict[str, Any] = {
                    "status": "continue",
                    "summary": summary_text,
                    "changes": args.get("changes") if isinstance(args.get("changes"), list) else [],
                }
                next_settings, applied_changes = apply_llm_calibration_changes(
                    provider,
                    dict(applied_settings),
                    current_response,
                    advisor_payload_compat,
                )

                history[-1] = {
                    **history[-1],
                    "status": "continue",
                    "summary": summary_text,
                    "response": {"tool": name, "args": args},
                    "changes": list(applied_changes),
                    "resulting_settings": dict(next_settings),
                }
                if report_trace is not None:
                    report_trace([dict(entry) for entry in history])
                _save_gallery(
                    cropped_frame,
                    "llm_review",
                    iteration_index,
                    applied_settings,
                    analysis=analysis,
                    advisor_payload=advisor_payload_compat,
                    summary=summary_text,
                )
                last_summary = summary_text or last_summary
                apply_handled_this_turn = True

                if not applied_changes:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": "No supported changes were applied. Verify keys/values against allowed_controls and try again, or call finish_calibration if exposure is acceptable.",
                        }
                    )
                    history[-1] = {**history[-1], "status": "done"}
                    if report_trace is not None:
                        report_trace([dict(entry) for entry in history])
                    done = True
                    break

                _report(
                    "llm_apply",
                    min(0.88, review_progress + 0.04),
                    f"Applying {len(applied_changes)} LLM-suggested change{'s' if len(applied_changes) != 1 else ''}.",
                    analysis,
                )
                active_settings = next_settings

                if iteration_index >= max_iterations:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": (
                                f"Settings applied. Iteration limit ({max_iterations}) reached — "
                                "calibration loop ending."
                            ),
                        }
                    )
                    best_settings = dict(best_settings if best_analysis is not None else active_settings)
                    done = True
                    break

                iteration_index += 1
                _report(
                    "llm_capture",
                    0.08 + ((iteration_index - 1) / max_iterations) * 0.55,
                    f"Capturing iteration {iteration_index} of {max_iterations} for LLM review.",
                    best_analysis,
                )

                applied_settings, analysis, cropped_frame = _capture_review_frame(active_settings)
                _track_best(applied_settings, analysis)
                analysis_summary = camera_calibration_analysis_summary(analysis)
                input_frame_url = _save_gallery(
                    cropped_frame,
                    "llm_capture",
                    iteration_index,
                    applied_settings,
                    analysis=analysis,
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": (
                            f"Applied {len(applied_changes)} change(s). New frame attached in next user message."
                        ),
                    }
                )

                followup_text = build_llm_calibration_user_text(
                    iteration=iteration_index,
                    max_iterations=max_iterations,
                    current_settings=applied_settings,
                    analysis_summary=analysis_summary,
                    is_initial=False,
                )
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": followup_text},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{frame_to_openrouter_jpeg(cropped_frame)}"
                                },
                            },
                        ],
                    }
                )

                pending_entry = {
                    "iteration": iteration_index,
                    "status": "pending",
                    "summary": "",
                    "input": {
                        "current_settings": dict(applied_settings),
                        "analysis_summary": dict(analysis_summary),
                        "reference_image_provided": reference_image_b64 is not None,
                        "allowed_controls": None,
                    },
                    "response": None,
                    "changes": [],
                    "resulting_settings": dict(applied_settings),
                    "analysis": analysis_summary,
                    "input_image_url": input_frame_url,
                }
                history.append(pending_entry)
                if report_trace is not None:
                    report_trace([dict(entry) for entry in history])
                continue

            # Unknown tool — reply and keep going
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": f"Unknown tool: {name}. Use apply_camera_settings or finish_calibration.",
                }
            )

        if done:
            break
        if not apply_handled_this_turn:
            # Only unknown/finish tools and we're not done — bail to avoid loops.
            break

    if not done and error_message is None and history and history[-1].get("status") == "pending":
        history[-1] = {
            **history[-1],
            "status": "done",
            "summary": history[-1].get("summary") or "Loop ended without explicit finish_calibration.",
        }
        if report_trace is not None:
            report_trace([dict(entry) for entry in history])

    best_settings = dict(best_settings if best_analysis is not None else active_settings)

    return best_settings, best_analysis, {
        "method": CALIBRATION_METHOD_LLM_GUIDED,
        "openrouter_model": openrouter_model,
        "max_iterations": max_iterations,
        "trace": history,
        "summary": last_summary,
    }


# ---------------------------------------------------------------------------
# Final review (post-CCM sign-off)
# ---------------------------------------------------------------------------


def run_llm_final_review(
    *,
    role: str,
    gallery_dir: Path | None,
    openrouter_model: str,
    final_frame: np.ndarray,
    final_settings: Dict[str, Any],
    profile_present: bool,
    last_loop_summary: str,
    next_iteration_index: int,
    advisor_history_step: int,
    dashboard_crop_spec: DashboardCropSpec,
    apply_dashboard_crop: ApplyDashboardCrop,
) -> Dict[str, Any]:
    """Send the CCM-corrected final frame back to the advisor for sign-off.

    Returns a trace entry dict suitable for appending to
    ``calibration_metadata["trace"]``. Never raises — failures are
    turned into a status="error" entry so the rest of the calibration
    result still ships.
    """
    frame_h, frame_w = final_frame.shape[:2]
    crop_spec = dashboard_crop_spec(role, frame_w, frame_h)
    cropped_frame = apply_dashboard_crop(final_frame, crop_spec) if crop_spec else final_frame

    image_url: str | None = None
    if gallery_dir is not None:
        prefix = f"step_{advisor_history_step:03d}_llm_final_review"
        image_name = f"{prefix}.jpg"
        ok = cv2.imwrite(str(gallery_dir / image_name), cropped_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            meta: Dict[str, Any] = {
                "stage": "llm_final_review",
                "iteration": next_iteration_index,
                "step": advisor_history_step,
                "settings": final_settings,
                "profile_present": profile_present,
            }
            (gallery_dir / f"{prefix}.json").write_text(json.dumps(meta, indent=2, default=str))
            task_id = gallery_dir.name
            image_url = f"/api/cameras/device-settings/{role}/calibrate-target/{task_id}/gallery/{image_name}"
        else:
            _LOG.warning("Failed to write final-review gallery frame %s", image_name)

    prompt = build_llm_final_review_prompt(
        role=role,
        final_settings=final_settings,
        profile_present=profile_present,
        last_loop_summary=last_loop_summary,
    )

    base_input = {
        "final_settings": dict(final_settings),
        "profile_present": profile_present,
        "loop_summary": last_loop_summary,
    }

    try:
        advisor_payload = call_openrouter_calibration_advisor(
            prompt,
            frame_to_openrouter_jpeg(cropped_frame),
            model=openrouter_model,
            reference_image_b64=llm_calibration_reference_image_b64(),
        )
    except Exception as exc:
        _LOG.warning("LLM final-review call failed: %s", exc)
        return {
            "iteration": next_iteration_index,
            "stage": "final_review",
            "status": "error",
            "summary": f"Final review skipped: {exc}",
            "input": base_input,
            "response": None,
            "changes": [],
            "input_image_url": image_url,
        }

    raw_status = str(advisor_payload.get("status") or "").strip().lower()
    raw_concerns = advisor_payload.get("concerns")
    if raw_status not in {"approved", "concerns"}:
        raw_status = "concerns" if isinstance(raw_concerns, list) and raw_concerns else "approved"
    summary_text = str(advisor_payload.get("summary") or "").strip()

    return {
        "iteration": next_iteration_index,
        "stage": "final_review",
        "status": raw_status,
        "summary": summary_text,
        "input": base_input,
        "response": dict(advisor_payload),
        "changes": [],
        "input_image_url": image_url,
    }


__all__ = [
    "DEFAULT_LLM_CALIBRATION_MAX_ITERATIONS",
    "DEFAULT_LLM_CALIBRATION_MODEL",
    "LLM_CALIBRATION_TOOLS",
    "apply_llm_calibration_changes",
    "build_llm_calibration_system_prompt",
    "build_llm_calibration_user_text",
    "build_llm_final_review_prompt",
    "calibrate_camera_device_settings_with_llm",
    "call_openrouter_calibration_advisor",
    "extract_openrouter_json",
    "frame_to_openrouter_jpeg",
    "llm_calibration_reference_image_b64",
    "normalize_llm_calibration_iterations",
    "normalize_llm_calibration_model",
    "openrouter_message_text",
    "run_llm_final_review",
]
