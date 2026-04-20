---
layout: default
title: Sorter troubleshooting
type: troubleshooting
slug: sorter-troubleshooting
kicker: Sorter — Operations
lede: Symptom-led entries for install, first-run, and runtime problems. Search this page (Cmd-F) for the error message you are seeing.
permalink: /sorter/troubleshooting/
---

Each entry: what you see → cause → fix → how to verify. For the install procedure itself, see [Install on a Linux machine]({{ '/sorter/installation/' | relative_url }}).

## `.onnx` files are tiny — backend logs a malformed model error

`du -h software/sorter/backend/blob/local_detection_models/*.onnx` shows files of a few hundred bytes.

**Cause:** Git LFS was not initialized before the clone.

**Fix:** Re-run `software/install.sh`, or by hand: `git lfs install && git lfs pull`.

**Verify:** `du -h` reports MB, not bytes.

---

## `ImportError: libGL.so.1` on backend startup

**Cause:** `libgl1` missing — usually `install.sh --skip-apt` on a system that didn't have it.

**Fix:** `sudo apt install -y libgl1 libglib2.0-0` or re-run `install.sh` without `--skip-apt`.

**Verify:** `python3 -c "import cv2; print(cv2.__version__)"` prints the version.

---

## `Address already in use` on port 8000 or 5173

**Cause:** A wedged child from a previous run is still holding the port.

**Fix:** `pkill -f 'uvicorn|vite' && ./dev.sh`.

> Kills *all* uvicorn/vite processes on the box — name them more specifically if you run other servers.

**Verify:** `lsof -i :8000 -i :5173` prints nothing before you start `./dev.sh`.

---

## UI loads but clicks do nothing

**Cause:** Backend crashed during import; the SvelteKit app is talking to a dead server.

**Fix:** Read the `[backend]` lines in `./dev.sh`. The last line before the silence tells you which import failed. Fix that and restart.

**Verify:** `curl -fsS http://localhost:8000/api/health` returns JSON.

---

## Pico boards not detected (`permission denied` on `/dev/ttyACM*`)

**Cause:** udev rule not installed, or your user is not in the `plugdev` group and you are not on the active desktop seat (e.g. headless/SSH session).

**Fix:** Re-run `install.sh`, or by hand: `sudo cp software/systemd/99-sorter-pico.rules /etc/udev/rules.d/ && sudo usermod -aG plugdev $USER && sudo udevadm control --reload-rules && sudo udevadm trigger`. Unplug and replug. For headless/SSH, log out and back in so the group takes effect.

**Verify:** `ls -l /dev/ttyACM*` shows the device owned by `root:plugdev` with mode `0660`, and `id` lists `plugdev` for your user.

---

## Feeder camera sees a part but the MOG2 detector never triggers

**Cause:** Bootstrap window — each channel needs 24 frames of background before reporting detections, and the counter resets on any image-shape change. Or: the channel was rotating when the part landed (motion blur is suppressed on purpose).

**Fix:** Wait ~2 seconds after homing or any camera setting change before dropping a part. If detections come in late but never fire, raise `var_threshold` in `mog2_diff_configs`.

**Verify:** A part landing in the dropzone produces `feeder: idle -> feeding` in the log within ~500 ms.

---

## Carousel keeps rotating past the part — classification never completes

**Cause:** The classification detector returns `found=false` every attempt. Two real causes: OpenRouter API key missing or rate-limited, or the classification region polygon is misaligned with where the carousel actually presents parts.

**Fix:**
- Set `OPENROUTER_API_KEY` in `.env`, or lower `OPENROUTER_MAX_CONCURRENCY` from 10.
- Re-run the classification region calibration in the setup wizard.
- Last resort: switch `detection_algorithm` for the classification scope to a local algorithm.

**Verify:** A dropped part advances `idle -> detecting -> snapping` in under 2 seconds.

---

## Chute drift — parts land in the wrong bin after ~50 parts

**Cause:** Chute position is open-loop from the homing endstop. Drift comes from a flipped endstop polarity, a stepper skipping under bind, or stale `first_bin_center` / `pillar_width_deg` after a hardware change.

**Fix:**
- Re-home from **Hardware → Chute → Home**. The chute does *not* re-home between runs.
- Re-measure `first_bin_center` and update `[chute]` in `machine.example.toml`.
- If steppers skip: lower the move speed or raise `[stepper_current_overrides.chute_stepper] irun` (max 31).

**Verify:** Send 50 parts to bin 0 from the test panel — all land in the same physical bin.

---

## Hive uploads pile up and never drain

**Cause:** Wrong URL/token, or Hive is unreachable from this machine. The uploader keeps samples on disk and backs off — nothing is dropped.

**Fix:** Test with `curl -fsS "$HIVE_URL/api/health"`. If that fails, fix the network. If it returns but uploads still 401, the token is wrong. Set both under **Settings → Hive** in the UI (stored via `blob_manager`, not `.env`).

**Verify:** The pending queue drains at roughly one upload per second per worker.

---

## Classification samples all show `detection_found=false`

**Cause:** Chamber lighting drifted from the calibration baseline. Gemini in particular is fragile against clipped highlights or strong color casts.

**Fix:** Restore the lighting, or re-run the setup wizard's chamber lighting step. If ambient has genuinely changed, recalibrate colour from **Settings → Cameras**.

**Verify:** **Settings → Detection Test** returns `detection_found=true` with a plausible bbox.

---

## Escalate

If the symptom is not on this page, capture the following and open an issue:

```bash
./dev.sh 2>&1 | tee /tmp/sorter.log    # full backend + ui output from clean start
uname -a
git -C <repo> rev-parse HEAD
uv --version && node --version && pnpm --version
```

Include a one-line description of what you were doing when the symptom appeared.
