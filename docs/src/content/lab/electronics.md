---
layout: default
title: How the electronics talk to each other
type: explanation
section: lab
slug: lab-electronics
kicker: Design and research — Electronics
lede: "How the Orange Pi talks to the Pico: the cable, the messages, and where to find each part in the firmware."
permalink: /lab/electronics/
audience: curious builder or contributor
applies_to: hardware-v2
owner: docs
warning: >-
  **AI-generated first draft.** Written from the Pico firmware, the control program and the board's
  KiCad files, not from an actual build. The part names, pins and numbers are read from those files and
  have not been checked against a built machine.
---

The Pico is the small control board on the machine, and the program stored inside it (the firmware) is deliberately simple. Everything that decides what to do runs on the Orange Pi, the machine's computer, which sends the Pico short commands. This page is about how those two talk to each other. What is connected to the Pico is on [What is connected to the Pico]({{ '/lab/pico/' | relative_url }}).

This page describes the **basically board v1.3**. How the cables are wired is in [Wire harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) and [Connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}).

## The big picture

<ul class="bulleted-list">
  <li><strong>Orange Pi to Pico:</strong> one micro-USB cable, through the USB hub.</li>
  <li><strong>Pico to the rest of the board:</strong> the stepper drivers (<a href="{{ '/lab/motors/' | relative_url }}">The motors</a>), the servo chip (<a href="{{ '/lab/servos/' | relative_url }}">The servos and the layer adapter boards</a>), and the lamps and switches (<a href="{{ '/lab/pico/' | relative_url }}">What is connected to the Pico</a>).</li>
</ul>

## Orange Pi to Pico

The Pico reaches the Orange Pi through the USB hub, as described on [The USB connections and the hub]({{ '/lab/usb/' | relative_url }}). The Orange Pi finds the Pico by its USB ID and opens it as a serial port (a connection that sends one byte after another).

Every message, in either direction, has the same layout, called a frame. It is a 4-byte header (device address, command, channel, payload length), then the payload, which is the data itself, then a CRC32 checksum, a number the receiver uses to check that nothing was damaged on the way. The frame is wrapped in COBS, an encoding that makes a zero byte appear only at the end of a message, so the receiver always knows where one message stops. A frame is at most 254 bytes. The Orange Pi sends a command, and the Pico answers it.

The commands are grouped by what they act on: the board itself (`INIT`, `PING`, `GET_VERSION`), the stepper motors, the stepper drivers, digital inputs and outputs (pins that are on or off), and the servos. The number in the header says which stepper, output or servo is meant.

<ul class="bulleted-list">
  <li>Frame format, Orange Pi side: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/hardware/bus.py"><code>hardware/bus.py</code></a> (the comment at the top describes the format)</li>
  <li>Command codes and the Python objects for steppers, outputs and servos: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/hardware/sorter_interface.py"><code>hardware/sorter_interface.py</code></a></li>
  <li>Finding and identifying the boards: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/machine_platform/control_board.py"><code>machine_platform/control_board.py</code></a></li>
  <li>Frame format and command table, firmware side: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/message.h"><code>message.h</code></a>, <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/message.cpp"><code>message.cpp</code></a> and the command tables at the top of <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp"><code>sorter_interface_firmware.cpp</code></a></li>
</ul>

## If something does not work

Where to look first. Each line points to the page that has the fix.

