# ArUco Tracker

The ArUco tracker (`client/vision/aruco_tracker.py`) runs on a dedicated thread, detecting 4×4 ArUco markers in the feeder camera feed and producing both raw and smoothed position outputs.

## Detection Pipeline

1. **Frame acquisition** — reads the latest frame from the feeder `CaptureThread`; skips if the frame hasn't changed since last processing.
2. **Marker detection** — converts to grayscale and runs `cv2.aruco.ArucoDetector` with tuned parameters (see below).
3. **Outlier rejection** — compares each detected tag position to its last accepted position. If the jump exceeds `ARUCO_OUTLIER_MAX_JUMP_PX` (120 px) within `ARUCO_OUTLIER_REACQUIRE_TIMEOUT_S` (1.0 s), the detection is discarded. This prevents phantom jumps from misreads.
4. **Smoothing** — if `smoothing_time_s > 0`, raw positions are accumulated in a per-tag sliding window. The smoothed output is the mean of all positions within the window. A **persistence gate** delays smoothing activation: the tag must be tracked for at least `0.5 × smoothing_time_s` before the averaged position is used; until then, the raw position is returned.
5. **Cache** — recently-seen tags that are not detected in the current frame are kept in the output for up to `ARUCO_TAG_CACHE_MS` (100 ms) to bridge brief detection dropouts.
6. **Cleanup** — stale history entries, cache entries, and outlier-tracking records are pruned each cycle.

## Outputs

The tracker produces two dictionaries each cycle, both mapping `tag_id → (x, y)`:

| Output | Access method | Description |
|--------|--------------|-------------|
| **Raw tags** | `getRawTags()` | Accepted (post-outlier) positions without smoothing |
| **Smoothed tags** | `getTags()` | Smoothed positions (or raw if persistence gate hasn't passed) |

The vision manager annotates the feeder camera feed with smoothed positions. The raw positions can be overlaid on the MJPEG stream via `?show_live_aruco_values=true`.

## Tunable Constants

| Constant | Default | Description |
|----------|---------|-------------|
| `ARUCO_TAG_CACHE_MS` | 100 | How long a missed tag stays in the output (ms) |
| `ARUCO_UPDATE_INTERVAL_MS` | 120 | Minimum sleep between detection cycles (ms) |
| `ARUCO_OUTLIER_MAX_JUMP_PX` | 120.0 | Max allowed position jump before rejection (px) |
| `ARUCO_OUTLIER_REACQUIRE_TIMEOUT_S` | 1.0 | Time after which a tag is considered "new" and jump filtering resets (s) |

## Configurable Settings

The **smoothing window** is configurable at runtime via:
- The ArUco configuration GUI (Settings panel)
- `POST /api/aruco/smoothing?value=<seconds>` API endpoint
- The `aruco_smoothing_time_s` field in `aruco_config.json`

Setting smoothing to `0` disables the sliding window entirely and returns raw positions.

## Detector Parameters

The OpenCV ArUco detector is configured with these non-default parameters for reliable marker detection at varying distances:

```python
ARUCO_TAG_DETECTION_PARAMS = {
    "minMarkerPerimeterRate": 0.003,
    "perspectiveRemovePixelPerCell": 4,
    "perspectiveRemoveIgnoredMarginPerCell": 0.3,
    "adaptiveThreshWinSizeMin": 3,
    "adaptiveThreshWinSizeMax": 53,
    "adaptiveThreshWinSizeStep": 4,
    "errorCorrectionRate": 1.0,
    "polygonalApproxAccuracyRate": 0.05,
    "minDistanceToBorder": 3,
    "maxErroneousBitsInBorderRate": 0.35,
    "cornerRefinementMethod": 0,
    "cornerRefinementWinSize": 5,
}
```

The dictionary type is `DICT_4X4_50` (tag IDs 0–49).

## Integration

The tracker is instantiated and started by `VisionManager`:
- `VisionManager.getFeederArucoTags()` → smoothed positions (used for geometry calibration and annotation)
- `VisionManager.getFeederArucoTagsRaw()` → raw positions (used for the optional raw overlay)

Tag positions feed into the feeder subsystem's channel geometry analysis (`subsystems/feeder/analysis.py`), which uses configured tag assignments from `aruco_config.json` to compute circle/ellipse boundaries for object routing.
