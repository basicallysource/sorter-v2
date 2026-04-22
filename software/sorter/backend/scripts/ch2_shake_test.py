#!/usr/bin/env python3
"""c_channel_2 shake-test driver.

One invocation = one staged test run against a live sorter backend:

  1. pause machine (so the feeder state-machine can't fight us)
  2. snapshot "before"
  3. reverse by ``clump_output_deg`` → pieces pile up against the exit wall
  4. snapshot "clumped"
  5. forward by ``center_output_deg`` → neutral starting spread
  6. snapshot "start" + baseline detection
  7. shake pattern for ``shake_duration_s`` while sampling detections ~4 Hz
  8. snapshot "after" + final detection
  9. resume machine

Run outputs under ``/tmp/ch2_shake_tests/run_<id>/``:
  params.json, timeline.json, snap_{before,clumped,start,after}.jpg.

The index.html report is (re)built from every run directory on disk, so
you can add runs over time and always get a combined view.

Usage example (first symmetric baseline):

    uv run python scripts/ch2_shake_test.py \\
        --run-id 001 \\
        --pattern symmetric-hard \\
        --amplitude-output-deg 15 \\
        --speed-fwd 2000 --speed-rev 2000 \\
        --note "hard-stop symmetric baseline, mild amplitude"
"""
from __future__ import annotations

import argparse
import html
import json
import math
import statistics
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import requests

BASE = "http://localhost:8000"
OUT_ROOT = Path("/tmp/ch2_shake_tests")
GEAR = 130.0 / 12.0  # output wheel -> stepper shaft multiplier
# c_channel_2 runs 200 full steps × 8 microsteps per stepper rev — the
# /stepper/pulse endpoint's `speed` parameter is microsteps per second, so
# a pulse's travel distance in stepper-degrees is
#   duration_s * speed / MICROSTEPS_PER_STEPPER_DEG
STEPS_PER_REV = 200
MICROSTEPS = 8
MICROSTEPS_PER_STEPPER_REV = STEPS_PER_REV * MICROSTEPS  # 1600
MICROSTEPS_PER_STEPPER_DEG = MICROSTEPS_PER_STEPPER_REV / 360.0  # ≈ 4.444
DETECT_SAMPLE_PERIOD_S = 0.25


def _pulse_duration_ms_for_output_deg(output_deg: float, speed_usteps_per_s: int) -> int:
    stepper_deg = output_deg * GEAR
    microsteps = stepper_deg * MICROSTEPS_PER_STEPPER_DEG
    return max(40, int(round(microsteps / max(speed_usteps_per_s, 1) * 1000)))


@dataclass
class RunParams:
    run_id: str
    pattern: str
    amplitude_output_deg: float
    amplitude_rev_output_deg: float
    speed_fwd: int
    speed_rev: int
    cycle_fwd_ms: int
    cycle_rev_ms: int
    shake_duration_s: float
    clump_output_deg: float
    center_output_deg: float
    clump_speed: int
    center_speed: int
    note: str
    single_forward_output_deg: float
    single_forward_speed: int
    # Rest time between fwd/rev half-cycles (0 = back-to-back). Lets pieces
    # settle after an inertial slip before the next impulse.
    inter_pulse_pause_ms: int
    # Gentle pre-move before each main pulse to take up gear backlash — the
    # gear has a hair of play that slams into the far tooth when we launch
    # at 8000 sp from a dead stop. A slow tiny move "cuddles" into the
    # new-direction tooth first so the main pulse starts in contact.
    backlash_takeup_output_deg: float
    backlash_takeup_speed: int
    # When > 0, replace the static pause with a slow opposite-direction
    # drift that runs for the full inter_pulse_pause_ms window. That single
    # slow move also closes backlash gently (friction-coupled), so separate
    # backlash-takeup is not needed when active_pause_speed is set.
    active_pause_speed: int
    # --- dance-mode fields (only used when pattern starts with "dance") ---
    dance_mode: bool
    dance_amp_min: float
    dance_amp_max: float
    dance_speed_min: int
    dance_speed_max: int
    dance_balance_bound_deg: float
    dance_seed: int
    # --- ramp fields: drive each shake stroke with move-degrees+ramp instead
    # of constant-velocity pulse. Both must be set to enable ramped motion.
    ramp_min_speed: int  # 0 disables ramp
    ramp_acceleration: int  # 0 disables ramp


