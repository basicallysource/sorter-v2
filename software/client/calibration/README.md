# Camera color calibration

Locks white balance / exposure / gain on the classification top camera and
verifies the lock against a physical target, so HSV-based detection gets
stable readings. See `scripts/calibrate_camera_color.py` for the full tool
docstring.

## Target

A 4x2 LEGO tile grid, mounted for repeatable placement at the tray position:

```
[ red    ] [ green     ] [ blue       ] [ yellow ]   <- saturated colors
[ black  ] [ dark_gray ] [ light_gray ] [ white  ]   <- grayscale ramp
```

## Run order

All commands from `software/client/`, target in place in the chamber.

1. **`roi`** (one-time, or after the camera/target is repositioned)

   ```bash
   .venv/bin/python scripts/calibrate_camera_color.py roi
   ```

   Click the 8 tile centers in the order shown above (left-to-right, top row
   then bottom row). `u` undo, `s` save, `q` abort.
   Writes `target_rois.json`.

2. **`reference`** (one-time, or whenever "known good" is redefined)

   Hand-tune `CLASSIFICATION_CAMERA_LOCK` in `irl/config.py` until the chamber
   looks right, restart the sorter so the lock is applied, then:

   ```bash
   .venv/bin/python scripts/calibrate_camera_color.py reference
   ```

   Writes `reference_snapshot.json` + `reference_snapshot.png`. This is the
   target the sweep optimizes toward — commit it to the repo.

3. **`sweep`** (whenever lighting/cameras change and need re-tuning)

   ```bash
   .venv/bin/python scripts/calibrate_camera_color.py sweep --fine
   ```

   Sweeps WB x exposure x gain, scores each capture against the reference,
   and writes results to `sweep_output/`. Prints the winning values to paste
   into `CLASSIFICATION_CAMERA_LOCK` (`irl/config.py`) by hand — nothing here
   is auto-applied.

   The default exposure sweep is whole numbers 3-10 (`exposure-time-abs` is
   integer with step-size 1, and this sensor saturates above ~10 — see Notes).
   Override with `--exposures` if needed.

## After swapping cameras

The 3-10 exposure default (and the 2800-6500K WB assumption) are tuned for
the old sensor and likely don't apply to a new one. Starting fresh:

1. Update `CLASSIFICATION_TOP_UVC_NAME` in `irl/config.py` to the new
   camera's UVC product name (`uvc-util -d` to list devices).
2. Re-run `roi` — the new camera's FOV/mounting will shift tile positions.
3. Re-run `reference` once the chamber looks right under the new camera's
   (probably-default) settings.
4. Run a discovery sweep against the new camera's actual reported ranges:

   ```bash
   .venv/bin/python scripts/calibrate_camera_color.py sweep --reset --fine
   ```

   `--reset` ignores the `--exposures`/`--gains`/`--wb-*` defaults (which
   were tuned for the old sensor) and instead queries the new camera's
   exposure-time-abs / white-balance-temp / gain ranges via `uvc-util -S`,
   then builds a broad log-spaced exposure sweep, a linear WB sweep across
   its full range, and a few gain points — same shape as the sweep that
   originally found the old camera's 3-10 sweet spot.
5. Once a productive narrow range is found, re-run plain `sweep --fine`
   (optionally with `--exposures`/`--gains` overrides) to refine, then
   hand-edit the 3-10 default in `buildSweepValues()` to match the new
   camera if you'll be re-tuning it often.

## Files

- `target_rois.json` — pixel ROI for each tile (from `roi`), committed.
- `reference_snapshot.json` / `.png` — the optimization target (from
  `reference`), committed.
- `sweep_output/` — per-run results (`results_*.json/csv`, `best_*.json`,
  `compare_*.png`). Not committed; regenerate as needed.

## Notes

- Top camera only — the bottom classification camera is unused currently.
- On this dev machine (macOS/AVFoundation), settings are applied via
  `uvc-util` (must be on `PATH` or set `UVC_UTIL_PATH`), not `cv2.set`.
- `white-balance-temp` maxes out at **6500K** on this camera — values above
  that get clamped by the driver.
- After committing new lock values, re-capture the classification detection
  baseline (`calibrate_classification_baseline.py --wipe`) — the old
  envelope is invalid once exposure/WB change.
