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
  <li><strong>The setup wizard finds no controller (<code>No MCU buses found</code>).</strong> A new Pico has no firmware yet, which is normal. Flash it first: <a href="{{ '/hardware/software-setup/' | relative_url }}">Software setup</a>. If it still does not appear, check the two USB cables, <code>USB6</code> (Pico to hub) and <code>USB5</code> (hub to Orange Pi).</li>
  <li><strong>One motor never moves and the others do.</strong> Check the address jumpers of its driver. A wrong or missing jumper fails silently. <a href="{{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}">Preparing the control board</a>, step 3.</li>
  <li><strong>A motor stops and the machine reports a stepper stall.</strong> Something is blocking that motor. Look at the machine. <a href="{{ '/lab/motors/' | relative_url }}">The motors</a> explains what the machine does.</li>
  <li><strong>The chute does not find its home position.</strong> Check that the limit switch lead (<code>LIM1</code>) is in the socket the board prints <code>HALL_SW_0</code>. <a href="{{ '/hardware/electronics/connecting/' | relative_url }}">Connecting the components</a>.</li>
  <li><strong>The doors open on the wrong layer, or not at all.</strong> Check that every ribbon cable runs from <code>J4</code> of one layer board to <code>J3</code> of the next, never the other way round. <a href="{{ '/lab/servos/' | relative_url }}">The servos and the layer adapter boards</a>.</li>
  <li><strong>A lamp is dim.</strong> Check that the solder jumper beside its port is bridged. <a href="{{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}">Preparing the control board</a>, step 4.</li>
</ul>

## Where to look in the firmware

The firmware lives in [`software/firmware/sorter_interface_firmware`](https://github.com/basicallysource/sorter-v2/tree/main/software/firmware/sorter_interface_firmware). Its README has the build and flashing steps.
