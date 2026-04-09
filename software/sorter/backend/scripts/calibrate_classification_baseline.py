import sys
import os
import time
import json
import glob as globmod
import threading
import queue
from datetime import datetime

import random

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from global_config import mkGlobalConfig
from irl.config import mkIRLConfig, mkIRLInterface
from vision.diff_configs import DEFAULT_CLASSIFICATION_DIFF_CONFIG

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
from vision import VisionManager
from blob_manager import BLOB_DIR

MAX_FRAMES = 64
DEGREES_PER_FRAME = -90
MOVE_TIMEOUT_MS = 2000
JITTER_RANGE = 1


def formatEta(seconds_remaining: float) -> str:
    seconds_remaining = max(0, int(round(seconds_remaining)))
    minutes, seconds = divmod(seconds_remaining, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def loadExistingGrayFrames(baseline_dir: Path, prefix: str) -> list[np.ndarray]:
    frames = []
    paths = sorted(globmod.glob(str(baseline_dir / f"{prefix}_frame_*.png")))
    for p in paths:
        gray = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        if gray is not None:
            frames.append(gray)
    return frames


def loadExistingLabFrames(baseline_dir: Path, prefix: str) -> list[np.ndarray]:
    frames = []
    paths = sorted(globmod.glob(str(baseline_dir / f"{prefix}_frame_lab_*.png")))
    for p in paths:
        lab_frame = cv2.imread(p, cv2.IMREAD_COLOR)
        if lab_frame is not None:
            frames.append(lab_frame)
    return frames


def saveGrayEnvelope(baseline_dir: Path, prefix: str, frames: list[np.ndarray]) -> None:
    stack = np.stack(frames, axis=0)
    cv2.imwrite(str(baseline_dir / f"{prefix}_baseline_min.png"), np.min(stack, axis=0).astype(np.uint8))
    cv2.imwrite(str(baseline_dir / f"{prefix}_baseline_max.png"), np.max(stack, axis=0).astype(np.uint8))


def saveLabEnvelope(baseline_dir: Path, prefix: str, frames: list[np.ndarray]) -> None:
    stack = np.stack(frames, axis=0)
    cv2.imwrite(str(baseline_dir / f"{prefix}_baseline_lab_min.png"), np.min(stack, axis=0).astype(np.uint8))
    cv2.imwrite(str(baseline_dir / f"{prefix}_baseline_lab_max.png"), np.max(stack, axis=0).astype(np.uint8))


def precomputeBaseline(baseline_dir: Path, prefix: str, mode: str, frames: list[np.ndarray]) -> None:
    cfg = DEFAULT_CLASSIFICATION_DIFF_CONFIG
    stack = np.stack(frames, axis=0)
    baseline_min = np.min(stack, axis=0).astype(np.uint8)
    baseline_max = np.max(stack, axis=0).astype(np.uint8)

    if len(frames) >= 2 and cfg.adaptive_std_k > 0:
        stddev = np.std(stack.astype(np.float32), axis=0)
        adaptive_margin = np.clip(stddev * cfg.adaptive_std_k, 0, 100).astype(np.uint8)
        baseline_min = np.clip(baseline_min.astype(np.int16) - adaptive_margin.astype(np.int16), 0, 255).astype(np.uint8)
        baseline_max = np.clip(baseline_max.astype(np.int16) + adaptive_margin.astype(np.int16), 0, 255).astype(np.uint8)

    if cfg.envelope_margin > 0:
        baseline_min = np.clip(baseline_min.astype(np.int16) - cfg.envelope_margin, 0, 255).astype(np.uint8)
        baseline_max = np.clip(baseline_max.astype(np.int16) + cfg.envelope_margin, 0, 255).astype(np.uint8)

    mode_suffix = f"_{mode}" if mode != "gray" else ""
    np.save(str(baseline_dir / f"{prefix}_precomputed{mode_suffix}_min.npy"), baseline_min)
    np.save(str(baseline_dir / f"{prefix}_precomputed{mode_suffix}_max.npy"), baseline_max)

    manifest = {
        "mode": mode,
        "num_frames": len(frames),
        "envelope_margin": cfg.envelope_margin,
        "adaptive_std_k": cfg.adaptive_std_k,
    }
    with open(baseline_dir / f"{prefix}_precomputed{mode_suffix}.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"  {prefix}: precomputed {mode} baseline saved ({len(frames)} frames, margin={cfg.envelope_margin}, k={cfg.adaptive_std_k})")


def getLatestRaw(vision: VisionManager, cam: str) -> np.ndarray | None:
    if cam == "top":
        frame = vision.classification_top_frame
    else:
        frame = vision.classification_bottom_frame
    if frame is None:
        return None
    return frame.raw


def _writeWorker(write_queue: queue.Queue[tuple[str, np.ndarray] | None]) -> None:
    while True:
        item = write_queue.get()
        if item is None:
            break
        path, img = item
        cv2.imwrite(path, img)


def calibrateCamera(
    vision: VisionManager,
    irl,
    baseline_dir: Path,
    cam: str,
    wipe: bool,
    no_jitter: bool,
) -> bool:
    prefix = cam
    cam_dir = baseline_dir

    if wipe:
        for p in globmod.glob(str(cam_dir / f"{prefix}_*.png")) + globmod.glob(str(cam_dir / f"{prefix}_*.npy")) + globmod.glob(str(cam_dir / f"{prefix}_*.json")):
            os.remove(p)

    gray_frames = loadExistingGrayFrames(cam_dir, prefix)
    lab_frames = loadExistingLabFrames(cam_dir, prefix)
    if len(gray_frames) != len(lab_frames):
        print(f"  {cam}: gray/lab frame count mismatch ({len(gray_frames)} vs {len(lab_frames)}). run with --wipe to rebuild.")
        return False
    existing_count = len(gray_frames)
    frames_needed = MAX_FRAMES - existing_count

    if frames_needed <= 0:
        print(f"  {cam}: already have {existing_count} frames (max {MAX_FRAMES}). use --wipe to reset.")
        return True

    print(f"  {cam}: have {existing_count} existing frames, capturing {frames_needed} more...")

    write_queue: queue.Queue[tuple[str, np.ndarray] | None] = queue.Queue()
    writer = threading.Thread(target=_writeWorker, args=(write_queue,), daemon=True)
    writer.start()

    debt = 0.0
    interrupted = False
    capture_start_time = time.time()
    try:
        for i in range(frames_needed):
            if not no_jitter and i % 2 == 1:
                jitter = random.uniform(-JITTER_RANGE, JITTER_RANGE)
            else:
                jitter = 0.0
            move = DEGREES_PER_FRAME + jitter - debt
            debt = jitter
            irl.carousel_stepper.move_degrees_blocking(move)
            time.sleep(MOVE_TIMEOUT_MS / 1000.0)

            completed_steps = i + 1
            total_elapsed_seconds = time.time() - capture_start_time
            avg_step_seconds = total_elapsed_seconds / completed_steps
            remaining_steps = frames_needed - completed_steps
            eta_seconds = avg_step_seconds * remaining_steps
            eta_text = formatEta(eta_seconds)
            progress_total = existing_count + completed_steps

            raw = getLatestRaw(vision, cam)
            if raw is None:
                print(f"    frame {progress_total}/{MAX_FRAMES} - no frame - eta {eta_text}")
                continue

            gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
            lab_frame = cv2.cvtColor(raw, cv2.COLOR_BGR2LAB)

            gray_frames.append(gray)
            lab_frames.append(lab_frame)

            frame_idx = len(gray_frames) - 1
            write_queue.put((str(cam_dir / f"{prefix}_frame_{frame_idx:03d}.png"), gray))
            write_queue.put((str(cam_dir / f"{prefix}_frame_lab_{frame_idx:03d}.png"), lab_frame))
            print(f"    frame {progress_total}/{MAX_FRAMES} ({len(gray_frames)} total) - eta {eta_text}")
    except KeyboardInterrupt:
        print(f"\n  {cam}: interrupted, saving {len(gray_frames)} frames captured so far...")
        interrupted = True

    write_queue.put(None)
    writer.join()

    if not gray_frames:
        print(f"  {cam}: no frames captured")
        return False

    if not interrupted and not no_jitter and abs(debt) > 1e-6:
        print(f"  {cam}: closing jitter residual ({debt:+.3f}°)")
        irl.carousel_stepper.move_degrees_blocking(-debt)

    saveGrayEnvelope(cam_dir, prefix, gray_frames)
    saveLabEnvelope(cam_dir, prefix, lab_frames)
    precomputeBaseline(cam_dir, prefix, "gray", gray_frames)
    precomputeBaseline(cam_dir, prefix, "lab", lab_frames)

    if interrupted:
        print(f"  {cam}: saved {len(gray_frames)} frames + envelopes + precomputed (partial)")
        raise KeyboardInterrupt
    print(f"  {cam}: done. {len(gray_frames)} frames + gray/lab envelopes + precomputed")
    return True


def main() -> int:
    wipe = "--wipe" in sys.argv
    no_jitter = "--jitter" not in sys.argv
    sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a not in ("--wipe", "--jitter")]

    gc = mkGlobalConfig()
    LOGS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"calibrate_classification_baseline_{timestamp}.log"
    gc.logger._log_file = open(log_path, "a")

    irl_config = mkIRLConfig()
    irl = mkIRLInterface(irl_config, gc)
    irl.enableSteppers()

    vision = VisionManager(irl_config, gc, irl)
    vision.start()

    print("waiting for camera frames...")
    time.sleep(2.0)

    baseline_dir = BLOB_DIR / "classification_baseline"
    baseline_dir.mkdir(parents=True, exist_ok=True)

    has_top = vision.classification_top_frame is not None
    has_bottom = vision.classification_bottom_frame is not None

    if not has_top and not has_bottom:
        print("ERROR: no classification cameras available")
        vision.stop()
        return 1

    print(f"cameras: top={'yes' if has_top else 'no'} bottom={'yes' if has_bottom else 'no'}")

    ok = True
    if has_top:
        ok = calibrateCamera(vision, irl, baseline_dir, "top", wipe, no_jitter) and ok
    if has_bottom:
        ok = calibrateCamera(vision, irl, baseline_dir, "bottom", wipe, no_jitter) and ok

    print(f"done. baseline in {baseline_dir}")

    vision.stop()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
