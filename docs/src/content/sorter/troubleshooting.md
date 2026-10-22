---
layout: default
title: SorterOS troubleshooting
type: troubleshooting
slug: sorter-troubleshooting
kicker: SorterOS — Operations
lede: Symptom-led entries for install, first-run, and runtime problems. Search this page (Cmd-F) for the error message you are seeing.
permalink: /sorter/troubleshooting/
warning: >-
  **SorterOS changes quickly.** This page describes what each fix does, but a
  button's name, or where it is, may have changed since this page was written,
  so it keeps screenshots to a minimum.
---

Each entry: what you see → cause → fix → how to verify. For the install procedure itself, see [Installation]({{ '/sorter/installation/' | relative_url }}).

## First boot {#first-boot}

These are for [the SorterOS image]({{ '/sorter/installation/sorter-os/' | relative_url }}). While it sets up, the Pi serves a progress page at `http://sorter.local` that lists every stage, and next to a stage that is stuck, the reason.

### `sorter.local` doesn't open

**Cause:** The browser changed the address to `https://`, and the machine only answers on `http://`. This also stops the IP address from loading, even when your router lists the Pi. Otherwise: mDNS only works on the Pi's own network, older Windows needs Bonjour for it, and a second machine on the same network running the SorterOS image answers at `sorter-2.local`.

**Fix:** Type the whole address, `http://sorter.local`, and check the address bar has not added an `s`. If it still doesn't open, browse from a device on the same network, or find the Pi in your router's list of connected devices and use its IP address, again starting with `http://`.

**Verify:** The progress page or the SorterOS UI loads.

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

**Verify:** The SorterOS UI or the first-boot progress page loads.

### The WiFi entered in SorterOS Setup was wrong

**Cause:** A typo, or the network changed.

**Fix:** Nothing to reflash. The Pi opens its `SorterOS-Setup-` network within a minute; join it from a phone. The page says why the first try failed; enter the right password.

**Verify:** The setup network disappears and the Pi answers at `http://sorter.local`.

### `tailscale-up` shows ✕

**Cause:** The Tailscale key was rejected (expired, already used, or not allowed the `tag:sorter` tag). After ten tries the Pi stops trying. The SorterOS UI is not affected.

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

**Verify:** `curl -fsS http://localhost:8000/health` returns JSON.

---

## Setup wizard: you need to open it again

**Cause:** The wizard only opens by itself the first time you open the UI. To get back to it, after flashing the control board or to redo a step such as the cameras, you open it yourself.

**Fix:** Open **Settings** → **General** and press **Open the setup wizard**. Or add `/setup` to the machine's address: `http://sorter.local/setup`. The wizard remembers how far you got.

**Verify:** The wizard's steps show along the top of the page.

---

## Setup wizard: `No MCU buses found` at Controller Discovery

The wizard's Controller Discovery step lists no controllers, and the issue banner reads `No MCU buses found`.

**Cause:** Discovery only enumerates USB serial devices with the Pico's firmware VID/PID (`2e8a:000a`). A Pico that has never been flashed has empty flash, so it boots into its own USB bootloader and enumerates as an `RPI-RP2` mass-storage device instead. It is invisible to discovery until the control board firmware is on it. This is normal for a freshly built machine, not a fault.

