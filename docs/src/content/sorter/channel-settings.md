---
layout: default
title: Channel settings
type: reference
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-channel-settings
kicker: SorterOS — Operate
author: reveryx
lede: What is on the Settings page of each C-channel, and the Picture, Detection and LED panels above its camera view. Use it to change a channel's camera, picture, detection model or lamp, or to turn its rotor by hand.
permalink: /sorter/channel-settings/
warning: >-
  **AI-generated first draft.** Written from SorterOS's own source, not from
  a running machine. It has no screenshots yet.
---

Each channel has its own page under **Settings**, in the **Hardware** group of the side menu: **C-channel 1**, **C-channel 2**, **C-channel 3** and **Classification channel**. They are where you set up a channel's camera and lamp and where you turn its rotor by hand.

<ul class="bulleted-list">
  <li><strong>C-channel 1</strong> has no camera. Its page is the rotor controls only.</li>
  <li><strong>C-channel 2</strong>, <strong>C-channel 3</strong> and <strong>Classification channel</strong> have a camera view with the channel's zones on it, the <strong>Picture</strong>, <strong>Detection</strong> and <strong>LED</strong> panels, and the rotor controls under the view. The Classification channel page adds a <strong>C4 sectors</strong> panel at the bottom and a <strong>StallGuard</strong> entry under it in the side menu.</li>
</ul>

<div class="img-placeholder">Screenshot of the C-channel 2 settings page: the camera view with the Change camera, Picture, Detection and LED buttons above it, the Zones panel beside it, and the rotor controls underneath.</div>

## The camera view

The line above the view shows which camera the channel uses (**Camera 0**, for example) and the buttons for it.

<ul class="bulleted-list">
  <li><strong>Change camera</strong> opens <strong>Choose the camera for</strong> that channel, with a live preview of every USB camera the machine finds. Press a camera to use it. The camera in use is marked <strong>Active</strong>. A camera another channel already uses is marked with that channel's name, and pressing it asks <strong>Move the camera?</strong>, because moving it takes it off the other channel. <strong>Remove the camera</strong> clears the channel's camera, and <strong>Refresh</strong> looks for cameras again. The change is saved as soon as you pick.</li>
  <li><strong>Choose a camera</strong> appears in place of the camera name when the channel has none yet.</li>
  <li>The two buttons at the top right of the view hide or show the <strong>annotations</strong> and the <strong>zones</strong> drawn on it.</li>
</ul>

**Picture**, **Detection** and **LED** each open a panel beside the view, in place of the **Zones** panel. Press the same button again, or the close button on the panel, to go back to **Zones**. All three buttons, and **Change camera**, are unavailable while you are editing zones.

## Zones

