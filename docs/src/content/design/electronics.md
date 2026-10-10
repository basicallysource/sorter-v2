---
layout: default
title: How the electronics talk to each other
type: explanation
section: design
slug: design-electronics
kicker: Design — Electronics
lede: How the Orange Pi talks to the Pico, which Pico pins do what, and where to find each part in the firmware.
permalink: /design/electronics/
last_verified: 2026-10-10
---

Optional background: you do not need this page to build the sorter.

The Pico is a small control board on the machine. The program stored inside it (the firmware) is deliberately simple. It makes the pulses that move the stepper motors (one pulse is one small step), switches outputs on and off, and reads inputs such as switches. Everything that decides what to do runs on the Orange Pi, the machine's computer, which sends the Pico short commands.

This page describes the **basically board v1.3**. How the cables are wired is in [Wire harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) and [Connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}).

## The big picture

<ul class="bulleted-list">
  <li><strong>Orange Pi to Pico:</strong> one micro-USB cable, through the USB hub. The Pico appears to the Orange Pi as a serial port (a connection that sends one byte after another).</li>
  <li><strong>Pico to the stepper drivers:</strong> each stepper motor has a driver chip (a TMC2209) that powers it. The Pico gives each driver a STEP pin (one pulse is one step) and a DIR pin (which way to turn). It also has a serial line (UART) to the drivers, used to configure them, and a DIAG pin per driver that turns on when the driver detects a stall, which is when the motor is blocked and cannot turn.</li>
  <li><strong>Pico to the servo chip:</strong> a PCA9685 chip on the control board makes the signals that tell the servos where to turn. The Pico talks to it over I²C (a two-wire connection between chips). The layer adapter boards take those signals down the ribbon cable.</li>
  <li><strong>Pico to the lamps and the switches:</strong> two PWM outputs for the camera lamps (PWM switches a pin on and off very fast, and the share of time it is on sets the brightness) and two switch inputs, one of them the chute limit switch.</li>
</ul>

## Orange Pi to Pico

The Pico plugs into the USB hub (`USB2`), and the hub plugs into the Orange Pi (`USB1`). The Orange Pi finds the Pico by its USB ID and opens it as a serial port.

The rest of the USB tree is on [The USB connections and the hub]({{ '/design/usb/' | relative_url }}), and everything else the Orange Pi connects to is on [What is connected to the Orange Pi]({{ '/design/orange-pi/' | relative_url }}).

Every message, in either direction, has the same layout, called a frame. It is a 4-byte header (device address, command, channel, payload length), then the payload, which is the data itself, then a CRC32 checksum, a number the receiver uses to check that nothing was damaged on the way. The frame is wrapped in COBS, an encoding that makes a zero byte appear only at the end of a message, so the receiver always knows where one message stops. A frame is at most 254 bytes. The Orange Pi sends a command, and the Pico answers it.

The commands are grouped by what they act on: the board itself (`INIT`, `PING`, `GET_VERSION`), the stepper motors, the stepper drivers, digital inputs and outputs (pins that are on or off), and the servos. The channel in the header says which stepper, output or servo is meant.

<ul class="bulleted-list">
  <li>Frame format, Orange Pi side: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/hardware/bus.py"><code>hardware/bus.py</code></a> (the comment at the top describes the format)</li>
  <li>Command codes and the Python objects for steppers, outputs and servos: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/hardware/sorter_interface.py"><code>hardware/sorter_interface.py</code></a></li>
  <li>Finding and identifying the boards: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/machine_platform/control_board.py"><code>machine_platform/control_board.py</code></a></li>
  <li>Frame format and command table, firmware side: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/message.h"><code>message.h</code></a>, <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/message.cpp"><code>message.cpp</code></a> and the command tables at the top of <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp"><code>sorter_interface_firmware.cpp</code></a></li>
</ul>

## What the Pico pins do

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-pinout-board-v1-3-w1600-637c7f51cee8.jpg" alt="Pinout of the Raspberry Pi Pico on basically board v1.3. All 40 pins are drawn in physical order, with the GP number and the job of each pin colour coded: STEP and DIR for the five steppers, a DIAG pin per driver, the two driver UART buses, the driver enable, two lamp outputs, two switch inputs and the servo chip I2C pins">
  <figcaption>The Pico's pins as the v1.3 board uses them. <a href="https://assets.basically.website/sorter-docs/pico-pinout-board-v1-3-full-85e97bfc49da.png">Full size</a>. <cite>Drawn from the firmware pin map, not from a build. Diagram: Balloon.</cite></figcaption>
</figure>

<table>
  <thead><tr><th>Purpose</th><th>Pico pins</th></tr></thead>
  <tbody>
    <tr><td>Stepper STEP / DIR: chute</td><td>GP28 / GP27</td></tr>
    <tr><td>Stepper STEP / DIR: C1 rotor</td><td>GP26 / GP22</td></tr>
    <tr><td>Stepper STEP / DIR: C3 rotor</td><td>GP21 / GP20</td></tr>
    <tr><td>Stepper STEP / DIR: carousel</td><td>GP19 / GP18</td></tr>
    <tr><td>Stepper STEP / DIR: C2 rotor</td><td>GP8 / GP7</td></tr>
    <tr><td>Driver enable, shared by all five</td><td>GP0</td></tr>
    <tr><td>Driver UART, drivers 1 to 4</td><td>GP16 (TX), GP17 (RX)</td></tr>
    <tr><td>Driver UART, driver 5</td><td>GP4 (TX), GP5 (RX)</td></tr>
    <tr><td>Driver stall signals (DIAG)</td><td>GP12, GP13, GP14, GP15, GP9</td></tr>
    <tr><td>Camera lamps (PWM outputs)</td><td>GP1, GP6</td></tr>
    <tr><td>Switch inputs (limit switch)</td><td>GP3, GP2</td></tr>
    <tr><td>Servo chip (I²C): SDA / SCL</td><td>GP10 / GP11</td></tr>
  </tbody>