<ul class="bulleted-list">
  <li><strong>The setup wizard finds no controller (<code>No MCU buses found</code>).</strong> A new Pico has no firmware yet, which is normal. Flash it first: <a href="{{ '/sorter/' | relative_url }}#flash-the-control-board-before-the-wizard">Flashing the control board</a>. If it still does not appear, check the two USB cables, <code>USB6</code> (Pico to hub) and <code>USB5</code> (hub to Orange Pi).</li>
  <li><strong>One motor never moves and the others do.</strong> Check the address jumpers of its driver. A wrong or missing jumper fails silently. <a href="{{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}">Preparing the control board</a>, step 3.</li>
  <li><strong>A motor stops and the machine reports a stepper stall.</strong> Something is blocking that motor. Look at the machine. <a href="{{ '/lab/motors/' | relative_url }}">The motors</a> explains what the machine does.</li>
  <li><strong>The chute does not find its home position.</strong> Check that the limit switch lead (<code>LIM1</code>) is in the socket the board prints <code>HALL_SW_0</code>. <a href="{{ '/hardware/electronics/connecting/' | relative_url }}">Connecting the components</a>.</li>
  <li><strong>The doors open on the wrong layer, or not at all.</strong> Check that every ribbon cable runs from <code>J4</code> of one layer board to <code>J3</code> of the next, never the other way round. <a href="{{ '/lab/servos/' | relative_url }}">The servos and the layer adapter boards</a>.</li>
  <li><strong>A lamp is dim.</strong> Check that the solder jumper beside its port is bridged. <a href="{{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}">Preparing the control board</a>, step 4.</li>
</ul>

## What happens at start-up

When the machine is started, the Orange Pi brings every motor and servo up in a fixed order. This is the order in the canary release of the control program (v0.4.15). Only the purpose of each step is listed, not every message.

<ol class="numbered-list">
  <li><strong>Find the boards.</strong> The Orange Pi opens each USB serial port and sends a ping (a short "are you there" message) to every address from 0 to 15. A Pico that answers is a board. If a stepper the machine needs is missing, it tries again, up to 8 times. If no board answers, start-up stops with <em>Control boards not found</em>.</li>
  <li><strong>Reset each board and ask what it has.</strong> The <code>INIT</code> command puts a Pico in a known state: lamps off, steppers not powered, servo chip reset with every output off. The Pico answers with its name, how many steppers, servos, inputs and outputs it has, and what each stepper is called. The Orange Pi uses the names to tell which stepper is which.</li>
  <li><strong>Set the lamps.</strong> The saved brightness of each lamp is sent to its output.</li>
  <li><strong>Set up each stepper driver.</strong> For every stepper the machine uses, the Orange Pi sends the driver its saved settings: UART mode (the driver takes its commands over a serial wire), microsteps, motor current and the stall detection threshold. It then sets the speed limit and acceleration. The driver counts the settings it accepts. The Orange Pi reads that counter before and after sending, and compares the difference with the number of settings it sent. If the driver took fewer, start-up stops with <em>Stepper settings not applied</em>. A driver that never answers also stops start-up, with <em>Stepper setup failed</em>, after 4 tries. Channels that no stepper uses are left alone.</li>
  <li><strong>Set up the servos.</strong> The Pico reports whether it found the servo chip. The Orange Pi gives each layer's servo its speed and its calibrated open and closed angles, and moves each servo back to the open or closed position it had when the machine last stopped. A servo that is not calibrated is not moved.</li>
  <li><strong>Open the doors.</strong> Every calibrated door is opened, at a slow speed. An uncalibrated servo is switched off instead, so it goes slack and cannot twitch. If no servo answers at all, start-up shows an error to check the servo cable and power.</li>
  <li><strong>Line up the classification channel.</strong> The carousel is turned forward until the camera sees the channel is empty, then turned a little more until one of the platter's five spokes is at its reference mark. This is skipped, with a warning, if there is no live camera picture yet.</li>
  <li><strong>Power the steppers and home the chute.</strong> The steppers are powered. The Orange Pi then tells the chute stepper to turn slowly until its limit switch is pressed. The Pico watches the switch itself, stops the stepper and sets that position as zero. Meanwhile the Orange Pi asks every 10 ms whether the stepper has stopped. It then backs the chute off to the first bin. If the switch is never reached, start-up fails with <em>Chute homing failed</em>.</li>
</ol>

After that the machine is ready and paused, until you resume it. Only the chute has a limit switch, so it is the only stepper that is homed.

## Where to look in the control program

