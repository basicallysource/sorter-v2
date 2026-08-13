"""Brute-optimize DetectorParams against the full Hive image set.

Cost function (lower is better):

    cost = -mean(prominence_ratio)              # reward sharp peaks
         + LAMBDA_CONSISTENCY * mean_machine_circ_std  # reward agreement within machine
         + PENALTY_INVALID * fraction_invalid          # large penalty for NaN / annulus_invalid

The prominence term rewards parameter settings that make the 5-spoke
template "ring like a bell" in the score curve, which is a label-free
proxy for "the detector locked onto something real".

The consistency term penalises parameter sets where the same machine's
captures disagree by more than the platter-rotation noise floor. Since
the platter actually rotates between captures, a perfect score on this
term is impossible — but parameter sets that *aren't actively
introducing noise* score better than ones that are.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import differential_evolution

from detector import (
    DetectorParams,
    HubAutoDetectParams,
    defaultAnnulusForMachine,
    detectSpokeAngle,
)


DEFAULT_IMG_DIR = Path("/Volumes/T7/sorter-v2-c4-spoke-orientation/hive-images")


@dataclass
class LoadedImage:
    machine: str
    path: Path
    image: np.ndarray


def loadDataset(img_dir: Path) -> list[LoadedImage]:
    items: list[LoadedImage] = []
    for machine_dir in sorted(p for p in img_dir.iterdir() if p.is_dir()):
        for img_path in sorted(machine_dir.glob("*.jpg")):
            img = cv2.imread(str(img_path))
            if img is None:
                continue
            items.append(LoadedImage(machine_dir.name, img_path, img))
    return items


# parameter vector layout:
PARAM_KEYS = [
    "preblur_sigma_px",
    "spoke_smooth_deg",
    "clip_outer_frac",
    "clip_inner_extra_frac",
    "edge_taper_frac",
    "use_gradient_magnitude",   # 0/1, binary
]
BOUNDS = [
    (0.3, 5.0),    # preblur_sigma_px
    (0.5, 12.0),   # spoke_smooth_deg
    (0.80, 1.00),  # clip_outer_frac
    (0.00, 0.20),  # clip_inner_extra_frac
    (0.00, 0.20),  # edge_taper_frac
    (0.0, 1.0),    # use_gradient_magnitude (binarised)
]


def vectorToParams(x: np.ndarray) -> DetectorParams:
    return DetectorParams(
        preblur_sigma_px=float(x[0]),
        spoke_smooth_deg=float(x[1]),
        clip_outer_frac=float(x[2]),
        clip_inner_extra_frac=float(x[3]),
        edge_taper_frac=float(x[4]),
        use_gradient_magnitude=bool(x[5] >= 0.5),
    )


def circularStdDeg(angles: list[float]) -> float:
    if not angles:
        return 0.0
    rads = [a / 72.0 * 2 * math.pi for a in angles]
    sx = float(np.mean([math.cos(r) for r in rads]))
    sy = float(np.mean([math.sin(r) for r in rads]))
    R = math.hypot(sx, sy)
    if R < 1e-9:
        return 72.0 / math.sqrt(12)
    return math.sqrt(-2 * math.log(R)) * 72.0 / (2 * math.pi)


def evaluate(
    x: np.ndarray, dataset: list[LoadedImage], hub_params: HubAutoDetectParams,
) -> tuple[float, dict]:
    params = vectorToParams(x)
    proms: list[float] = []
    invalid = 0
    angles_per_machine: dict[str, list[float]] = {}
    for item in dataset:
        ann_def = defaultAnnulusForMachine(item.machine, item.image.shape[:2])
        try:
            res = detectSpokeAngle(item.image, ann_def, params, hub_params)
        except Exception:
            invalid += 1
            continue
        if not res.success or not math.isfinite(res.prominence_ratio):
            invalid += 1
            continue
        proms.append(res.prominence_ratio)
        angles_per_machine.setdefault(item.machine, []).append(res.angle_deg)
    n = len(dataset)
    frac_invalid = invalid / max(n, 1)
    mean_prom = float(np.mean(proms)) if proms else 0.0
    cs = [circularStdDeg(v) for v in angles_per_machine.values() if v]
    mean_consistency_deg = float(np.mean(cs)) if cs else 72.0 / math.sqrt(12)

    LAMBDA_CONSISTENCY = 0.05
    PENALTY_INVALID = 5.0
    cost = -mean_prom + LAMBDA_CONSISTENCY * mean_consistency_deg + PENALTY_INVALID * frac_invalid

    info = {
        "mean_prom": mean_prom,
        "mean_consistency_deg": mean_consistency_deg,
        "frac_invalid": frac_invalid,
        "n_used": len(proms),
    }
    return cost, info


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--in-dir", type=Path, default=DEFAULT_IMG_DIR)
    p.add_argument("--maxiter", type=int, default=25)
    p.add_argument("--popsize", type=int, default=12)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", type=Path, default=Path("optimized_params.json"))
    args = p.parse_args()

    print(f"loading dataset from {args.in_dir} ...")
    dataset = loadDataset(args.in_dir)
    print(f"loaded {len(dataset)} images across "
          f"{len(set(d.machine for d in dataset))} machines")

    hub_params = HubAutoDetectParams()

    # Baseline (current defaults)
    base = DetectorParams()
    base_x = np.array([
        base.preblur_sigma_px,
        base.spoke_smooth_deg,
        base.clip_outer_frac,
        base.clip_inner_extra_frac,
        base.edge_taper_frac,
        1.0 if base.use_gradient_magnitude else 0.0,
    ])
    t0 = time.time()
    base_cost, base_info = evaluate(base_x, dataset, hub_params)
    print(f"baseline cost={base_cost:.4f}  {base_info}  ({time.time()-t0:.1f}s)")

    iter_count = [0]
    best = {"cost": base_cost, "x": base_x, "info": base_info}

    def cb_eval(x):
        c, info = evaluate(x, dataset, hub_params)
        return c

    def cb_progress(x, convergence):
        iter_count[0] += 1
        c, info = evaluate(x, dataset, hub_params)
        if c < best["cost"]:
            best["cost"] = c
            best["x"] = x.copy()
            best["info"] = info
        print(f"  gen {iter_count[0]:2d}  best cost={best['cost']:.4f}  "
              f"this x→cost={c:.4f}  conv={convergence:.3f}")

    print("running differential_evolution ...")
    result = differential_evolution(
        cb_eval,
        BOUNDS,
        seed=args.seed,
        maxiter=args.maxiter,
        popsize=args.popsize,
        tol=1e-3,
        polish=True,
        updating="deferred",
        workers=1,
        callback=cb_progress,
    )
    final_x = result.x
    final_cost, final_info = evaluate(final_x, dataset, hub_params)
    if final_cost > best["cost"]:
        final_x = best["x"]
        final_cost = best["cost"]
        final_info = best["info"]

    final_params = vectorToParams(final_x)
    summary = {
        "baseline": {"params": base.__dict__, "cost": base_cost, **base_info},
        "optimized": {"params": final_params.__dict__, "cost": final_cost, **final_info},
        "x_vector": final_x.tolist(),
        "param_keys": PARAM_KEYS,
    }
    Path(args.out).write_text(json.dumps(summary, indent=2, default=str))
    print("\n=== RESULT ===")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