def _stepper_deg(output_deg: float) -> float:
    return output_deg * GEAR


def _move_blocking(
    stepper_deg: float,
    speed: int,
    timeout_s: float = 60.0,
    *,
    min_speed: int | None = None,
    acceleration: int | None = None,
) -> None:
    """POST /stepper/move-degrees and wait long enough for the stepper to
    finish. When ``min_speed`` and ``acceleration`` are both given, the
    firmware ramps from min_speed up to ``speed`` and back down (trapezoid
    profile). Falls back to hard-stop constant speed otherwise.
    """
    params: dict[str, Any] = {"stepper": "c_channel_2", "degrees": stepper_deg, "speed": speed}
    if min_speed is not None and acceleration is not None:
        params["min_speed"] = int(min_speed)
        params["acceleration"] = int(acceleration)
    deadline = time.monotonic() + timeout_s
    while True:
        resp = requests.post(f"{BASE}/stepper/move-degrees", params=params, timeout=10)
        if resp.status_code == 200:
            break
        if resp.status_code == 409 and time.monotonic() < deadline:
            time.sleep(0.1)
            continue
        resp.raise_for_status()
    # Estimate motion duration. Without a ramp the move is constant speed at
    # ``speed`` µsteps/s. With a ramp, average speed is (min+max)/2 across
    # the travel (trapezoid with short ramp shoulders); add a safety margin
    # because the firmware also spends time on the ramp itself.
    microsteps = abs(stepper_deg) * MICROSTEPS_PER_STEPPER_DEG
    if min_speed is not None and acceleration is not None:
        avg_speed = (min_speed + speed) / 2.0
        expected_s = microsteps / max(avg_speed, 1) * 1.25 + 0.3
    else:
        expected_s = microsteps / max(speed, 1) * 1.15 + 0.4
    time.sleep(expected_s)


def _pulse(direction: str, duration_ms: int, speed: int) -> None:
    body = {
        "stepper": "c_channel_2",
        "direction": direction,
        "duration_s": max(0.02, duration_ms / 1000.0),
        "speed": speed,
    }
    for _ in range(20):
        resp = requests.post(f"{BASE}/stepper/pulse", params=body, timeout=10)
        if resp.status_code == 200:
            return
        if resp.status_code == 409:
            time.sleep(0.03)
            continue
        resp.raise_for_status()
    raise RuntimeError("pulse stayed locked for too long")


def _detect() -> dict[str, Any]:
    resp = requests.post(f"{BASE}/api/feeder/detect/c_channel_2", timeout=15)
    resp.raise_for_status()
    return resp.json()


def _fetch_raw_jpeg() -> bytes:
    """Grab one raw JPEG frame from c_channel_2's MJPEG feed."""
    url = f"{BASE}/api/cameras/feed/c_channel_2?layer=raw&dashboard=false"
    with requests.get(url, stream=True, timeout=15) as r:
        r.raise_for_status()
        buf = bytearray()
        start = -1
        for chunk in r.iter_content(chunk_size=8192):
            buf.extend(chunk)
            if start < 0:
                start = buf.find(b"\xff\xd8")
                if start < 0 and len(buf) > 200_000:
                    buf.clear()
                    continue
            if start >= 0:
                end = buf.find(b"\xff\xd9", start + 2)
                if end >= 0:
                    return bytes(buf[start:end + 2])
            if len(buf) > 3_000_000:
                break
    raise RuntimeError(f"could not capture a complete JPEG from {url}")


def _snapshot_with_bboxes(dest: Path, bboxes: list[list[int]]) -> None:
    """Fetch a raw frame, draw the supplied bboxes in green, save as JPEG.

    Works around the live MJPEG feed drawing persistent *tracks* rather
    than raw detections — with the machine paused during a test run, the
    tracker never stabilizes (track_count stays at 0) so the annotated
    stream is blank. Instead we grab the raw frame and paint the bboxes
    we already collected via the detection endpoint.
    """
    import cv2
    import numpy as np

    jpeg = _fetch_raw_jpeg()
    arr = np.frombuffer(jpeg, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("could not decode fetched JPEG")
    for b in bboxes:
        if not isinstance(b, (list, tuple)) or len(b) < 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in b[:4]]
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 230, 0), 2, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    dest.write_bytes(buf.tobytes())


