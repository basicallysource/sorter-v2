---
layout: default
title: Sorter troubleshooting
type: troubleshooting
slug: sorter-troubleshooting
kicker: Sorter — Operations
lede: Symptom-led entries for install, first-run, and runtime problems. Search this page (Cmd-F) for the error message you are seeing.
permalink: /sorter/troubleshooting/
---

Each entry: what you see → cause → fix → how to verify. For the install procedure itself, see [Installation]({{ '/sorter/installation/' | relative_url }}).

## First boot {#first-boot}

These are for [SorterOS]({{ '/sorter/installation/sorter-os/' | relative_url }}). While it sets up, the Pi serves a progress page at `http://sorter.local` that lists every stage, and next to a stage that is stuck, the reason.

### `sorter.local` doesn't open

**Cause:** mDNS only works on the Pi's own network, older Windows needs Bonjour for it, and a second SorterOS machine on the same network answers at `sorter-2.local`.

**Fix:** Browse from a device on the same network, or find the Pi in your router's list of connected devices and use its IP address.

**Verify:** The progress page or the Sorter UI loads.

### A stage says `waiting for internet`

**Cause:** The Pi is on a network, but the internet doesn't answer through it: an Ethernet port with no upstream, or a WiFi network that doesn't reach the internet. Within about a minute the Pi opens its `SorterOS-Setup-` network so you can give it one that does.

**Fix:** Plug the Pi into a port on your router, or join `SorterOS-Setup-` from a phone and pick a WiFi network that reaches the internet.

**Verify:** The stage moves on within a minute.

### No `SorterOS-Setup-` network appears

**Cause:** The Pi only opens it when the internet doesn't answer through any network it's on. If a cable or the WiFi you gave it gets it online, there's nothing to set up. Otherwise it's been less than about half a minute since power-on (a minute while a cable or a saved WiFi network is still trying), or the board has no WiFi (see the [Orange Pi 5 page]({{ '/hardware/orange-pi-5/' | relative_url }}#wifi)).

**Fix:** Look for the Pi on your network at `http://sorter.local` first. If it isn't there, wait a minute with no cable in, or use Ethernet.

**Verify:** The network shows up in your phone's WiFi list.

### Your network isn't in the setup page's list

**Cause:** A network that's off, out of range of the Pi, or hidden isn't listed. Until the Pi knows your time zone it listens on every channel but doesn't call out on the ones it isn't sure your country allows, so a hidden network on 5 GHz can't be found yet.

**Fix:** Tap **Refresh**. If it's still missing, choose **Other network** and type its name exactly (spaces and capitals count). If your router has separate 2.4 GHz and 5 GHz networks and the 5 GHz one isn't found, pick the 2.4 GHz one; the Pi learns your country from the setup page, so the 5 GHz one works from its next start.

**Verify:** The page says **Your Sorter is on** your network.

### **Find my sorter** keeps waiting

**Cause:** The network the Pi joined doesn't reach the internet, so it can't report its address, or it came online more than 15 minutes ago, after which it stops reporting.

**Fix:** Use the address the setup page showed when the Pi joined. If you didn't note it, browse to `http://<name>.local` (the name you gave it, `sorter` if you didn't), find the Pi in your router's list of connected devices, or join `SorterOS-Setup-` again if it's in your phone's WiFi list: the page shows where the Pi is.

**Verify:** The Sorter UI or the first-boot progress page loads.

### The WiFi entered in SorterOS Setup was wrong

**Cause:** A typo, or the network changed.

**Fix:** Nothing to reflash. The Pi opens its `SorterOS-Setup-` network within a minute; join it from a phone. The page says why the first try failed; enter the right password.

**Verify:** The setup network disappears and the Pi answers at `http://sorter.local`.

### `tailscale-up` shows ✕

**Cause:** The Tailscale key was rejected (expired, already used, or not allowed the `tag:sorter` tag). After ten tries the Pi stops trying. The Sorter UI is not affected.

**Fix:** Connect Tailscale from the UI's **Settings** later.

**Verify:** The machine shows up in your Tailscale admin console.

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

## Setup wizard: `No MCU buses found` at Controller Discovery

The wizard's Controller Discovery step lists no controllers, and the issue banner reads `No MCU buses found`.

**Cause:** Discovery only enumerates USB serial devices with the Pico's firmware VID/PID (`2e8a:000a`). A Pico that has never been flashed has empty flash, so it boots into its own USB bootloader and enumerates as an `RPI-RP2` mass-storage device instead. It is invisible to discovery until the control board firmware is on it. This is normal for a freshly built machine, not a fault.

**Fix:** Flash the control board before running the wizard, as [Software setup]({{ '/hardware/software-setup/' | relative_url }}) describes. For a blank board, go to **Settings → Control board**, tick the **Recovery flash** checkbox (labelled "board is already in bootloader (RPI-RP2), or blank"), pick the release asset for that board, and flash. Do one board at a time. The job mounts the `RPI-RP2` drive itself. Then return to the wizard and press **Rescan**.

**Verify:** `ls /dev/ttyACM*` lists a device per board, and Controller Discovery shows each one with a **Controller** badge.

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
