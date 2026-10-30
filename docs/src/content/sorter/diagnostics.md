---
layout: default
title: Diagnostics
type: reference
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-diagnostics
kicker: SorterOS — Operate
author: jensr80
lede: The four diagnostic pages under Settings. Performance and Cycle time show how fast the machine is working and where each piece's time goes. The Jitter test and the Power stress test move motors on purpose.
permalink: /sorter/diagnostics/
warning: >-
  **AI-generated first draft.** Written from SorterOS's own source, not from
  a running machine. It has no screenshots yet, and the wording on the pages
  may have drifted since it was written.
---

All four pages are in the **Helpers** group of the **Settings** side menu, next to **Incidents**. On a phone the same pages are in the **Settings page** list at the top.

<ul class="bulleted-list">
  <li><strong>Performance</strong> and <strong>Cycle time</strong> only read. Opening them changes nothing and moves nothing.</li>
  <li><strong>Jitter test</strong> and <strong>Power stress test</strong> <strong>move motors</strong>. Read the warnings in their sections before you press anything.</li>
</ul>

## Performance

**Settings**, then **Performance**. It answers "how fast is this machine thinking, and how old is the camera data behind each decision?" Use it to compare two machines, or to spot a machine that has got slower than it was.

The header says which machine you are looking at, its state, and how long the current run has been going. The page refreshes itself every few seconds. A tile shows **–** until the machine has reported that number.

### Time range

The **Time range** control has **Live**, **1 min**, **5 min**, **15 min** and **60 min**. It starts on **5 min**.

It changes only the small line charts. The numbers in the tiles always cover the whole current run: rates are the run's total count divided by how long it has been running, and times are medians. The machine keeps about the last hour of chart history in memory.

### The tiles

Each number is colored green, amber or red. The limits below are the ones the page uses.

<ul class="bulleted-list">
  <li><strong>Decisions a second:</strong> how often the classification step runs. Green at 60 Hz or more, amber at 30 Hz or more.</li>
  <li><strong>Decision data age:</strong> how old the camera data is when a decision is made. Green at 150 ms or less, amber at 300 ms or less.</li>
  <li><strong>Control loop rate:</strong> how often the main control loop runs. The tile says <strong>Target 100</strong>. Green at 80 Hz or more, amber at 50 Hz or more.</li>
  <li><strong>GIL stall:</strong> how long the control loop waits on other work in the same program. Green at 5 ms or less, amber at 15 ms or less.</li>
  <li><strong>Perception</strong> has one row per camera that runs the detector, with <strong>Rate</strong> (detections a second), <strong>Infer</strong> (time for one detection), <strong>Cycle</strong> and <strong>Frame age</strong>. Rate is green at 15 Hz or more and amber at 8 Hz or more. Infer is green at 40 ms or less and amber at 80 ms or less. Frame age is green at 80 ms or less and amber at 160 ms or less. Cycle has no color. If no camera has reported yet the panel says <strong>No inference cameras are reporting yet.</strong></li>
  <li><strong>Subsystem step cost</strong> is the time each control tick spends in <strong>Distribution</strong>, <strong>Classification</strong> and <strong>Feeder</strong> (green at 2 ms or less, amber at 6 ms or less), and in <strong>Controller step</strong> (green at 4 ms or less, amber at 10 ms or less).</li>
  <li><strong>Throughput</strong> has <strong>Pieces a minute (5 min)</strong>, <strong>Pieces a minute (average)</strong>, <strong>Pieces seen</strong> and <strong>Distributed</strong>. These have no colors.</li>
</ul>

Red or amber on the data age, the control loop rate or the camera rows means the machine is deciding on stale information or running behind. The page does not say why.

### Compare to a past run

**Compare to a past run** puts the current session beside a finished run. Pick one from **Past run** (each is listed by its start time and piece count). A table then shows the same metrics for both. **None** clears it. With no finished runs the panel says **No saved runs yet.**

<div class="img-placeholder">Screenshot of the Performance page with the 5 min time range, showing the Decision loop tiles and one camera row.</div>

## Cycle time

**Settings**, then **Cycle time**. It shows where each piece's seconds go on the classification channel (C4). One cycle runs from the moment C4 asks the feeder for a piece to the moment it asks for the next. Use it to see whether pieces are slow because C4 itself is slow, or because it is waiting for the feeder to bring one.

Choose the **Time span**: **10 min**, **1 hour** (the default) or **Today**. The page refreshes every 10 seconds.

Cycles in which the machine was stopped (an incident held it, or the control loop did not run for a while) are left out of every figure and counted apart. The first tile says how many. A pause drops the cycle in progress, so a stop never shows up as a slow piece.

### The four tiles

