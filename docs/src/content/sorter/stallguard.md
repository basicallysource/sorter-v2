---
layout: default
title: StallGuard
type: how-to
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-stallguard
kicker: SorterOS — Operate
author: jensr80
lede: Stop the machine when the chute or the classification channel stalls, and set how sensitive that check is. Record the motor running freely and held back, save the threshold the page works out, then check it.
permalink: /sorter/stallguard/
warning: >-
  **AI-generated first draft.** Written from SorterOS's own source, not from
  a running machine. It has no screenshots yet, and the wording on the page
  may have drifted since it was written.
---

StallGuard is the stall check built into each stepper motor's driver chip. The driver measures how hard the motor is working and reports it as a number called **SG_RESULT**. A free-running motor reads high, a motor that is loaded reads lower, and a motor held still reads near 0. When the reading falls to the trip level, the driver raises a stall, the firmware stops the motor, and SorterOS halts the machine with a stall incident. The hardware side is in [Stall detection]({{ '/lab/motors/' | relative_url }}#stall-detection).

The **StallGuard** pages are where you set the trip level for one motor, so a real stall trips it and normal running does not.

## Open it

There are two StallGuard pages, one under each motor:

<ul class="bulleted-list">
  <li><strong>Settings</strong>, <strong>Chute</strong>, then <strong>StallGuard</strong>: the <strong>Chute StallGuard</strong> page.</li>
  <li><strong>Settings</strong>, <strong>Classification channel</strong>, then <strong>StallGuard</strong>: the <strong>Classification channel StallGuard</strong> page. It tunes the classification channel's stepper.</li>
</ul>

The older address `/settings/stepper-stallguard` goes to the chute's page. The other channel steppers have no StallGuard page. The [machine.toml reference]({{ '/sorter/machine-toml-reference/' | relative_url }}) lists the defaults a motor starts with and where they are saved.

The two pages are the same except for what only the chute has: **Automatic tuning**, a speed filled in from its operating speed, the random go-to-angle motion, and a link to its stress test.

## Read the numbers

<ul class="bulleted-list">
  <li><strong>Threshold (SGTHRS):</strong> a number from 0 to 255. A stall is reported when SG_RESULT is at or below <strong>twice</strong> this number. The page prints that line as "Trips when SG_RESULT is N or less". A higher threshold trips on a lighter load, so it is more sensitive. A lower one trips only on a heavier load.</li>
  <li><strong>Speed floor (TCOOLTHRS):</strong> a number in TSTEP units, the time the driver takes for one 1/256 microstep. A smaller TSTEP is a faster motor. The driver checks for a stall only while TSTEP is at or under the speed floor, which is to say only above a certain speed. The page shows that speed as <strong>Checks above</strong>, in µsteps/s.</li>
</ul>

A motor that cruises slower than the speed floor allows is never checked. The page tells you so with **Can't trip at this speed yet** or **StallGuard can't trip at this speed**, and what speed it needs.

## Automatic tuning (chute only)

**Automatic tuning** keeps the chute's threshold and speed floor set for you. While it is on, it learns how the chute reads in normal running, at the speed the chute runs at, and sets the trip level far under that and far over a stall. It learns again when the speed, the run current, the microstepping or the chopper mode changes.

<ul class="bulleted-list">
  <li><strong>Tune automatically</strong> is the switch. It is disabled when StallGuard is off on this machine, and the panel says <strong>Not running: StallGuard is off on this machine.</strong></li>
  <li>The badge shows the state: <strong>Off</strong>, <strong>Learning</strong> with a count of readings so far out of the readings needed, <strong>Tuned</strong>, <strong>Paused for a recording</strong>, or <strong>Working harder</strong>.</li>
  <li>When it is on, the panel lists <strong>Trips at</strong>, <strong>Normal running</strong> (a reading of "N or higher", or <strong>Still learning</strong>), <strong>Speed floor</strong>, <strong>Learned from</strong> a number of readings, and the <strong>Last change</strong>.</li>
  <li><strong>Working harder than it did</strong> means normal running now reads lower than it used to. Check that the chute turns freely, then press <strong>Learn again</strong>. <strong>Learn again</strong> is also at the foot of the panel while tuning is on.</li>
  <li><strong>Normal running is close to a stall</strong> means normal running reads so near the trip level that a stall still trips it but with little room.</li>
