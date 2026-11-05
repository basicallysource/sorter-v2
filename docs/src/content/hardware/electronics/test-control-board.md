---
layout: default
title: Test the control board
type: reference
section: hardware
slug: electronics-test-control-board
kicker: Electronics — Test the control board
lede: Turn each stepper, move each servo and watch the limit switch from your browser, to find a wiring fault before the board goes into the machine.
permalink: /hardware/electronics/test-control-board/
author: reveryx
warning: >-
  **AI-generated first draft.** The tester speaks the control board firmware's own serial protocol, and
  that protocol is checked byte for byte against the machine's Python backend. It has not been run
  against a real board yet. If something does not work, the Traffic panel on the page shows exactly
  what was sent and what came back.
---

This page talks to the control board directly over USB. Nothing is installed and nothing leaves your computer: your browser sends the same commands SorterOS does.

## What you need

<ul class="bulleted-list">
  <li>A computer with <strong>Chrome, Edge, Brave or Opera</strong>. Firefox and Safari cannot talk to USB serial devices.</li>
  <li>The control board flashed with the interface firmware. A board that has never been flashed does not appear in the list below; <a href="{{ '/sorter/' | relative_url }}#flash-the-control-board-before-the-wizard">flash it first</a>.</li>
  <li>A USB cable from the board's Pico to your computer.</li>
  <li>For the steppers and servos, the machine's 24 V supply connected and switched on. USB only powers the Pico itself.</li>
</ul>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Close SorterOS first.</b> Only one program can use the board's serial port at a time. If the board is plugged into the Orange Pi, stop SorterOS there, or unplug the board and use your own computer. On Linux your user also needs permission to open serial ports (usually the <code>dialout</code> group).</p>
</div>

## Test the board

<ol class="numbered-steps">
  <li>Press <strong>Connect to board</strong> and pick the Pico in the list your browser shows. Leave the board address at 0 unless you built the firmware with another one.</li>
  <li>The board reports what it has: its name, firmware version, and how many steppers, servo channels, inputs and outputs. If a count is lower than you expect, that part is not being seen.</li>
  <li>Work down the panels below.</li>
</ol>

<div data-firmware-tester><p>The tester needs JavaScript.</p></div>

## What each panel does

**Steppers.** Motors start with no current, so the first move sets the current for you. The tester starts at 8; raise it only if the motor skips. SorterOS defaults to 16, and 4 on the C-channel rotors. **Forward** and **Reverse** move the number of microsteps you enter. **Run forward** and **Run reverse** keep turning at a speed until you press **Stop**. **Stop all** stops every motor at once. If a motor hums but does not turn, check the coil wiring and the current.

**Check driver** asks the stepper driver for its status over the board's internal link. It tells you whether the driver answered at all, and lists any fault it is reporting: overheating, a short, or a coil that is not connected. A driver that does not answer is usually missing, unpowered or set to the wrong address. Run the motor for a moment before checking for open coils, because that flag only means something while the motor is turning.

**Home against a limit switch.** The motor turns until the input you pick reaches the level you pick, then stops and calls that position 0. This is how the chute is homed against its limit switch. Press the switch by hand first and watch the Inputs panel to see which level means pressed, then use that level here. If the input already reads that level, the motor stops straight away without moving. Press **Stop** if the motor never reaches it.

**Servos.** The channel list covers the 16 outputs of the servo controller. A servo does nothing until it is switched on, and switching on sends it to the angle on the slider, so set the slider to where the horn is before you press the button. 0° to 180° is a 0.5 ms to 2.5 ms pulse. **Release** switches the servo off so you can turn it by hand. If no servo channels appear, the servo controller did not answer; check its wiring and power, then press **Reset and rescan**.

**Inputs.** The limit switch and the other sensors. Press **Read** for a snapshot, or tick **Live** to watch them change. An input with nothing connected reads High, so a switch that goes Low when pressed is wired correctly.

**Outputs.** The lamp and enable outputs. **On** and **Off** switch them fully; the slider sets a PWM duty from 0 to 100%.

**Traffic** lists every command sent and every reply, which is what to copy into a bug report.

## If it will not connect

<ul class="bulleted-list">
  <li><strong>No board in the list:</strong> the board is not running the interface firmware, or the cable carries power only. A board that has never been flashed shows up as a USB drive named <code>RPI-RP2</code> instead.</li>
  <li><strong>"Failed to open serial port":</strong> something else has the port open. Close SorterOS and any other serial program, or check your user's permission to open it.</li>
  <li><strong>Connected but the board does not answer:</strong> try the other address, or reflash the firmware.</li>
</ul>