<ul class="bulleted-list">
  <li><strong>Pieces a minute:</strong> pieces divided by the total time they took. Under it, the number of pieces and how many cycles were left out for stops. When the machine spent time waiting with nothing on C2 or C3, a second figure appears, <strong>while the hopper kept up</strong>: the rate it would have had without those waits.</li>
  <li><strong>Per piece, on average:</strong> the whole cycle, wait plus C4's work. The median is underneath.</li>
  <li><strong>C4's own work:</strong> from landing until C4 asks for the next piece.</li>
  <li><strong>Waiting for the feeder:</strong> from C4's ask until the next piece lands. Underneath, the median and the share of all waiting time that came from waits longer than 4 seconds.</li>
</ul>

### C4's own work

One row per phase, with the **Median**, the **Average** and the **Slowest 10%**:

<ul class="bulleted-list">
  <li><strong>Landing confirmed</strong></li>
  <li><strong>Photos</strong></li>
  <li><strong>Waiting for the piece ahead (classified, chute aimed)</strong></li>
  <li><strong>Turn (eject the piece ahead, stage this one)</strong></li>
  <li><strong>All of C4's own work</strong></li>
</ul>

### Waiting for the feeder

Each wait is sorted by where C3's next piece was at the moment C4 asked. The table shows how many asks fell in each case and their share, the median and average wait, the total seconds, and **C3 moving** and **Chute moving**: the share of the wait that C3, or the chute, was turning.

<ul class="bulleted-list">
  <li><strong>C3's next piece within 20° of its edge:</strong> about to drop.</li>
  <li><strong>20° to 80° from the edge</strong></li>
  <li><strong>More than 80° from the edge:</strong> a piece still in C3's landing area is most of a lap away.</li>
  <li><strong>Only out of view on C3:</strong> there is a piece on C3, but the camera cannot see it.</li>
  <li><strong>None on C3, some on C2</strong></li>
  <li><strong>None on C3 or C2: the hopper or C1:</strong> nothing is coming. Feed the machine.</li>
</ul>

### Longest waits

The 40 longest waits over 4 seconds in the span, longest first: when C4 asked, how long it waited, where C3's next piece was, how many pieces were on C3 and on C2, and **C3 moving** and **Chute moving** as shares of that wait. If there are none it says **No waits over 4 s.**

### Pieces C2 or C3 could not move

Lists pieces that a channel turned under and that stayed put, so the channel next to it was turned. After three turns the feeder gives up and sorts around the piece. Each row shows when, **Where** (C2 or C3, landing area or exit), **Held for**, **Turns**, and **How it ended**: **Moved again**, **Left the channel** or **Sorting stopped first**, with ", after the feeder gave up on it" where that happened. With none the panel says **None.**

<div class="img-placeholder">Screenshot of the Cycle time page on the 1 hour span, showing the four tiles and the C4's own work table.</div>

## Jitter test

**Settings**, then **Jitter test**. It gives one motor a short, sharp back-and-forth that breaks static friction, enough to nudge a stuck piece off a C channel without a violent shake. It ends where it started.

**This moves a motor as soon as you press Jitter.** Keep your hands and tools clear of the channel or chute you pick. Pressing a preset only fills in the settings and moves nothing.

The page does not check whether the sorter is running or paused. The backend refuses only while the hardware is homing or a power stress test is running, and while that motor is already moving or still jittering. If the hardware has not been started it answers that the hardware is not initialized.

### Run a jitter

<ol class="numbered-steps">
  <li>Under <strong>Motor</strong>, choose the motor: <strong>C-channel 1</strong>, <strong>C-channel 2</strong>, <strong>C-channel 3</strong>, <strong>C-channel 4</strong>, <strong>Classification C-channel (C4)</strong> or <strong>Chute</strong>.</li>
  <li>Optional: press a preset under <strong>Presets</strong>. The selected preset is highlighted when the settings match it.</li>
  <li>Check or edit the settings.</li>
  <li>Press <strong>Jitter</strong>. A message confirms what is running: it starts with <strong>Jittering</strong> and the motor, then gives the number of cycles, the stroke in motor degrees, and an estimated duration in seconds. If the backend refuses, an error message says why.</li>
</ol>

**Stop** sends a stop command to the selected motor. The backend runs a jitter to completion once it has started, so keep the cycle count small rather than relying on **Stop**. **Back to the defaults** puts the four settings back to their defaults and keeps the motor you chose. The page remembers its settings in this browser.

### The settings

<ul class="bulleted-list">
  <li><strong>Amplitude:</strong> how far each stroke goes, in degrees at the motor (default 6). The help text shows what that is at the rotor, because the gearing divides it: about 10.8 to 1 for the C channels and the classification channel, 4.8 to 1 for the chute. The backend refuses an amplitude so small it rounds to zero microsteps.</li>
  <li><strong>Cycles:</strong> back-and-forths (default 12). The backend accepts 1 to 5000.</li>
  <li><strong>Speed:</strong> in µsteps/s (default 5000).</li>
  <li><strong>Acceleration:</strong> in µsteps/s² (default 100000). Higher is a sharper jerk on each stroke.</li>
</ul>

### Presets

Each preset sets all four numbers: the amplitude is the travel, the cycles are the length, and the speed and acceleration are the strength. The page lists them with their numbers. **Heavy stuck** is the reference (6° amplitude, 12 cycles, 5000 µsteps/s, 100000 acceleration) and the others vary around it:

<ul class="bulleted-list">
  <li><strong>Shorter, same force:</strong> Quick stuck, Brief stuck.</li>
  <li><strong>Sharper and shorter:</strong> Sharp &amp; short, Hard snap.</li>
  <li><strong>Softer and longer:</strong> Soft &amp; long, Gentle marathon.</li>
  <li><strong>More travel:</strong> Big travel, Big &amp; brief, Big &amp; hard, Max shake, Wide &amp; soft.</li>
  <li><strong>Long and strong:</strong> Fast buzz, Strong &amp; long.</li>
</ul>

<div class="img-placeholder">Screenshot of the Jitter test page with the Motor field, the preset grid and the Settings panel.</div>

## Power stress test

**Settings**, then **Power stress test**. It runs the heaviest load the machine can make, so you can measure its draw at the wall (for example with a power meter on the supply). For what one run measured, see [A partial power stress run on Kitbash]({{ '/n/kvdd/' | relative_url }}).

**This moves everything at once**, for as long as you set (10 minutes unless you change it). Before you start, check that nothing is in the way of the chute, the channels or the servo arms.

### Before you start

The test refuses to start unless both of these are true:

<ol class="numbered-steps">
  <li><strong>The hardware is homed and ready.</strong> The hardware badge in the top bar must read <strong>Ready</strong>. If it does not, open the three-dot <strong>System</strong> menu in the top bar and choose <strong>Home</strong> (it says <strong>Re-home</strong> once the machine is ready). Wait for the badge to change to <strong>Ready</strong>. If you start the test earlier the page shows <strong>Cannot run power stress test while hardware is</strong> followed by the state, and says to run Safe Home first.</li>
  <li><strong>The sorter is paused.</strong> Press <strong>Pause</strong> in the top bar, so the button changes to <strong>Resume</strong>. Otherwise the page shows <strong>Pause the sorter before starting power stress</strong>, and tells you what state the sorter is in.</li>
</ol>

The test also needs the chute and the four channel steppers present, and the detection models running on every configured channel. If one is missing the page shows the reason, for example **Perception models are not running on every configured channel** or **Required steppers unavailable**.

### What it does

The chute homes itself first and then stays at or below the **Chute limit**. The lights go to 100% and are put back afterwards. C1 to C4 ramp their moves, and the servos use their whole 0° to 180°. Three phases follow in order, shown under **Sequence**:

<ul class="bulleted-list">
  <li><strong>1. Steady:</strong> the four channel steppers run without stopping, the chute sweeps from home to its limit, and the servos sweep end to end. Takes a third of the moving time.</li>
  <li><strong>2. Random:</strong> the steppers brake and burst either way, and the chute and the servos go to random targets. Takes a third of the moving time.</li>
  <li><strong>3. Mixed:</strong> short stretches mix steady and bursting steppers while the chute and the servos alternate. Takes the rest.</li>
</ul>

While it runs, manual motion on other pages (a pulse, a jitter) is refused with a message that power stress is active, and a separate chute stress test cannot be started.

### The settings

The fields are locked while a test is running.

<ul class="bulleted-list">
  <li><strong>Moving time:</strong> in minutes (default 10). The backend accepts 10 seconds to 60 minutes.</li>
  <li><strong>C1 to C4 top speed:</strong> in µsteps/s (default 6000). Between 17 and 20000.</li>
  <li><strong>Chute speed:</strong> in µsteps/s (default 3000). Between 17 and 10000.</li>
  <li><strong>Chute limit:</strong> in degrees (default 345). Between 5 and 345.</li>
</ul>

### Run it and read the result

<ol class="numbered-steps">
  <li>Press <strong>Start the power stress test</strong>.</li>
  <li>Watch <strong>This run</strong>. It shows a status badge, the phase and part, the time done out of the time set, a progress bar, and four counts of what the test found: <strong>Steppers</strong>, <strong>Servos</strong>, <strong>Light outputs</strong> and <strong>Vision workers</strong>. A table lists what happened and when, newest first, in your local time.</li>
  <li>To end it early press <strong>Stop safely</strong>. The status goes to stopping, the motors brake, the chute and servos stop, and the lights and stepper limits are put back.</li>
</ol>

Each phase's start is stored as an epoch time. To line the machine's phases up against a power meter's readings, press **Download the JSON** (or **JSON** beside a run under **Past runs**) and use the times in it.

A run ends as completed, stopped, or failed. A failed run shows its reason. One cause is a motor stall: if stall detection is on and any of the four channel steppers stalls, the run fails with **Stepper stall detected** and the motor's name (see <a href="{{ '/sorter/stallguard/' | relative_url }}">StallGuard</a>).

**Past runs** lists the last 20 with their start, status and duration, each with a **JSON** download.

<div class="img-placeholder">Screenshot of the Power stress test page mid-run, showing the Sequence panel, the Settings panel, and This run with its progress bar.</div>