</ul>

A threshold or speed floor saved by hand turns automatic tuning off. So does **Save and turn on StallGuard** in step 4 below, which says so beside the button.

## Tune it by hand

The **Tune StallGuard** panel takes five steps. It has a badge, **Step N of 5**, which turns to **Tuned** when the settings are saved. The steps follow what the machine has recorded, not what you clicked, so a reload (or another browser) shows the same step open. A finished step has a button to open it again (**Change**, **Record again** or **Review**).

**Two steps move the motor.** Steps 2 and 5 show **Moves the motor. Keep clear.** Step 3 asks you to hold the motor back by hand, with **Hold only the part that turns. Let go if anything feels wrong.** Nothing on these pages checks that the sorter is paused. They refuse only while the hardware is homing or a power stress test is running, and when that motor is busy. The sorter must also have started its hardware.

<ol class="numbered-steps">
  <li><strong>Check the speed.</strong> Type the speed the motor runs at, in µsteps/s, in <strong>Speed</strong>. The chute fills this in with its operating speed (marked <strong>Operating speed</strong>, or press <strong>Use the operating speed</strong>). The classification channel starts at 1500, so type the speed it really runs at. A message under it says whether the saved settings <strong>Can trip at this speed</strong>, <strong>Can't trip at this speed yet</strong> (steps 2 to 4 fix it) or that <strong>StallGuard is off</strong> (step 4 turns it on). Press <strong>Tune at</strong> followed by your speed.</li>
  <li><strong>Record the motor running freely.</strong> It runs normally with nothing holding it back. Press <strong>Record it running freely</strong>. It takes about the duration shown (4 s unless you change it). The step then reads, for example, "Running freely it reads N or higher."</li>
  <li><strong>Record a stall.</strong> Press <strong>Record a stall</strong>, then hold the motor back until it stops, for the whole recording. While it records the page says <strong>Hold it now, until it stops.</strong> A real stall reads near 0. The step then reads "Held back, it dips to N." If the last recording could not be used, the step says why. Record it again.</li>
  <li><strong>Review and save.</strong> The page shows the <strong>Threshold (SGTHRS)</strong> and <strong>Speed floor (TCOOLTHRS)</strong> it suggests, and for each says <strong>Saved</strong> or what it is now. Under them: <strong>Running freely</strong> (N or higher), <strong>Stall</strong> (N or lower), <strong>Trips at</strong> (N or lower) and <strong>Checks above</strong>. Press <strong>Save and turn on StallGuard</strong>. The trip level sits between the free-running floor and the stall dip, and the speed floor is set from the speed the motor actually reached in the recordings. If the page shows <strong>Not reliable at</strong> that speed, normal moves dip close to the trip line and it would false-trip. The button then reads <strong>Save anyway</strong>, and <strong>Record the stall again</strong> is offered. If the stall only dipped to a high reading, the page says to hold the motor until it stops.</li>
  <li><strong>Check it</strong> (optional). Press <strong>Record a check</strong> for one more free run, compared against the saved settings. It reports <strong>Nothing would have tripped</strong> with the lowest reading and the trip level, or <strong>It would have stopped the machine</strong> with how many readings were at or under the trip level (record the stall again, or lower the threshold below), or <strong>Nothing to check</strong> if the motor never ran above the speed floor. On the chute, <strong>Open the stress test</strong> goes to the chute settings page for a test with detection on.</li>
</ol>

Only recordings made at the speed you are tuning, and with the motor's current run current, microstepping and chopper mode, count toward a suggestion. Change the speed and the steps look again at what is recorded for the new one. While a recording runs, stall detection is off for that motor, and is put back after.

<div class="img-placeholder">Screenshot of the Chute StallGuard page with step 4, Review and save, open.</div>

## The load curve

Below the steps, **Load curve** draws one recording as SG_RESULT over time, with the trigger line and the part of the recording where the driver would be checking. Lower means more load.