</table>

The full circuit is the board's schematic: <a href="https://assets.basically.website/sorter-docs/basically-board-v1-3-schematic-1a2945526770.pdf">basically board v1.3 schematic (PDF)</a>, drawn from <a href="https://github.com/basicallysource/sorter-v2/tree/main/electronics/KiCad/1_Distribution_Board">the KiCad project</a>, which is the file to open if you want to edit or export it yourself.

In this table, GP and a number (for example GP28) name one pin on the Pico. The pin map is the file [`hwcfg_basically_v1_2.h`](https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/hwcfg_basically_v1_2.h), and that file is the one to trust if this table and the firmware ever disagree. The v1.3 board uses the file named `v1_2`. Other boards have their own file next to it: [`hwcfg_skr_pico.h`](https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/hwcfg_skr_pico.h) for the BigTreeTech SKR Pico and [`hwcfg_basically_v1_1.h`](https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/hwcfg_basically_v1_1.h) for the earlier board.

## Steppers and the chute

Movement and configuration use two separate paths. The Pico makes the step pulses and sets the direction on each driver's STEP and DIR pins, and the firmware speeds the motor up and slows it down smoothly. The TMC2209 itself is set up over its UART line: the motor current, the microstepping (dividing each step into smaller ones for smoother movement) and the stall detection. The five drivers share two UART buses, and each driver answers to an address set by the jumpers on the board ([Preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }})).

Each driver's **DIAG** pin is the third path, and it only carries one thing: stall detection (the TMC2209 calls this StallGuard). The driver turns DIAG on when it senses that the motor is being held back while it turns. The firmware checks the pin every time it updates the motor's movement. When it is on, the firmware stops that stepper at once and remembers that it stalled. The Orange Pi asks the Pico for these stall records over USB, and it then raises a "stepper stall" incident, a message that stops the machine. It does not clear the incident on its own, because a person has to look at the machine. A stalled chute also loses its home position (the known starting angle), so it has to be homed again, meaning turned back to its limit switch, before sorting continues.

The five DIAG pins are GP12 (chute), GP13 (C1 rotor), GP14 (C3 rotor), GP15 (carousel, the classification channel) and GP9 (C2 rotor). The earlier v1.1 board has no DIAG routing, so a setting on the Orange Pi turns the whole stall check off.

The chute stepper is channel 0. The Orange Pi homes it against the limit switch, then turns it to the angle of a bin. The firmware counts the steps, and the Orange Pi works in degrees.

<ul class="bulleted-list">
  <li>Step generation and motion: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/Stepper.cpp"><code>Stepper.cpp</code></a></li>
  <li>Driver setup over UART: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/TMC2209.cpp"><code>TMC2209.cpp</code></a> and <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/TMC_UART.cpp"><code>TMC_UART.cpp</code></a></li>
  <li>Chute homing and aiming, Orange Pi side: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/subsystems/distribution/chute.py"><code>subsystems/distribution/chute.py</code></a></li>
  <li>What you do with it as an operator: <a href="{{ '/sorter/chute-calibration/' | relative_url }}">Chute calibration</a></li>
</ul>

## Lamp brightness

The two lamp outputs are PWM pins. The Orange Pi turns a brightness percentage into a duty value, which says how much of the time the pin is on (a number from 0 to 65535), and sends it as a `WRITE_PWM` command for that output. The Pico sets it and keeps it until told otherwise.

<ul class="bulleted-list">
  <li>Percentage to duty on the Orange Pi: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/irl/leds.py"><code>irl/leds.py</code></a></li>
  <li>The endpoint the UI calls: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/server/routers/leds.py"><code>server/routers/leds.py</code></a></li>
  <li>The firmware handler: <code>CMDH_digital_write_pwm</code> in <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp"><code>sorter_interface_firmware.cpp</code></a></li>
</ul>

## Servos and the layer adapter boards

A PCA9685 chip on the control board generates the servo signals. The Pico talks to it over I²C, and the Orange Pi sends servo commands (move to an angle, set speed and acceleration limits, release). The control board's ribbon cable carries the signals to the first [layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}), and each layer's board passes them on down the stack and drives that layer's servo.

<ul class="bulleted-list">
  <li>Servo chip driver: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/PCA9685.cpp"><code>PCA9685.cpp</code></a></li>
  <li>Servo motion: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/Servo.cpp"><code>Servo.cpp</code></a></li>
</ul>

## Switches and stall detection

The two switch inputs are plain digital inputs, on or off, that the Orange Pi reads with a `READ` command; the chute limit switch plugs into the one the board prints `HALL_SW_0`. Stall detection is the DIAG pins described under steppers above.

<ul class="bulleted-list">
  <li>Firmware side of stall detection: the stall check in <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/Stepper.cpp"><code>Stepper.cpp</code></a>, with the DIAG pin numbers in <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/hwcfg_basically_v1_2.h"><code>hwcfg_basically_v1_2.h</code></a></li>
  <li>Orange Pi side: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/stepper_stall_monitor.py"><code>stepper_stall_monitor.py</code></a></li>
</ul>

## Where to look in the firmware

The firmware lives in [`software/firmware/sorter_interface_firmware`](https://github.com/basicallysource/sorter-v2/tree/main/software/firmware/sorter_interface_firmware). Its README has the build and flashing steps.