def _pause() -> None:
    requests.post(f"{BASE}/pause", timeout=10).raise_for_status()


def _pair_distances(bboxes: Iterable[list[int]]) -> list[float]:
    centers = [((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0) for b in bboxes]
    out: list[float] = []
    n = len(centers)
    for i in range(n):
        for j in range(i + 1, n):
            dx = centers[i][0] - centers[j][0]
            dy = centers[i][1] - centers[j][1]
            out.append(math.hypot(dx, dy))
    return out


def _summarize(ds: list[float]) -> dict[str, float | int | None]:
    if not ds:
        return {"min": None, "max": None, "avg": None, "median": None, "pair_count": 0}
    return {
        "min": round(min(ds), 2),
        "max": round(max(ds), 2),
        "avg": round(statistics.fmean(ds), 2),
        "median": round(statistics.median(ds), 2),
        "pair_count": len(ds),
    }


def _sample(t0: float) -> dict[str, Any]:
    d = _detect()
    bboxes = d.get("candidate_bboxes") or []
    return {
        "t": round(time.monotonic() - t0, 3),
        "piece_count": int(d.get("bbox_count") or 0),
        "track_count": int(d.get("track_count") or 0),
        "bboxes": bboxes,
        "distances": _summarize(_pair_distances(bboxes)),
    }


def _shake_loop(params: RunParams, stop: threading.Event) -> None:
    ramp = params.ramp_min_speed > 0 and params.ramp_acceleration > 0
    fwd_stepper_deg = params.amplitude_output_deg * GEAR
    rev_stepper_deg = params.amplitude_rev_output_deg * GEAR
    backlash_deg = (
        params.backlash_takeup_output_deg * GEAR
        if params.backlash_takeup_output_deg > 0
        else 0.0
    )

    def _backlash_takeup(sign: int) -> None:
        if backlash_deg <= 0:
            return
        try:
            _move_blocking(
                sign * backlash_deg, params.backlash_takeup_speed
            )
        except Exception as exc:
            print(f"[warn] backlash takeup failed: {exc}", file=sys.stderr)

    def _active_pause(opposite_sign: int) -> bool:
        """Slow counter-direction drift during the pause window. The motor
        moves at ``active_pause_speed`` for ``inter_pulse_pause_ms``, which
        both closes backlash gently (friction-coupled) and keeps the rotor
        doing *something* during the rest window. Returns True if stop
        fired mid-drift.
        """
        if params.active_pause_speed <= 0:
            return params.inter_pulse_pause_ms > 0 and stop.wait(
                timeout=params.inter_pulse_pause_ms / 1000.0
            )
        if params.inter_pulse_pause_ms <= 0:
            return False
        duration_s = params.inter_pulse_pause_ms / 1000.0
        microsteps = params.active_pause_speed * duration_s
        stepper_deg = (opposite_sign * microsteps) / MICROSTEPS_PER_STEPPER_DEG
        try:
            _move_blocking(stepper_deg, params.active_pause_speed)
        except Exception as exc:
            print(f"[warn] active pause drift failed: {exc}", file=sys.stderr)
        return stop.is_set()

    while not stop.is_set():
        if ramp:
            try:
                _move_blocking(
                    fwd_stepper_deg,
                    params.speed_fwd,
                    min_speed=params.ramp_min_speed,
                    acceleration=params.ramp_acceleration,
                )
            except Exception as exc:
                print(f"[warn] cw ramped move failed: {exc}", file=sys.stderr)
            if stop.is_set():
                return
            try:
                _move_blocking(
                    -rev_stepper_deg,
                    params.speed_rev,
                    min_speed=params.ramp_min_speed,
                    acceleration=params.ramp_acceleration,
                )
            except Exception as exc:
                print(f"[warn] ccw ramped move failed: {exc}", file=sys.stderr)
            continue
        if params.active_pause_speed <= 0:
            _backlash_takeup(+1)
        try:
            _pulse("cw", params.cycle_fwd_ms, params.speed_fwd)
        except Exception as exc:
            print(f"[warn] cw pulse failed: {exc}", file=sys.stderr)
        if stop.wait(timeout=params.cycle_fwd_ms / 1000.0):
            return
        # Pause after cw: drift slowly in ccw to close backlash for upcoming ccw pulse.
        if _active_pause(-1):
            return
        if params.active_pause_speed <= 0:
            _backlash_takeup(-1)
        try:
            _pulse("ccw", params.cycle_rev_ms, params.speed_rev)
        except Exception as exc:
            print(f"[warn] ccw pulse failed: {exc}", file=sys.stderr)
        if stop.wait(timeout=params.cycle_rev_ms / 1000.0):
            return
        # Pause after ccw: drift slowly in cw to close backlash for upcoming cw pulse.
        if _active_pause(+1):
            return


def _dance_loop(params: RunParams, stop: threading.Event, step_log: list[dict[str, Any]]) -> None:
    """Random-but-balanced dance: each step picks a fresh (amp, speed) from the
    configured ranges and a direction that keeps the cumulative drift inside
    ``dance_balance_bound_deg``. Net result — unpredictable rhythm, no net
    drift, pieces stay on the plate but never fall into the same groove.
    """
    import random

    rng = random.Random(params.dance_seed)
    balance_deg = 0.0  # running fwd(+) - rev(-) imbalance in output degrees
    while not stop.is_set():
        amp = rng.uniform(params.dance_amp_min, params.dance_amp_max)
        speed = rng.randint(params.dance_speed_min, params.dance_speed_max)
        # Force direction when we're drifting past the allowed bound so the
        # plate never walks off; otherwise pick direction uniformly.
        if balance_deg > params.dance_balance_bound_deg:
            direction = "ccw"
        elif balance_deg < -params.dance_balance_bound_deg:
            direction = "cw"
        else:
            direction = rng.choice(("cw", "ccw"))
        duration_ms = _pulse_duration_ms_for_output_deg(amp, speed)
        try:
            _pulse(direction, duration_ms, speed)
        except Exception as exc:
            print(f"[warn] {direction} dance pulse failed: {exc}", file=sys.stderr)
        signed = amp if direction == "cw" else -amp
        balance_deg += signed
        step_log.append({
            "direction": direction,
            "amp_output_deg": round(amp, 2),
            "speed_usteps_per_s": speed,
            "duration_ms": duration_ms,
            "balance_after_deg": round(balance_deg, 2),
        })
        if stop.wait(timeout=duration_ms / 1000.0):
            return


def run(params: RunParams) -> Path:
    run_dir = OUT_ROOT / f"run_{params.run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "params.json").write_text(json.dumps(asdict(params), indent=2))

    print(f"[{params.run_id}] pause machine (stays paused after test — resume manually)")
    _pause()
    time.sleep(0.5)

    if params.clump_output_deg > 0:
        print(f"[{params.run_id}] reverse {params.clump_output_deg}° output → clump")
        _move_blocking(-_stepper_deg(params.clump_output_deg), params.clump_speed)
        time.sleep(0.3)
        clumped_sample = _sample(time.monotonic())
        _snapshot_with_bboxes(run_dir / "snap_clumped.jpg", clumped_sample["bboxes"])
    else:
        print(f"[{params.run_id}] clump-output-deg=0 → skipping reverse (operator-placed start)")

    if params.center_output_deg > 0:
        print(f"[{params.run_id}] forward {params.center_output_deg}° output → start position")
        _move_blocking(_stepper_deg(params.center_output_deg), params.center_speed)
        time.sleep(0.5)
    else:
        print(f"[{params.run_id}] center-output-deg=0 → skipping forward priming")

    print(f"[{params.run_id}] baseline detection + start snapshot")
    t0 = time.monotonic()
    start_sample = _sample(t0)
    timeline: list[dict[str, Any]] = [start_sample]
    _snapshot_with_bboxes(run_dir / "snap_start.jpg", start_sample["bboxes"])

    if params.single_forward_output_deg > 0:
        print(
            f"[{params.run_id}] single forward move {params.single_forward_output_deg}° @ {params.single_forward_speed}sp"
        )
        _move_blocking(
            _stepper_deg(params.single_forward_output_deg),
            params.single_forward_speed,
        )
        time.sleep(0.4)
        after_sample = _sample(t0)
        timeline.append(after_sample)
        _snapshot_with_bboxes(run_dir / "snap_after.jpg", after_sample["bboxes"])
        (run_dir / "timeline.json").write_text(json.dumps(timeline, indent=2))
        print(f"[{params.run_id}] single-forward run done → {run_dir} (machine still paused)")
        return run_dir

    stop = threading.Event()
    dance_steps: list[dict[str, Any]] = []
    if params.dance_mode:
        t = threading.Thread(
            target=_dance_loop, args=(params, stop, dance_steps), daemon=True
        )
    else:
        t = threading.Thread(target=_shake_loop, args=(params, stop), daemon=True)
    t.start()

    deadline = t0 + params.shake_duration_s
    next_sample = t0 + DETECT_SAMPLE_PERIOD_S
    while time.monotonic() < deadline:
        sleep_for = min(next_sample, deadline) - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)
        timeline.append(_sample(t0))
        next_sample += DETECT_SAMPLE_PERIOD_S

    stop.set()
    t.join(timeout=2.0)
    time.sleep(0.3)

    print(f"[{params.run_id}] final detection + after snapshot")
    after_sample = _sample(t0)
    timeline.append(after_sample)
    _snapshot_with_bboxes(run_dir / "snap_after.jpg", after_sample["bboxes"])

    (run_dir / "timeline.json").write_text(json.dumps(timeline, indent=2))
    if params.dance_mode and dance_steps:
        (run_dir / "dance_log.json").write_text(json.dumps(dance_steps, indent=2))
        print(f"[{params.run_id}] dance: {len(dance_steps)} steps, final balance {dance_steps[-1]['balance_after_deg']:.1f}°")
    print(f"[{params.run_id}] {len(timeline)} samples saved → {run_dir} (machine still paused)")

    return run_dir


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