<ul class="bulleted-list">
  <li><strong>Recording</strong> picks which one to show. It opens on the latest, and shows a new one the moment it is made. Each entry has a time, the kind (<strong>Free running</strong> or <strong>Stall</strong>), a label and a speed.</li>
  <li>Above the chart are the facts of the recording: motor, speed, direction, duration, mean SG, run current (IRUN), acceleration, microsteps, chopper (StealthChop or SpreadCycle), whether it was loaded, and the cruise TSTEP.</li>
  <li><strong>CS_ACTUAL</strong> and <strong>TSTEP</strong> add those readings to the chart (TSTEP is on by default).</li>
  <li><strong>Threshold suggestion</strong> lists the numbers behind step 4: <strong>Unloaded floor</strong>, <strong>Loaded dip</strong>, <strong>Trigger at or below</strong>, <strong>SGTHRS</strong>, <strong>Measured cruise TSTEP</strong>, <strong>Gate TCOOLTHRS</strong> and <strong>Real-motion floor</strong>. With no stall recorded at the speed yet, it says the numbers are provisional.</li>
</ul>

## Stall detection

The **Stall detection** panel is the form the steps fill in. You can also use it directly.

<ol class="numbered-steps">
  <li>Tick <strong>StallGuard stall detection</strong> to halt the machine if this motor stalls, on every move, while it is on. The two fields below appear once it is ticked.</li>
  <li>Set <strong>Threshold (SGTHRS)</strong> (a slider, or type 0 to 255) and <strong>Speed floor (TCOOLTHRS)</strong>. The line under them shows the trip level and the TSTEP limit those give.</li>
  <li>Press <strong>Save</strong>. The page confirms with <strong>Stall detection saved.</strong>, and adds that it applies at the next start if the hardware is not running.</li>
</ol>

When Automatic tuning is on, the two numbers are not editable: the panel says they are set by automatic tuning, and **Save** changes only whether detection is on. Saving a different threshold or speed floor turns Automatic tuning off.

## Expert tools

<ul class="bulleted-list">
  <li><strong>Sweep options</strong> changes how steps 2, 3 and 5 move the motor. <strong>Motion</strong> is <strong>Constant spin</strong>, <strong>Pulsed with jitter</strong>, or on the chute <strong>Chute: random go-to-angle</strong>. Then <strong>Direction</strong> (<strong>Clockwise</strong> or <strong>Counterclockwise</strong>), <strong>Duration</strong> in seconds, and an optional <strong>Label</strong>. Random go-to-angle adds <strong>Min angle</strong>, <strong>Max angle</strong> and <strong>Min angle change</strong>. It homes the chute first if needed and stays within the chute's safe travel. Pulsed adds <strong>Pulse size</strong>, <strong>Dwell</strong> and <strong>Jitter every</strong> (0 turns jitter off). <strong>Cruise TSTEP</strong> sets which readings count as cruising, and when empty it follows the speed. A checkbox makes <strong>Enter</strong> start the recording of the open step. Each step shows what it will do and has <strong>Change how it moves</strong> to get here. The chute defaults to random moves between 10° and 340°. The classification channel defaults to short pulses.</li>
  <li><strong>Past recordings</strong> lists every recording for this motor, newest first. Press a row to show it in the load curve. The <strong>Delete run</strong> button beside it asks <strong>Delete the run?</strong> and deletes the recording and its readings. The list shows the latest 8, and <strong>Show all</strong> shows the rest.</li>
  <li><strong>Recorded readings</strong> gives the totals for this motor: <strong>Samples</strong> and when the last was taken, <strong>SG min</strong>, <strong>SG mean</strong> and <strong>SG max</strong>.</li>
</ul>

## After a real stall

When the check trips in use, the motor stops and the machine halts. The motor's own page (the chute's page, or its channel's) shows an alert, **stalled**, with **Clear the stall**. Clear the jam first, then press it. A stall drops the motor's home position, so home it again before precise moves. The top bar's resume button stays disabled while a stall is unresolved, labeled **Clear the motor stall before resuming**. After a chute stall it stays disabled, labeled **Re-home the chute before resuming**, until the chute is homed again.