The **Zones** panel beside the view has **Find** and **Edit** buttons. Drawing the drop, precise and exit zones is the same as in setup: see [Review zone]({{ '/sorter/first-setup/' | relative_url }}#review-zone). **Edit** needs a camera on the channel and says **Choose a camera before setting the zones** otherwise. A saved zone is used from the machine's next picture on.

While the machine is running and has handed pieces on from the channel, the panel also says how long half of the last pieces took to land on the next channel.

## Picture

**Picture** opens a panel with three parts: the capture mode, the camera's own controls, and the orientation. The view updates while you change the camera's controls and the orientation, so you can judge the result before saving.

### Capture mode

<ul class="bulleted-list">
  <li><strong>Mode</strong> lists the resolutions and frame rates the camera offers, such as one size at a given number of fps. <strong>Live</strong> at the top right shows what the camera is delivering now.</li>
  <li><strong>Pixel format</strong> is <strong>MJPG</strong> unless the camera needs another. MJPG is compressed and uses about a tenth of the USB bandwidth of the uncompressed format, and a camera that offers MJPG is only shown MJPG modes.</li>
</ul>

Both are saved the moment you pick them, with no **Save** button, and the camera reopens at the new mode. The panel says the camera does not offer a choice when it cannot, and a camera that is a network stream has no choice of resolution. Which mode to use per channel is in [Picture tuning]({{ '/sorter/first-setup/' | relative_url }}#picture-tuning), and [a camera only offers small modes]({{ '/sorter/troubleshooting/' | relative_url }}#cameras-a-camera-only-offers-small-modes-or-runs-at-5-fps) covers a camera stuck on small ones.

### Manual settings

Open **Manual settings** to adjust the camera's own controls. Only the controls the camera exposes are shown, from this list:

<ul class="bulleted-list">
  <li><strong>Auto Exposure</strong>, <strong>Exposure</strong> and <strong>Gain</strong></li>
  <li><strong>Brightness</strong>, <strong>Contrast</strong>, <strong>Saturation</strong> and <strong>Sharpness</strong></li>
  <li><strong>Auto White Balance</strong> and <strong>White Balance Temperature</strong> (in kelvin)</li>
  <li><strong>Autofocus</strong> and <strong>Focus</strong></li>
</ul>

Each number has a slider with minus and plus buttons. Changes reach the camera as you move them but are kept only when you press **Save**. If the camera has no adjustable controls, the panel says so instead. A network-stream camera never has any.

**Reset the camera to auto** puts the camera back on automatic exposure, white balance and focus and clears the manual settings. It takes effect at once, without **Save**.

### Orientation

<ul class="bulleted-list">
  <li><strong>Rotate</strong> turns the picture to <strong>0°</strong>, <strong>90°</strong>, <strong>180°</strong> or <strong>270°</strong>.</li>
  <li><strong>Flip horizontally</strong> and <strong>Flip vertically</strong> mirror it.</li>
</ul>

The camera view shows the turn or flip before it is saved.

### Saving

At the foot of the panel:

<ul class="bulleted-list">
  <li><strong>Save</strong> keeps the orientation and the manual settings. It is unavailable until something has changed. The panel closes and the line above the view says <strong>Picture settings saved.</strong></li>
  <li><strong>Undo the changes</strong> returns to what was last saved.</li>
  <li><strong>Back to the defaults</strong> sets the orientation to 0° with no flips and the manual settings to their defaults. Press <strong>Save</strong> to keep it.</li>
</ul>

Closing the panel without saving drops the unsaved changes and puts the camera back as it was.

### When the camera's settings drift

While the panel is open, SorterOS compares the camera's actual values with the saved ones every ten seconds. If they differ, a window titled **The camera's settings drifted** lists each setting with its **Saved** and **Live** value and asks which the camera should use.

<ul class="bulleted-list">
  <li><strong>Keep the live values</strong> saves what the camera reports now.</li>
  <li><strong>Restore the saved values</strong> sends the saved values back to the camera.</li>
  <li><strong>Ignore</strong> closes the window and leaves both as they are. It stays closed until the difference changes.</li>
</ul>

## Detection

**Detection** opens a panel titled for the channel, with one field.

<ul class="bulleted-list">
  <li><strong>Detection model</strong> picks the model that finds pieces on this channel. The list holds the models installed on the machine. Each of C-channel 2, C-channel 3 and the Classification channel has its own. The choice is saved as soon as you pick it, and the panel says <strong>Detection model saved.</strong> The field is empty and unavailable until a model is installed; the panel then says to install one from <strong>Settings</strong> → <strong>Hive</strong>. <a href="{{ '/sorter/before-first-sort-run/' | relative_url }}">Before your first sort run</a> covers the model a new machine installs for itself.</li>
  <li><strong>See the live detection results</strong> opens the <a href="{{ '/sorter/perception-debug/' | relative_url }}">Perception debug</a> page, which draws what the detector sees on each channel.</li>
</ul>

## LED

**LED** opens a panel for the lamp in the channel's hood. A change applies as you make it, with no **Save** button.

<ul class="bulleted-list">
  <li><strong>Output</strong> is the board output that drives this channel's lamp, listed as the board and its <strong>GPIO</strong> number. <strong>Not assigned</strong> leaves the lamp off. Channels can share an output: they are one physical pin, so they share one brightness, and the panel says which channels share it.</li>
  <li><strong>Brightness</strong> is the output's duty from 0% to 100%. <strong>0% is off</strong>; there is no separate switch. The slider is unavailable until an output is picked. Picking an output that is already in use keeps the brightness it is running at; a free one starts at 100%.</li>
</ul>

The panel says <strong>No LED outputs are free to assign right now</strong> when the machine's hardware is not up. [Lamps: a camera lamp stays dark]({{ '/sorter/troubleshooting/' | relative_url }}#lamps-a-camera-lamp-stays-dark) covers that and which port is which GPIO.

## The rotor controls

Under the camera view (and on its own on C-channel 1) is the panel for the channel's rotor, titled **C-channel 1**, **C-channel 2**, **C-channel 3** or **Classification C-channel (C4)**.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>These controls turn the motor.</strong> A press moves the rotor at once, whether or not a sort is running, and the arrow keys do the same (below). Keep hands and tools out of the channel, and press <strong>Stop</strong> to halt it.</p>
</div>

### Status

Next to the name there is a badge (<strong>Stopped</strong>, <strong>Moving</strong> or <strong>Unknown</strong>) and a position line. On the channel pages the badge reads <strong>Unknown</strong> and the position shows <strong>--</strong>, because these pages have no endstop to read a live position from.

### Moving it by hand

<ul class="bulleted-list">
  <li><strong>CCW</strong> and <strong>CW</strong> turn the rotor counterclockwise or clockwise. <strong>Stop</strong>, between them, halts this motor. The line below them says what the last press did, such as <strong>Pulsing clockwise.</strong></li>
  <li><strong>Each press moves</strong> chooses how far a press goes: <strong>Time</strong> runs the motor for a number of seconds, and <strong>Degrees</strong> turns the rotor by an angle. The time can be 0.05 to 120 s and the angle 1° to 3600°. It starts at 0.25 s in Time mode and 90° in Degrees mode.</li>
  <li><strong>Speed</strong> is in steps per second. It starts at 800.</li>
  <li>In <strong>Degrees</strong> mode the angle is at the rotor. A line under the controls shows the gear ratio (about 10.83:1 for the C-channels) and the matching angle at the motor.</li>
  <li>The left and right arrow keys press <strong>CCW</strong> and <strong>CW</strong> while you are on the page, unless the cursor is in a field or a button has focus.</li>
</ul>

The mode, time, angle and speed are remembered for each motor in your browser.

A press is refused while the machine is homing or starting up, or while a power stress test is running. If it says <strong>Hardware not started. Press Start in the dashboard first.</strong>, the motors are not up yet.

### Stalled motors

If the motor's stall detection halts it, a red notice titled for the channel, such as **C-channel 2 stalled**, appears with a **Clear the stall** button. Clear the jam first, then press it. The motor's home position was dropped, so home it again before precise moves.

### Driver settings

**Driver settings** (shown as "Currents, microsteps, stall detection") opens the motor driver's settings. The driver is read when you open it.

<ul class="bulleted-list">
  <li><strong>Run current</strong> and <strong>Hold current</strong> are each 0 to 31, set with a slider or a number.</li>
  <li><strong>Microstepping</strong> is 1/1 up to 1/256.</li>
  <li><strong>StealthChop</strong> and <strong>CoolStep</strong> are tick boxes.</li>
  <li><strong>Invert the direction</strong> reverses which way <strong>CW</strong> turns the rotor.</li>
  <li><strong>StallGuard stall detection</strong> halts the machine if this motor stalls, on every move while it is on. Ticked, it shows a <strong>Threshold (SGTHRS)</strong> from 0 to 255 and a <strong>Speed floor (TCOOLTHRS)</strong>, and states the reading at which it trips. If automatic tuning is on, those two are set by it and only shown. On the Classification channel the <strong>StallGuard</strong> tab in the side menu is where the threshold is tuned.</li>
</ul>

Nothing changes until you press **Apply the driver settings**. Under it, **Driver status (DRV_STATUS)** shows what the driver reports: overheating, short and open coil flags, standing still, current, the stall reading and the temperature band. Defaults for the currents are in the [machine.toml reference]({{ '/sorter/machine-toml-reference/' | relative_url }}). The direction can also be checked in [Motion direction check]({{ '/sorter/first-setup/' | relative_url }}#step-4-motion-direction-check) during setup.

## C4 sectors

The Classification channel page ends with a **C4 sectors** panel. It reads the classification camera's latest detection and shows which of the channel's five sectors, **S1** to **S5**, hold a piece. It does not move anything.

<ul class="bulleted-list">
  <li><strong>Scan</strong> reads a fresh result. The panel scans once when the page opens and does not update on its own, so press <strong>Scan</strong> to refresh it.</li>
  <li>Each sector shows <strong>Occupied</strong>, <strong>Handoff</strong>, <strong>Exit</strong> or <strong>Free</strong>, with its <strong>Detections</strong> count and best <strong>Confidence</strong>.</li>
  <li>The line above the sectors shows the <strong>Phase</strong> (the offset in degrees of the five walls, or n/a when they could not be found), the frame size, <strong>N of 5 occupied</strong> and the time of the scan.</li>
  <li>The figures below give the number of <strong>Candidates</strong> and <strong>Detections</strong> and which sectors are <strong>Handoff</strong> and <strong>Exit</strong>.</li>
</ul>

A warning above the sectors says why a scan failed, for instance when the classification channel has not completed a detection yet.