_REPORT_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>c_channel_2 shake test report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  body { font-family: ui-sans-serif, system-ui, sans-serif; margin: 0; padding: 20px; background: #111; color: #eee; }
  h1 { margin: 0 0 16px; }
  .run { border: 1px solid #333; margin-bottom: 32px; padding: 16px; background: #1a1a1a; }
  .run h2 { margin-top: 0; display: flex; gap: 12px; align-items: baseline; }
  .pattern { color: #9cdcfe; font-family: ui-monospace, monospace; }
  table.params { border-collapse: collapse; font-size: 13px; margin: 8px 0 12px; }
  table.params td { padding: 2px 10px 2px 0; }
  table.params td:first-child { color: #888; }
  .snap-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 8px; margin-bottom: 12px; }
  .snap-row figure { margin: 0; background: #000; border: 1px solid #333; }
  .snap-row img { width: 100%; display: block; }
  .snap-row figcaption { padding: 4px 6px; font-size: 11px; color: #aaa; font-family: ui-monospace, monospace; }
  .charts { display: grid; grid-template-columns: 1fr; gap: 16px; }
  .chart-box { background: #0a0a0a; border: 1px solid #333; padding: 8px; }
  .chart-box canvas { max-height: 260px; }
  .note { background: #222; border-left: 3px solid #c29b20; padding: 6px 10px; font-size: 13px; color: #ddd; margin-bottom: 12px; }
</style>
</head>
<body>
<h1>c_channel_2 shake tests</h1>
__RUNS__
<script>
const runs = __RUNS_JSON__;
for (const r of runs) {
  if (!r.timeline || !r.timeline.length) continue;
  const labels = r.timeline.map(s => s.t.toFixed(2));
  new Chart(document.getElementById('count_' + r.run_id), {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'pieces detected', data: r.timeline.map(s => s.piece_count), borderColor: '#7cc36e', backgroundColor: 'transparent', tension: 0.25 },
        { label: 'tracks', data: r.timeline.map(s => s.track_count), borderColor: '#9cdcfe', backgroundColor: 'transparent', tension: 0.25, borderDash: [4, 4] },
      ]
    },
    options: { responsive: true, animation: false, scales: { y: { beginAtZero: true, ticks: { color: '#aaa' } }, x: { ticks: { color: '#aaa' } } }, plugins: { legend: { labels: { color: '#ddd' } } } },
  });
  new Chart(document.getElementById('dist_' + r.run_id), {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'min', data: r.timeline.map(s => s.distances.min), borderColor: '#e06c75', tension: 0.25, backgroundColor: 'transparent' },
        { label: 'avg', data: r.timeline.map(s => s.distances.avg), borderColor: '#c29b20', tension: 0.25, backgroundColor: 'transparent' },
        { label: 'median', data: r.timeline.map(s => s.distances.median), borderColor: '#7cc36e', tension: 0.25, backgroundColor: 'transparent' },
        { label: 'max', data: r.timeline.map(s => s.distances.max), borderColor: '#9cdcfe', tension: 0.25, backgroundColor: 'transparent' },
      ]
    },
    options: { responsive: true, animation: false, scales: { y: { beginAtZero: true, ticks: { color: '#aaa' } }, x: { ticks: { color: '#aaa' } } }, plugins: { legend: { labels: { color: '#ddd' } } } },
  });
}
</script>
</body>
</html>
"""


def _render_run(run_dir: Path) -> tuple[str, dict[str, Any]] | None:
    try:
        params = json.loads((run_dir / "params.json").read_text())
    except Exception:
        return None
    timeline: list[dict[str, Any]] = []
    try:
        timeline = json.loads((run_dir / "timeline.json").read_text())
    except Exception:
        pass

    snaps = ["clumped", "start", "after"]
    snap_html = "\n".join(
        f'<figure><img src="{run_dir.name}/snap_{key}.jpg" alt="{key}" /><figcaption>{key}</figcaption></figure>'
        for key in snaps
        if (run_dir / f"snap_{key}.jpg").exists()
    )

    counts = [s["piece_count"] for s in timeline]
    medians = [s["distances"]["median"] for s in timeline if s["distances"]["median"] is not None]
    summary_bits = []
    if counts:
        summary_bits.append(f"piece count {counts[0]} → {counts[-1]} (min {min(counts)}, max {max(counts)})")
    if medians:
        summary_bits.append(
            f"median distance {medians[0]:.0f} → {medians[-1]:.0f} px (min {min(medians):.0f}, max {max(medians):.0f})"
        )

    note_html = ""
    note_path = run_dir / "note.md"
    if note_path.exists():
        note_html = f'<div class="note">{html.escape(note_path.read_text().strip())}</div>'

    params_rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>"
        for k, v in params.items()
    )

    run_id = params["run_id"]
    section = f"""
<section class="run">
  <h2>Run {html.escape(str(run_id))} <span class="pattern">{html.escape(params.get('pattern', ''))}</span></h2>
  {note_html}
  {('<p>' + html.escape(' — '.join(summary_bits)) + '</p>') if summary_bits else ''}
  <table class="params">{params_rows}</table>
  <div class="snap-row">{snap_html}</div>
  <div class="charts">
    <div class="chart-box"><canvas id="count_{html.escape(str(run_id))}"></canvas></div>
    <div class="chart-box"><canvas id="dist_{html.escape(str(run_id))}"></canvas></div>
  </div>
</section>
"""
    return section, {"run_id": run_id, "timeline": timeline, "params": params}


def build_report(out_root: Path = OUT_ROOT) -> Path:
    runs = sorted(p for p in out_root.glob("run_*") if p.is_dir())
    sections: list[str] = []
    data: list[dict[str, Any]] = []
    for run_dir in runs:
        rendered = _render_run(run_dir)
        if rendered is None:
            continue
        sec, payload = rendered
        sections.append(sec)
        data.append(payload)
    html_text = _REPORT_HTML.replace("__RUNS__", "\n".join(sections)).replace(
        "__RUNS_JSON__", json.dumps(data)
    )
    index = out_root / "index.html"
    index.write_text(html_text)
    return index


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--pattern", required=True, help="free-form label, e.g. symmetric-hard")
    ap.add_argument("--amplitude-output-deg", type=float, default=15.0)
    ap.add_argument("--amplitude-rev-output-deg", type=float, default=-1.0, help="reverse amplitude (defaults to fwd amplitude)")
    ap.add_argument("--speed-fwd", type=int, default=2000)
    ap.add_argument("--speed-rev", type=int, default=2000)
    ap.add_argument("--cycle-fwd-ms", type=int, default=0, help="0 = derive from amplitude/speed")
    ap.add_argument("--cycle-rev-ms", type=int, default=0)
    ap.add_argument("--shake-duration-s", type=float, default=5.0)
    ap.add_argument("--clump-output-deg", type=float, default=520.0)
    ap.add_argument("--center-output-deg", type=float, default=180.0)
    ap.add_argument("--clump-speed", type=int, default=2500)
    ap.add_argument("--center-speed", type=int, default=2500)
    ap.add_argument("--note", default="")
    ap.add_argument("--dance", action="store_true", help="enable random-but-balanced dance pattern")
    ap.add_argument("--dance-amp-min", type=float, default=5.0)
    ap.add_argument("--dance-amp-max", type=float, default=20.0)
    ap.add_argument("--dance-speed-min", type=int, default=1000)
    ap.add_argument("--dance-speed-max", type=int, default=2500)
    ap.add_argument("--dance-balance-bound-deg", type=float, default=25.0, help="max cumulative net drift before direction is forced back")
    ap.add_argument("--dance-seed", type=int, default=42)
    ap.add_argument("--ramp-min-speed", type=int, default=0, help="enable ramp: start/end speed (µsteps/s). 0 = no ramp")
    ap.add_argument("--ramp-acceleration", type=int, default=0, help="enable ramp: acceleration (µsteps/s²). 0 = no ramp")
    ap.add_argument("--single-forward-output-deg", type=float, default=0.0, help="instead of shake, do one forward move of this many output deg after priming")
    ap.add_argument("--single-forward-speed", type=int, default=2000)
    ap.add_argument("--inter-pulse-pause-ms", type=int, default=0, help="rest period between each fwd/rev half-cycle (0 = back-to-back)")
    ap.add_argument("--backlash-takeup-output-deg", type=float, default=0.0, help="gentle pre-move before each main pulse to take up gear backlash (0 = off)")
    ap.add_argument("--backlash-takeup-speed", type=int, default=500)
    ap.add_argument("--active-pause-speed", type=int, default=0, help="if > 0, use the inter-pulse pause for a slow opposite-direction drift at this speed (µsteps/s)")
    ap.add_argument("--report-only", action="store_true", help="skip the run, just rebuild index.html")
    args = ap.parse_args()

    amp_rev = (
        args.amplitude_rev_output_deg
        if args.amplitude_rev_output_deg >= 0
        else args.amplitude_output_deg
    )
    if args.cycle_fwd_ms == 0:
        args.cycle_fwd_ms = _pulse_duration_ms_for_output_deg(
            args.amplitude_output_deg, args.speed_fwd
        )
    if args.cycle_rev_ms == 0:
        args.cycle_rev_ms = _pulse_duration_ms_for_output_deg(
            amp_rev, args.speed_rev
        )

    params = RunParams(
        run_id=args.run_id,
        pattern=args.pattern,
        dance_mode=bool(args.dance),
        dance_amp_min=args.dance_amp_min,
        dance_amp_max=args.dance_amp_max,
        dance_speed_min=args.dance_speed_min,
        dance_speed_max=args.dance_speed_max,
        dance_balance_bound_deg=args.dance_balance_bound_deg,
        dance_seed=args.dance_seed,
        ramp_min_speed=args.ramp_min_speed,
        ramp_acceleration=args.ramp_acceleration,
        amplitude_output_deg=args.amplitude_output_deg,
        amplitude_rev_output_deg=amp_rev,
        speed_fwd=args.speed_fwd,
        speed_rev=args.speed_rev,
        cycle_fwd_ms=args.cycle_fwd_ms,
        cycle_rev_ms=args.cycle_rev_ms,
        shake_duration_s=args.shake_duration_s,
        clump_output_deg=args.clump_output_deg,
        center_output_deg=args.center_output_deg,
        clump_speed=args.clump_speed,
        center_speed=args.center_speed,
        note=args.note,
        single_forward_output_deg=args.single_forward_output_deg,
        single_forward_speed=args.single_forward_speed,
        inter_pulse_pause_ms=args.inter_pulse_pause_ms,
        backlash_takeup_output_deg=args.backlash_takeup_output_deg,
        backlash_takeup_speed=args.backlash_takeup_speed,
        active_pause_speed=args.active_pause_speed,
    )

    if not args.report_only:
        run(params)

    index = build_report()
    print(f"report: {index}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