**Fix:** Flash the control board before running the wizard, as [the SorterOS page]({{ '/sorter/' | relative_url }}#flash-the-control-board-before-the-wizard) describes. For a blank board, go to **Settings → Control board**, tick the **Recovery flash** checkbox (labelled "board is already in bootloader (RPI-RP2), or blank"), pick the release asset for that board, and flash. Do one board at a time. The job mounts the `RPI-RP2` drive itself. Then return to the wizard and press **Rescan**.

**Verify:** `ls /dev/ttyACM*` lists a device per board, and Controller Discovery shows each one with a **Controller** badge.

---

## Pico boards not detected (`permission denied` on `/dev/ttyACM*`)

**Cause:** udev rule not installed, or your user is not in the `plugdev` group and you are not on the active desktop seat (e.g. headless/SSH session).

**Fix:** Re-run `install.sh`, or by hand: `sudo cp software/systemd/99-sorter-pico.rules /etc/udev/rules.d/ && sudo usermod -aG plugdev $USER && sudo udevadm control --reload-rules && sudo udevadm trigger`. Unplug and replug. For headless/SSH, log out and back in so the group takes effect.

**Verify:** `ls -l /dev/ttyACM*` shows the device owned by `root:plugdev` with mode `0660`, and `id` lists `plugdev` for your user.

---

## Cameras: a camera only offers small modes, or runs at 5 fps

In the camera's **Picture** panel (**Picture tuning** in the setup wizard), the **Mode** list has nothing at 1280x720, only small sizes such as 640x480 at 5 fps down to 160x120. Or the size and frame rate in the bottom-right corner of its live view are well below [the modes in first setup]({{ '/sorter/first-setup/' | relative_url }}#picture-tuning). At 5 fps a channel misses small pieces such as Technic pins and pushes them on without seeing them.

**Cause:** A slow USB link, not a faulty camera. The cameras on the hub share one cable to the Orange Pi, and when that link drops to its slowest speed, every camera on the hub only offers the small modes. A damaged cable between the hub and the Orange Pi has caused it. If whichever camera you plug into the hub gets the short list, it is the link.

**Fix:** In order, checking the mode list after each:

<ol class="numbered-steps">
  <li>Push every USB plug fully home: each camera's lead at the camera and at the hub, and the hub's cable at both ends. The hub's power light should be on, and the light beside each camera's port steady.</li>
  <li>Check the hub's cable goes into the Orange Pi's blue USB 3 port.</li>
  <li>Replace the cable between the hub and the Orange Pi. The one that comes with the hub is easily damaged while routing it.</li>
  <li>Plug the slow camera straight into a free USB port on the Orange Pi instead of the hub. Move one camera, not all of them: the hub has its own power so the cameras don't pull the Orange Pi's voltage down (<a href="{{ '/lab/usb/' | relative_url }}">why</a>).</li>
</ol>

After moving any camera, check each channel's page in **Settings** still shows its own camera. If not, press **Change camera** and pick the right one.

**Verify:** The **Mode** list offers 1280x720 at 30 fps, and the corner of the live view shows it once picked.

---

## Lamps: a camera lamp stays dark

A lamp stays off with its channel's **LED** panel set, or the panel's **Output** list is empty and says "No LED outputs are free to assign right now". The housing fan often stays still as well, because it runs off an LED port too.

**Cause:** No LED port switches on by itself. Each one stays off until a channel has that port's output picked, and there are no outputs to pick until the machine's hardware is up. Once the board is switching the port, the fault is in the lamp's lead: the barrel plug and socket if you fitted them, a crimp, or the wires reversed.

**Fix:** In order, checking the lamp after each:

<ol class="numbered-steps">
  <li><strong>If the Output list is empty,</strong> look at the machine's state in the top bar. In <strong>Standby</strong> or <strong>Error</strong> there are no outputs to offer. Open the menu there and pick <strong>Home</strong>, or <strong>Initialize without homing</strong> if you only want the lamps. Once it says <strong>Ready</strong> or <strong>Initialized</strong>, close the LED panel and open it again. Still empty in <strong>Ready</strong>: check the firmware version on <strong>Settings → Control board</strong>; it has to be v0.8.0 or newer.</li>
  <li><strong>Pick the output for each lamp.</strong> On each channel's page in <strong>Settings</strong> (<strong>C-channel 2</strong>, <strong>C-channel 3</strong>, <strong>Classification channel</strong>), press <strong>LED</strong>, pick the <strong>Output</strong> for the port that channel's lamp is plugged into, and set <strong>Brightness</strong> above 0%. <code>J8</code> and <code>J9</code> are <strong>GPIO 1</strong>; <code>J10</code> and <code>J11</code> are <strong>GPIO 6</strong>. Brightness with no output picked does nothing, and the housing fan only runs while some channel has <strong>GPIO 6</strong>.</li>
  <li><strong>Check each plug at the board:</strong> red to <code>+V</code>, black to <code>GND</code>, as in <a href="{{ '/hardware/electronics/connecting/' | relative_url }}#step-4">connecting the components, step 4</a>.</li>
  <li><strong>See whether the board is switching the port.</strong> With the lamp plugged in and a multimeter on DC volts, put the probes on the lamp's two wires where they meet the strip. Read it with <strong>Brightness</strong> at 0%, then at 100%. About 0 V then about 24 V means the board is switching it and the fault is in the lead; carry on below. The same reading at both settings means the board is not switching that port: <a href="#escalate">escalate</a>. Measure across the two wires, not from one wire to ground: the red wire has 24 V on it all the time, so 24 V there proves nothing.</li>
  <li><strong>If you fitted the barrel plug and socket in the lamp's lead,</strong> take them out and join the lamp's wires to the board cable directly, red to red and black to black.</li>
  <li><strong>Check the rest of the lead:</strong> tug each crimp and look for a wire that pulls out, check each wire beeps through end to end on the <a href="{{ '/hardware/helpers/multimeter/' | relative_url }}#continuity-for-tracing-a-cable">continuity setting</a>, and check red goes to the strip's <code>+</code> and black to its <code>-</code>.</li>
</ol>

**Verify:** Each lamp comes on at the brightness you set, and the housing fan runs.

---

## Chute: the endstop always reads triggered, or never does

The chute's endstop reading does not follow the switch. It shows on the **Chute endstop** row in [step 5 of the setup wizard]({{ '/sorter/first-setup/' | relative_url }}#step-5-chute-endstop-and-geometry), as **Endstop triggered** or **Endstop clear** on **Settings → Chute**, and as **Endstop** on the **Chute aiming** tab.

<ul class="bulleted-list">
  <li><strong>Always triggered:</strong> homing stops at once, wherever the chute happens to be, and calls that home. Every bin is then off, and the <strong>Chute aiming</strong> jog will not take the chute below that false 0°.</li>
  <li><strong>Never triggered:</strong> homing turns the chute without stopping at the switch, then gives up with "Chute homing stopped before the endstop triggered". If the chute keeps turning, press <strong>Stop the motion</strong> in the wizard or <strong>Cancel</strong> on <strong>Settings → Chute</strong>.</li>
</ul>

**Cause:** The lead is wired so the circuit is closed while the lever is free and opens when the chute presses it. Anything that breaks the circuit therefore reads exactly like a pressed switch, so **always triggered is nearly always a connection**, not the switch: a crimp, the housing on the board the wrong way round, or a wire broken where the lead flexes.

**Fix:** To move the chute while you work on it, use **CCW** and **CW** on **Settings → Chute**. They move it whatever the endstop reads, and without homing. Then, in order:

<ol class="numbered-steps">
  <li><strong>Press the switch's lever by hand and watch the reading.</strong> If it changes, but the wrong way round (triggered while free), press <strong>Flip the polarity</strong> in wizard step 5. If it never changes, carry on.</li>
  <li><strong>Check the hammer and the lever.</strong> Nothing should rest on the lever, and the chute's hammer should press the roller as the chute reaches home.</li>
  <li><strong>Check the housing on <code>J5</code>.</strong> It is not keyed. The empty position goes over the pin the board marks <code>3.3V</code>; turned over, the machine never sees the switch change. <a href="{{ '/hardware/helpers/limit-switch-lead/' | relative_url }}#putting-the-housing-on-the-board">Putting the housing on the board</a>.</li>
  <li><strong>Check the crimps.</strong> Tug each wire where it enters the housing and at each receptacle on the switch. Re-crimp any that pulls out or moves.</li>
  <li><strong>Meter the lead.</strong> Unplug the housing from the board and put a multimeter on its two contacts on the <a href="{{ '/hardware/helpers/multimeter/' | relative_url }}#continuity-for-tracing-a-cable">continuity setting</a>. It should beep with the lever free and go silent when you press it. Silent both ways: the break is in the lead or the switch, so check each wire end to end. Silent while free and beeping while pressed: the receptacles are on <code>COM</code> and <code>NO</code>, so move one along to <code>NC</code>. Beeping both ways: strands are crossing at a crimp. <a href="{{ '/hardware/helpers/limit-switch-lead/' | relative_url }}#check-the-lead">Checking the lead</a>.</li>
</ol>

**Verify:** The reading flips each time you press and release the lever, and **Find the chute endstop** turns the chute counter-clockwise, seen from above, until it reaches the switch.

---

## Flaps: a flap will not reach open or closed, or its servo spins freely

On **Settings → Storage layers**, a flap stops short of lying flat in the chute wall or of crossing the chute, and the arrows will not take it further. Or a flap that locked fine before has drifted, so pieces bounce past a closed one. Or the angle between the arrows changes but the flap does not move, or it flops loosely.

**Cause:** The flap is coupled to its MG995 servo through the plastic horn inside the servo adapter. Forcing the flap, by hand or by leaving the servo pushing against the chute wall, does one of two things:

<ul class="bulleted-list">
  <li><strong>The horn's teeth round off</strong> and it slips on the servo's shaft, a few teeth at a time. The flap's swing then sits partly outside the servo's 0° to 180°, so one end is out of reach. Nothing in the software can move the servo further than that.</li>
  <li><strong>The servo breaks.</strong> It spins freely, or does not move at all.</li>
</ul>

**Fix:** In order:

<ol class="numbered-steps">
  <li><strong>Take the servo bracket off the chute core:</strong> the 2 M3x12 countersunk screws through the side arm and the 1 through the lower arm, as in <a href="{{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}">the door module, step 8</a>. Draw the bracket back so the servo adapter comes off the flap's hex.</li>
  <li><strong>Look at the horn's splined sleeve</strong> in the middle of the adapter's servo side. If its teeth are worn round, rebuild the adapter around a fresh horn from the servo's bag.</li>
  <li><strong>If the servo spins freely, or no longer moves with the arrows, replace it.</strong> Take out the cover's 2 screws, slide the servo out and the new one in, and plug it into the same socket on the layer adapter board. Do the cover screws up evenly: they are all that holds the servo.</li>
  <li><strong>Set the servo to 0°.</strong> With the adapter off the flap, press the left arrow (<strong>Move toward a lower angle</strong>) until the angle between the arrows reads 0°. It holds there while the machine is on.</li>
  <li><strong>Re-couple with the flap fully open.</strong> Push the adapter onto the servo's spline and drive the small screw from the servo's bag into the middle of the horn, through the hex socket, so the horn cannot creep off the spline. Hold the flap flat in the chute wall and bolt the bracket back on with the hex going onto the flap's shaft. If the hex will not line up, take the screw out and turn the adapter one tooth on the spline. 0° with the flap open matters: each time the machine starts, it swings every flap to 0° on the way to opening it.</li>
  <li><strong>Lock open and closed again</strong> for that layer. The old angles no longer apply.</li>
</ol>

**Verify:** The layer reads **Calibrated**, the flap lies flat at open and crosses the chute at closed, and the servo is quiet at both.

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
- Re-measure `first_bin_center` and update `[chute]` in `software/machine.toml`.
- If steppers skip: lower the move speed or raise `[stepper_current_overrides.chute_stepper] irun` (max 31).

**Verify:** Send 50 parts to bin 0 from the test panel — all land in the same physical bin.

---

## Hive uploads pile up and never drain

**Cause:** Wrong URL/token, or Hive is unreachable from this machine. The uploader keeps samples on disk and backs off — nothing is dropped.

**Fix:** Test with `curl -fsS "$HIVE_URL/api/health"`. If that fails, fix the network. If it returns but uploads still 401, the token is wrong. Set both under **Settings → Hive** in the UI (stored in the backend's `local_state.sqlite`, not `.env`).

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
