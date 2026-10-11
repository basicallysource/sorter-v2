---
layout: default
title: How the electronics talk to each other
type: explanation
section: lab
slug: lab-electronics
kicker: Lab — Electronics
lede: How the Orange Pi talks to the Pico: the cable, the messages, and where to find each part in the firmware.
permalink: /lab/electronics/
audience: curious builder or contributor
applies_to: hardware-v2
owner: docs
last_verified: 2026-10-11
---

The Pico is the small control board on the machine, and the program stored inside it (the firmware) is deliberately simple. Everything that decides what to do runs on the Orange Pi, the machine's computer, which sends the Pico short commands. This page is about how those two talk to each other. What is connected to the Pico is on [What is connected to the Pico]({{ '/lab/pico/' | relative_url }}).

This page describes the **basically board v1.3**. How the cables are wired is in [Wire harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) and [Connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}).

## The big picture

<ul class="bulleted-list">
  <li><strong>Orange Pi to Pico:</strong> one micro-USB cable, through the USB hub.</li>
  <li><strong>Pico to the rest of the board:</strong> the stepper drivers (<a href="{{ '/lab/motors/' | relative_url }}">The motors</a>), the servo chip (<a href="{{ '/lab/servos/' | relative_url }}">The servos and the layer adapter boards</a>), and the lamps and switches (<a href="{{ '/lab/pico/' | relative_url }}">What is connected to the Pico</a>).</li>
</ul>

## Orange Pi to Pico

The Pico plugs into the USB hub (`USB6`), and the hub plugs into the Orange Pi (`USB5`). The Orange Pi finds the Pico by its USB ID and opens it as a serial port (a connection that sends one byte after another).

The rest of the USB tree is on [The USB connections and the hub]({{ '/lab/usb/' | relative_url }}), and everything else the Orange Pi connects to is on [What is connected to the Orange Pi]({{ '/lab/orange-pi/' | relative_url }}).

Every message, in either direction, has the same layout, called a frame. It is a 4-byte header (device address, command, channel, payload length), then the payload, which is the data itself, then a CRC32 checksum, a number the receiver uses to check that nothing was damaged on the way. The frame is wrapped in COBS, an encoding that makes a zero byte appear only at the end of a message, so the receiver always knows where one message stops. A frame is at most 254 bytes. The Orange Pi sends a command, and the Pico answers it.

The commands are grouped by what they act on: the board itself (`INIT`, `PING`, `GET_VERSION`), the stepper motors, the stepper drivers, digital inputs and outputs (pins that are on or off), and the servos. The channel in the header says which stepper, output or servo is meant.

<ul class="bulleted-list">
  <li>Frame format, Orange Pi side: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/hardware/bus.py"><code>hardware/bus.py</code></a> (the comment at the top describes the format)</li>
  <li>Command codes and the Python objects for steppers, outputs and servos: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/hardware/sorter_interface.py"><code>hardware/sorter_interface.py</code></a></li>
  <li>Finding and identifying the boards: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/machine_platform/control_board.py"><code>machine_platform/control_board.py</code></a></li>
  <li>Frame format and command table, firmware side: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/message.h"><code>message.h</code></a>, <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/message.cpp"><code>message.cpp</code></a> and the command tables at the top of <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp"><code>sorter_interface_firmware.cpp</code></a></li>
</ul>

## Where to look in the firmware

The firmware lives in [`software/firmware/sorter_interface_firmware`](https://github.com/basicallysource/sorter-v2/tree/main/software/firmware/sorter_interface_firmware). Its README has the build and flashing steps.
