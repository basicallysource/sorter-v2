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

The firmware on the Pico is deliberately simple. It generates step pulses, switches outputs and reads inputs. Everything that decides what to do runs on the Orange Pi, which sends the Pico short commands.

This page describes the **basically board v1.3**. How the cables are wired is in [Wire harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) and [Connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}).

## The big picture

<ul class="bulleted-list">
  <li><strong>Orange Pi to Pico:</strong> one micro-USB cable, through the USB hub. The Pico appears to the Orange Pi as a serial port.</li>
  <li><strong>Pico to the stepper drivers:</strong> a STEP and a DIR pin per driver for movement, plus a serial (UART) line to configure each TMC2209.</li>
  <li><strong>Pico to the servo chip:</strong> a PCA9685 on the control board, over I²C. The layer adapter boards take its signals down the ribbon cable.</li>
  <li><strong>Pico to the lamps and the switches:</strong> two PWM outputs for the camera lamps and two switch inputs, one of them the chute limit switch.</li>
</ul>

## Orange Pi to Pico

The Pico plugs into the USB hub (`USB2`), and the hub plugs into the Orange Pi (`USB1`). The Orange Pi finds the Pico by its USB ID and opens it as a serial port.

Every message, in either direction, has the same frame: a 4-byte header (device address, command, channel, payload length), the payload, and a CRC32 checksum. The frame is wrapped in COBS so a zero byte marks the end of each message, and it is at most 254 bytes. The host sends a command, the Pico answers it.

The commands are grouped by what they act on: the board itself (`INIT`, `PING`, `GET_VERSION`), steppers, the stepper drivers, digital inputs and outputs, and servos. The channel in the header says which stepper, output or servo is meant.

<ul class="bulleted-list">
  <li>Frame format, host side: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/hardware/bus.py"><code>hardware/bus.py</code></a> (the comment at the top describes the format)</li>
  <li>Command codes and the Python objects for steppers, outputs and servos: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/hardware/sorter_interface.py"><code>hardware/sorter_interface.py</code></a></li>
  <li>Finding and identifying the boards: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/machine_platform/control_board.py"><code>machine_platform/control_board.py</code></a></li>
  <li>Frame format and command table, firmware side: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/message.h"><code>message.h</code></a>, <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/message.cpp"><code>message.cpp</code></a> and the command tables at the top of <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp"><code>sorter_interface_firmware.cpp</code></a></li>
</ul>

## What the Pico pins do

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

The pin map is the file [`hwcfg_basically_v1_2.h`](https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/hwcfg_basically_v1_2.h), and that file is the one to trust if this table and the firmware ever disagree. The v1.3 board uses the file named `v1_2`. Other boards have their own file next to it: [`hwcfg_skr_pico.h`](https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/hwcfg_skr_pico.h) for the BigTreeTech SKR Pico and [`hwcfg_basically_v1_1.h`](https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/hwcfg_basically_v1_1.h) for the earlier board.

## Steppers and the chute

Movement and configuration use two separate paths. The Pico makes the step pulses and sets the direction on each driver's STEP and DIR pins, with acceleration handled in the firmware. The TMC2209 itself is set up over its UART: motor current, microstepping and stall detection. The five drivers share two UART buses, and each driver answers to an address set by the jumpers on the board ([Preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }})).

The chute stepper is channel 0. The host homes it against the limit switch, then turns it to a bin angle. Its steps are counted in the firmware, and the host works in degrees.

<ul class="bulleted-list">
  <li>Step generation and motion: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/Stepper.cpp"><code>Stepper.cpp</code></a></li>
  <li>Driver setup over UART: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/TMC2209.cpp"><code>TMC2209.cpp</code></a> and <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/TMC_UART.cpp"><code>TMC_UART.cpp</code></a></li>
  <li>Chute homing and aiming, host side: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/subsystems/distribution/chute.py"><code>subsystems/distribution/chute.py</code></a></li>
  <li>What you do with it as an operator: <a href="{{ '/sorter/chute-calibration/' | relative_url }}">Chute calibration</a></li>
</ul>

## Lamp brightness

The two lamp outputs are PWM pins. The host turns a brightness percentage into a 16-bit duty value and sends it as a `WRITE_PWM` command for that output. The Pico sets the duty and keeps it until told otherwise.

<ul class="bulleted-list">
  <li>Percentage to duty on the host: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/irl/leds.py"><code>irl/leds.py</code></a></li>
  <li>The endpoint the UI calls: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/server/routers/leds.py"><code>server/routers/leds.py</code></a></li>
  <li>The firmware handler: <code>CMDH_digital_write_pwm</code> in <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp"><code>sorter_interface_firmware.cpp</code></a></li>
</ul>

## Servos and the layer adapter boards

A PCA9685 chip on the control board generates the servo signals. The Pico talks to it over I²C and the host sends servo commands (move to an angle, speed and acceleration limits, release). The control board's ribbon cable carries the signals to the first [layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}), and each layer's board passes them on down the stack and drives that layer's servo.

<ul class="bulleted-list">
  <li>Servo chip driver: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/PCA9685.cpp"><code>PCA9685.cpp</code></a></li>
  <li>Servo motion: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/Servo.cpp"><code>Servo.cpp</code></a></li>
</ul>

## Switches and stall detection

The two switch inputs are plain digital inputs that the host reads with a `READ` command; the chute limit switch plugs into the one the board prints `HALL_SW_0`. Each TMC2209 can also signal a stall on its DIAG pin, and the host can read the same information from the driver over UART.

## Where to look in the firmware

The firmware lives in [`software/firmware/sorter_interface_firmware`](https://github.com/basicallysource/sorter-v2/tree/main/software/firmware/sorter_interface_firmware). Its README has the build and flashing steps.
