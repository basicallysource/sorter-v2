#!/usr/bin/env python3
"""Sweep classification-channel motion settings against live parts on C4.

This is a deliberately practical live-hardware tool:

1. Pause the machine so feeder/distribution automation cannot interfere.
2. For each speed/acceleration cell:
   - reverse a configurable number of pulses to reset the pile a bit
   - capture current C4 detections
   - execute one or more forward pulses with the test parameters
   - capture C4 detections again
   - greedily match before/after detections and summarize real motion
3. Write per-cell JSON, snapshots, and a CSV summary under /tmp.

The goal is not "perfect scientific tracking" but a repeatable matrix that
lets us answer questions like:
  - which settings actually move parts the furthest?
  - which settings move them consistently instead of just shuffling?
  - which settings lose detections or push parts toward the exit pile-up?
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import parse, request

DEFAULT_BASE = "http://127.0.0.1:8000"
OUT_ROOT = Path("/tmp/c4_motion_sweep")
STEPPER = "carousel"
BASE = DEFAULT_BASE
CAMERA_CONFIG_URL = f"{BASE}/api/cameras/config"
CAROUSEL_DETECT_URL = f"{BASE}/api/feeder/detect/carousel"
CAROUSEL_LIVE_URL = f"{BASE}/api/hardware-config/carousel/live"
PAUSE_URL = f"{BASE}/pause"
RESUME_URL = f"{BASE}/resume"
MOVE_URL = f"{BASE}/stepper/move-degrees"


@dataclass
class DetectionBox:
    bbox: tuple[int, int, int, int]
    cx: float
    cy: float
    angle_deg: float
    radius_px: float
    area_px: float


def _get_json(url: str) -> dict[str, Any]:
    with request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    full_url = url
    if params:
        full_url = f"{url}?{parse.urlencode(params)}"
    req = request.Request(full_url, method="POST")
    with request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _pause_machine() -> None:
    _post_json(PAUSE_URL)


def _resume_machine() -> None:
    _post_json(RESUME_URL)


def _wait_for_carousel_stop(timeout_s: float = 15.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last_payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_payload = _get_json(CAROUSEL_LIVE_URL)
        if bool(last_payload.get("stepper_stopped")):
            return last_payload
        time.sleep(0.05)
    raise TimeoutError("carousel stepper did not stop in time")


def _move_blocking(
    *,
    degrees: float,
    speed: int,
    min_speed: int | None,
    acceleration: int | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "stepper": STEPPER,
        "degrees": round(float(degrees), 6),
        "speed": int(speed),
    }
    if min_speed is not None and acceleration is not None:
        params["min_speed"] = int(min_speed)
        params["acceleration"] = int(acceleration)
    _post_json(MOVE_URL, params=params)
    return _wait_for_carousel_stop()


def _fetch_single_jpeg() -> bytes:
    try:
        from websockets.sync.client import connect  # type: ignore
    except Exception as exc:  # pragma: no cover — dev script only
        raise RuntimeError(
            "websockets package required — install via `uv add websockets`"
        ) from exc

    import json
    with request.urlopen(CAMERA_CONFIG_URL, timeout=10) as response:
        cfg = json.loads(response.read().decode("utf-8"))
    source = cfg.get("carousel")
    if not isinstance(source, int):
        raise RuntimeError(
            f"carousel camera is not a USB device (got {source!r}); cannot WS-fetch"
        )

    ws_url = BASE.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url}/ws/camera-preview/{source}"
    deadline = time.time() + 15.0
    with connect(ws_url, open_timeout=5.0) as ws:
        while time.time() < deadline:
            msg = ws.recv(timeout=5.0)
            if isinstance(msg, (bytes, bytearray)) and len(msg) > 0:
                return bytes(msg)
    raise RuntimeError(f"could not capture a JPEG from {ws_url}")


def _capture_snapshot(dest: Path) -> None:
    dest.write_bytes(_fetch_single_jpeg())


def _detect_current() -> dict[str, Any]:
    return _post_json(CAROUSEL_DETECT_URL)


def _normalize_angle_deg(value: float) -> float:
    while value <= -180.0:
        value += 360.0
    while value > 180.0:
        value -= 360.0
    return value


def _parse_boxes(payload: dict[str, Any]) -> tuple[list[DetectionBox], tuple[float, float]]:
    frame_resolution = payload.get("frame_resolution") or [1920, 1080]
    width = float(frame_resolution[0]) if len(frame_resolution) >= 2 else 1920.0
    height = float(frame_resolution[1]) if len(frame_resolution) >= 2 else 1080.0
    center_x = width / 2.0
    center_y = height / 2.0

    parsed: list[DetectionBox] = []
    for candidate in payload.get("candidate_bboxes") or []:
        if not isinstance(candidate, list) or len(candidate) < 4:
            continue
        x1, y1, x2, y2 = (int(candidate[0]), int(candidate[1]), int(candidate[2]), int(candidate[3]))
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        dx = cx - center_x
        dy = center_y - cy
        angle_deg = math.degrees(math.atan2(dy, dx))
        radius_px = math.hypot(dx, dy)
        area_px = max(1.0, float(max(1, x2 - x1) * max(1, y2 - y1)))
        parsed.append(
            DetectionBox(
                bbox=(x1, y1, x2, y2),
                cx=cx,
                cy=cy,
                angle_deg=angle_deg,
                radius_px=radius_px,
                area_px=area_px,
            )
        )
    return parsed, (center_x, center_y)


def _match_boxes(before: list[DetectionBox], after: list[DetectionBox]) -> list[dict[str, Any]]:
    if not before or not after:
        return []

    candidates: list[tuple[float, int, int]] = []
    for i, box_a in enumerate(before):
        for j, box_b in enumerate(after):
            angular_delta = _normalize_angle_deg(box_b.angle_deg - box_a.angle_deg)
            radial_delta = box_b.radius_px - box_a.radius_px
            area_ratio = box_b.area_px / max(box_a.area_px, 1.0)
            area_penalty = abs(math.log(max(area_ratio, 1e-6)))
            cost = (
                abs(angular_delta) * 3.0
                + abs(radial_delta) * 0.05
                + area_penalty * 25.0
            )
            candidates.append((cost, i, j))

    candidates.sort(key=lambda item: item[0])
    used_before: set[int] = set()
    used_after: set[int] = set()
    matches: list[dict[str, Any]] = []
    for cost, i, j in candidates:
        if i in used_before or j in used_after:
            continue
        box_a = before[i]
        box_b = after[j]
        angular_delta = _normalize_angle_deg(box_b.angle_deg - box_a.angle_deg)
        radial_delta = box_b.radius_px - box_a.radius_px
        area_ratio = box_b.area_px / max(box_a.area_px, 1.0)
        if abs(angular_delta) > 65.0:
            continue
        if abs(radial_delta) > 220.0:
            continue
        if area_ratio < 0.28 or area_ratio > 3.5:
            continue
        used_before.add(i)
        used_after.add(j)
        matches.append(
            {
                "before_index": i,
                "after_index": j,
                "cost": round(cost, 3),
                "angular_delta_deg": round(angular_delta, 3),
                "radial_delta_px": round(radial_delta, 3),
                "area_ratio": round(area_ratio, 3),
                "before_bbox": list(box_a.bbox),
                "after_bbox": list(box_b.bbox),
            }
        )
    return matches


def _safe_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(statistics.fmean(values), 3)


def _safe_median(values: list[float]) -> float | None:
    if not values:
        return None
    return round(statistics.median(values), 3)


def _safe_stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return round(statistics.pstdev(values), 3)


def _build_summary(
    before: list[DetectionBox],
    after: list[DetectionBox],
    matches: list[dict[str, Any]],
    *,
    before_position_deg: float | None,
    after_position_deg: float | None,
) -> dict[str, Any]:
    angular = [float(item["angular_delta_deg"]) for item in matches]
    radial = [float(item["radial_delta_px"]) for item in matches]
    moved = [value for value in angular if abs(value) >= 3.0]
    matched_ratio = (
        round(len(matches) / max(len(before), len(after), 1), 3)
        if before or after
        else 0.0
    )
    return {
        "count_before": len(before),
        "count_after": len(after),
        "matched_count": len(matches),
        "matched_ratio": matched_ratio,
        "angular_mean_deg": _safe_mean(angular),
        "angular_median_deg": _safe_median(angular),
        "angular_stdev_deg": _safe_stdev(angular),
        "radial_mean_px": _safe_mean(radial),
        "radial_median_px": _safe_median(radial),
        "moved_count_abs_ge_3deg": len(moved),
        "moved_ratio_abs_ge_3deg": round(len(moved) / max(len(matches), 1), 3),
        "before_position_degrees": before_position_deg,
        "after_position_degrees": after_position_deg,
        "position_delta_degrees": (
            round(after_position_deg - before_position_deg, 3)
            if before_position_deg is not None and after_position_deg is not None
            else None
        ),
    }


def _write_summary_csv(out_dir: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames = [
        "cell",
        "speed",
        "acceleration",
        "pulses",
        "count_before",
        "count_after",
        "matched_count",
        "matched_ratio",
        "angular_mean_deg",
        "angular_median_deg",
        "angular_stdev_deg",
        "radial_mean_px",
        "radial_median_px",
        "moved_count_abs_ge_3deg",
        "moved_ratio_abs_ge_3deg",
        "position_delta_degrees",
    ]
    with (out_dir / "summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name) for name in fieldnames})


def _parse_csv_ints(value: str) -> list[int | None]:
    parsed: list[int | None] = []
    for raw in value.split(","):
        token = raw.strip().lower()
        if not token:
            continue
        if token in {"none", "off", "hard"}:
            parsed.append(None)
        else:
            parsed.append(int(token))
    return parsed


def _run_cell(
    *,
    run_dir: Path,
    cell_id: str,
    speed: int,
    acceleration: int | None,
    args: argparse.Namespace,
) -> dict[str, Any]:
    cell_dir = run_dir / cell_id
    cell_dir.mkdir(parents=True, exist_ok=True)

    for reset_index in range(args.reset_pulses):
        _move_blocking(
            degrees=-args.stepper_deg,
            speed=args.reset_speed,
            min_speed=(args.reset_min_speed if args.reset_acceleration is not None else None),
            acceleration=args.reset_acceleration,
        )
        time.sleep(args.settle_ms / 1000.0)
        if args.reset_pause_ms > 0:
            time.sleep(args.reset_pause_ms / 1000.0)

    before_live = _get_json(CAROUSEL_LIVE_URL)
    before_payload = _detect_current()
    before_boxes, center = _parse_boxes(before_payload)
    _capture_snapshot(cell_dir / "before.jpg")

    for pulse_index in range(args.pulses_per_cell):
        _move_blocking(
            degrees=args.stepper_deg,
            speed=speed,
            min_speed=(args.min_speed if acceleration is not None else None),
            acceleration=acceleration,
        )
        time.sleep(args.settle_ms / 1000.0)
        if pulse_index + 1 < args.pulses_per_cell and args.inter_pulse_pause_ms > 0:
            time.sleep(args.inter_pulse_pause_ms / 1000.0)

    after_live = _get_json(CAROUSEL_LIVE_URL)
    after_payload = _detect_current()
    after_boxes, _ = _parse_boxes(after_payload)
    _capture_snapshot(cell_dir / "after.jpg")

    matches = _match_boxes(before_boxes, after_boxes)
    summary = _build_summary(
        before_boxes,
        after_boxes,
        matches,
        before_position_deg=(
            float(before_live["current_position_degrees"])
            if isinstance(before_live.get("current_position_degrees"), (int, float))
            else None
        ),
        after_position_deg=(
            float(after_live["current_position_degrees"])
            if isinstance(after_live.get("current_position_degrees"), (int, float))
            else None
        ),
    )

    payload = {
        "cell": cell_id,
        "speed": speed,
        "acceleration": acceleration,
        "min_speed": args.min_speed if acceleration is not None else None,
        "stepper_deg": args.stepper_deg,
        "pulses": args.pulses_per_cell,
        "center": {"x": center[0], "y": center[1]},
        "summary": summary,
        "matches": matches,
        "before": {
            "live": before_live,
            "detection": before_payload,
        },
        "after": {
            "live": after_live,
            "detection": after_payload,
        },
    }
    (cell_dir / "result.json").write_text(json.dumps(payload, indent=2))
    return {
        "cell": cell_id,
        "speed": speed,
        "acceleration": acceleration if acceleration is not None else "hard",
        "pulses": args.pulses_per_cell,
        **summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep live C4 motion settings.")
    parser.add_argument("--base-url", default=DEFAULT_BASE, help="Sorter backend base URL.")
    parser.add_argument("--run-id", default=time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--speeds", default="1800,2600,3600,5200")
    parser.add_argument("--accelerations", default="none,1100,2500,6000")
    parser.add_argument("--stepper-deg", type=float, default=112.5)
    parser.add_argument("--pulses-per-cell", type=int, default=1)
    parser.add_argument("--min-speed", type=int, default=16)
    parser.add_argument("--settle-ms", type=int, default=350)
    parser.add_argument("--inter-pulse-pause-ms", type=int, default=0)
    parser.add_argument("--reset-pulses", type=int, default=3)
    parser.add_argument("--reset-speed", type=int, default=5200)
    parser.add_argument("--reset-acceleration", type=int, default=6000)
    parser.add_argument("--reset-min-speed", type=int, default=16)
    parser.add_argument("--reset-pause-ms", type=int, default=120)
    parser.add_argument("--resume-after", action="store_true")
    parser.add_argument("--out-root", default=str(OUT_ROOT))
    args = parser.parse_args()

    global BASE, CAMERA_CONFIG_URL, CAROUSEL_DETECT_URL, CAROUSEL_LIVE_URL, PAUSE_URL, RESUME_URL, MOVE_URL
    BASE = args.base_url.rstrip("/")
    CAMERA_CONFIG_URL = f"{BASE}/api/cameras/config"
    CAROUSEL_DETECT_URL = f"{BASE}/api/feeder/detect/carousel"
    CAROUSEL_LIVE_URL = f"{BASE}/api/hardware-config/carousel/live"
    PAUSE_URL = f"{BASE}/pause"
    RESUME_URL = f"{BASE}/resume"
    MOVE_URL = f"{BASE}/stepper/move-degrees"

    speeds = [int(item.strip()) for item in args.speeds.split(",") if item.strip()]
    accelerations = _parse_csv_ints(args.accelerations)
    if not speeds:
        raise SystemExit("No speeds supplied.")
    if not accelerations:
        raise SystemExit("No accelerations supplied.")

    run_dir = Path(args.out_root) / f"run_{args.run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    params_path = run_dir / "params.json"
    params_path.write_text(
        json.dumps(
            {
                "run_id": args.run_id,
                "base_url": BASE,
                "speeds": speeds,
                "accelerations": accelerations,
                "stepper_deg": args.stepper_deg,
                "pulses_per_cell": args.pulses_per_cell,
                "min_speed": args.min_speed,
                "settle_ms": args.settle_ms,
                "inter_pulse_pause_ms": args.inter_pulse_pause_ms,
                "reset_pulses": args.reset_pulses,
                "reset_speed": args.reset_speed,
                "reset_acceleration": args.reset_acceleration,
                "reset_min_speed": args.reset_min_speed,
                "reset_pause_ms": args.reset_pause_ms,
            },
            indent=2,
        )
    )

    _pause_machine()
    _wait_for_carousel_stop()

    rows: list[dict[str, Any]] = []
    cell_index = 0
    try:
        for speed in speeds:
            for acceleration in accelerations:
                cell_index += 1
                accel_label = "hard" if acceleration is None else str(acceleration)
                cell_id = f"{cell_index:02d}_speed{speed}_accel{accel_label}"
                print(f"[{cell_id}] speed={speed} acceleration={accel_label}")
                row = _run_cell(
                    run_dir=run_dir,
                    cell_id=cell_id,
                    speed=speed,
                    acceleration=acceleration,
                    args=args,
                )
                rows.append(row)
                print(
                    "  matched=%d angular_mean=%s radial_mean=%s"
                    % (
                        row["matched_count"],
                        row["angular_mean_deg"],
                        row["radial_mean_px"],
                    )
                )
    finally:
        _pause_machine()
        if args.resume_after:
            _resume_machine()

    _write_summary_csv(run_dir, rows)
    (run_dir / "summary.json").write_text(json.dumps(rows, indent=2))
    print(f"\nWrote sweep results to {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
