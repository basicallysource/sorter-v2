import sys
import os
import time
import shutil
import glob as globmod

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from global_config import mkGlobalConfig
from irl.config import mkIRLConfig, mkIRLInterface
from vision import VisionManager
from subsystems.feeder.analysis import computeChannelGeometry
from blob_manager import BLOB_DIR

BASELINE_DIR = BLOB_DIR / "feeder_baseline"
MAX_FRAMES = 64
STEPS_PER_FRAME = 1600  # 1 full revolution per frame
CAROUSEL_STEPS_PER_FRAME = 111  # ~25 deg per frame (1600 * 25 / 360)
STEP_DELAY_US = 150
MOVE_TIMEOUT_MS = 3000
SETTLE_S = 0.1


def loadExistingFrames() -> list[np.ndarray]:
    frames = []
    paths = sorted(globmod.glob(str(BASELINE_DIR / "frame_*.png")))
    for p in paths:
        gray = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        if gray is not None:
            frames.append(gray)
    return frames


def saveEnvelope(frames: list[np.ndarray], mask: np.ndarray) -> None:
    stack = np.stack(frames, axis=0)
    baseline_min = np.min(stack, axis=0).astype(np.uint8)
    baseline_max = np.max(stack, axis=0).astype(np.uint8)
    cv2.imwrite(str(BASELINE_DIR / "mask.png"), mask)
    cv2.imwrite(str(BASELINE_DIR / "baseline_min.png"), baseline_min)
    cv2.imwrite(str(BASELINE_DIR / "baseline_max.png"), baseline_max)


def main() -> int:
    wipe = "--wipe" in sys.argv
    sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--wipe"]

    gc = mkGlobalConfig()
    irl_config = mkIRLConfig()
    irl = mkIRLInterface(irl_config, gc)

    vision = VisionManager(irl_config, gc)
    vision.start()

    print("waiting for aruco tags...")
    geometry = None
    for _ in range(30):
        time.sleep(0.2)
        aruco_tags = vision.getFeederArucoTags()
        geometry = computeChannelGeometry(aruco_tags, irl_config.aruco_tags)
        if geometry.second_channel is not None or geometry.third_channel is not None:
            break

    if geometry is None or (geometry.second_channel is None and geometry.third_channel is None):
        print("no channel geometry found. are aruco tags visible?")
        vision.stop()
        return 1

    # load or wipe existing frames
    if wipe and BASELINE_DIR.exists():
        print("wiping existing baseline...")
        shutil.rmtree(BASELINE_DIR)

    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    frames = loadExistingFrames()
    existing_count = len(frames)
    frames_needed = MAX_FRAMES - existing_count

    if frames_needed <= 0:
        print(f"already have {existing_count} frames (max {MAX_FRAMES}). use --wipe to reset.")
        vision.stop()
        return 0

    print(f"have {existing_count} existing frames, capturing {frames_needed} more...")

    initial_gray = vision.getLatestFeederGray()
    if initial_gray is None:
        print("no camera frame available")
        vision.stop()
        return 1
    mask = vision.buildFeederChannelMask(geometry, initial_gray.shape)
    if mask is None:
        print("failed to build channel mask")
        vision.stop()
        return 1

    for i in range(frames_needed):
        irl.second_c_channel_rotor_stepper.moveStepsBlocking(
            -STEPS_PER_FRAME, MOVE_TIMEOUT_MS, STEP_DELAY_US,
        )
        irl.third_c_channel_rotor_stepper.moveStepsBlocking(
            -STEPS_PER_FRAME, MOVE_TIMEOUT_MS, STEP_DELAY_US,
        )
        irl.carousel_stepper.moveSteps(-CAROUSEL_STEPS_PER_FRAME, STEP_DELAY_US)
        time.sleep(SETTLE_S)
        gray = vision.getLatestFeederGray()
        if gray is None:
            print(f"  frame {existing_count + i + 1}/{MAX_FRAMES} - no frame")
            continue

        frames.append(gray)
        cv2.imwrite(str(BASELINE_DIR / f"frame_{len(frames)-1:03d}.png"), gray)
        saveEnvelope(frames, mask)
        print(f"  frame {existing_count + i + 1}/{MAX_FRAMES} ({len(frames)} total)")

    if not frames:
        print("no frames captured")
        vision.stop()
        return 1

    print(f"done. {len(frames)} frames + envelope in {BASELINE_DIR}")

    vision.stop()
    irl.disableSteppers()
    irl.mcu.flush()
    irl.mcu.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