The control program on the Orange Pi is Python, under <a href="https://github.com/basicallysource/sorter-v2/tree/sorter/canary/v0.4.15/software/sorter/backend"><code>software/sorter/backend</code></a>. These are the places that match the steps above, in the canary release (v0.4.15).

<ul class="bulleted-list">
  <li>Start-up order: <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/sorter/backend/main.py#L678"><code>_home_hardware</code></a> in <code>main.py</code></li>
  <li>Finding the boards: <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/sorter/backend/machine_platform/control_board.py#L242"><code>discover_control_boards</code></a> and <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/sorter/backend/hardware/bus.py#L344"><code>scan_devices</code></a></li>
  <li>Binding the steppers and servos: <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/sorter/backend/irl/config.py#L973"><code>_bindHardware</code></a> in <code>irl/config.py</code></li>
  <li>Setting up and checking a stepper driver: <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/sorter/backend/irl/config.py#L104"><code>_configureStepper</code></a> and <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/sorter/backend/hardware_settings/steppers.py#L210"><code>applyStepperSettings</code></a></li>
  <li>Servos: <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/sorter/backend/machine_platform/servo_controller.py#L351"><code>build_servo_controller</code></a>, <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/sorter/backend/irl/config.py#L159"><code>restore_servo_states</code></a> and <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/sorter/backend/main.py#L81"><code>_checkServoBusHealth</code></a></li>
  <li>Classification channel: <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/sorter/backend/subsystems/classification_channel/two_piece/spoke_home.py#L382"><code>maybeRunSpokeHome</code></a></li>
  <li>Chute homing: <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/sorter/backend/subsystems/distribution/chute.py#L284"><code>Chute.home</code></a></li>
</ul>

## Where to look in the firmware

The firmware lives in [`software/firmware/sorter_interface_firmware`](https://github.com/basicallysource/sorter-v2/tree/main/software/firmware/sorter_interface_firmware). Its README has the build and flashing steps.

The commands named in the start-up steps, each linked to the function that handles it in the canary release (v0.4.15). The command list is at the top of the same file.

<ul class="bulleted-list">
  <li><strong>Steps 1 and 2:</strong> <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L557"><code>PING</code></a>, <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L552"><code>INIT</code></a>; the reset itself is <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L469"><code>initialize_hardware</code></a></li>
  <li><strong>Step 3 (lamps):</strong> <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L634"><code>DIGITAL_WRITE_PWM</code></a></li>
  <li><strong>Step 4 (stepper drivers):</strong> <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L799"><code>STEPPER_DRV_WRITE_REGISTER</code></a>, <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L786"><code>STEPPER_DRV_READ_REGISTER</code></a>, <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L736"><code>STEPPER_DRV_SET_MICROSTEPS</code></a>, <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L778"><code>STEPPER_DRV_SET_CURRENT</code></a>, <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L807"><code>STEPPER_ENABLE_STALL_DETECTION</code></a>, <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L655"><code>STEPPER_SET_SPEED_LIMITS</code></a>, <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L663"><code>STEPPER_SET_ACCELERATION</code></a></li>
  <li><strong>Steps 5 and 6 (servos):</strong> <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L858"><code>SERVO_SET_SPEED_LIMITS</code></a>, <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L896"><code>SERVO_SET_DUTY_LIMITS</code></a>, <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L890"><code>SERVO_SET_ENABLED</code></a>, <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L834"><code>SERVO_MOVE_TO</code></a>, <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L842"><code>SERVO_MOVE_TO_AND_RELEASE</code></a></li>
  <li><strong>Step 8 (powering and homing):</strong> <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L723"><code>STEPPER_DRV_SET_ENABLED</code></a>, <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L689"><code>STEPPER_HOME</code></a>, <a href="https://github.com/basicallysource/sorter-v2/blob/sorter/canary/v0.4.15/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp#L670"><code>STEPPER_IS_STOPPED</code></a></li>
</ul>
