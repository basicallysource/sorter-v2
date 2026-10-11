---
layout: default
title: What is connected to the Pico
type: explanation
section: lab
slug: lab-pico
kicker: Design and research — Electronics
lede: Everything the Raspberry Pi Pico on the control board is connected to, which pin each connection uses, and which part of the firmware handles it.
permalink: /lab/pico/
audience: curious builder or contributor
applies_to: hardware-v2
owner: docs
warning: >-
  **AI-generated first draft.** Written from the Pico firmware, the control program and the board's
  KiCad files, not from an actual build. The part names, pins and numbers are read from those files and
  have not been checked against a built machine.
---

The Pico is a Raspberry Pi Pico, a small board with a microcontroller on it (a tiny computer that runs one program and nothing else). It plugs into headers on the control board, which is the **basically board v1.3** this page describes. The program stored inside the Pico (the firmware) only makes the pulses that move the stepper motors, switches outputs on and off, and reads inputs. The Orange Pi decides what to do and sends it commands, which is described on [How the electronics talk to each other]({{ '/lab/electronics/' | relative_url }}).

This page is the list of what connects to the Pico and which pin each connection uses. Which socket each cable goes into is on [Connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), and how the cables are wired is on [Wire harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}).

## The big picture

<ul class="bulleted-list">
  <li><strong>The Orange Pi:</strong> over USB. See <a href="{{ '/lab/usb/' | relative_url }}">The USB connections and the hub</a> and <a href="{{ '/lab/electronics/' | relative_url }}">How the electronics talk to each other</a>.</li>
  <li><strong>Power:</strong> 5 V into the Pico's <code>VSYS</code> pin, from a converter on the control board. Details: <a href="{{ '/lab/power/' | relative_url }}">Power distribution</a>.</li>
  <li><strong>The stepper drivers:</strong> five driver chips, one per stepper motor. The Pico gives each a STEP pin and a DIR pin, shares one enable pin and two serial lines between them, and reads a DIAG pin from each. Details: <a href="{{ '/lab/motors/' | relative_url }}">The motors</a>.</li>
  <li><strong>The servo chip:</strong> a PCA9685 chip that makes the servo signals, reached over two wires (I²C, a two-wire connection between chips). Details: <a href="{{ '/lab/servos/' | relative_url }}">The servos and the layer adapter boards</a>.</li>
  <li><strong>The camera lamps:</strong> two outputs, covered below.</li>
  <li><strong>The switches:</strong> two inputs, one of them the chute limit switch, covered below.</li>
</ul>

## What the Pico pins do

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-pinout-board-v1-3-w1600-637c7f51cee8.jpg" alt="Pinout of the Raspberry Pi Pico on basically board v1.3. All 40 pins are drawn in physical order, with the GP number and the job of each pin colour coded: STEP and DIR for the five steppers, a DIAG pin per driver, the two driver UART buses, the driver enable, two lamp outputs, two switch inputs and the servo chip I2C pins">
  <figcaption>The Pico's pins as the v1.3 board uses them. <a href="https://assets.basically.website/sorter-docs/pico-pinout-board-v1-3-full-85e97bfc49da.png">Full size</a>. <cite>Drawn from the firmware pin map, not from a build. Diagram: Balloon.</cite></figcaption>
</figure>

<table>
  <thead><tr><th>Purpose</th><th>Pico pins</th></tr></thead>
  <tbody>
    <tr><td>Chute stepper: STEP / DIR / DIAG</td><td>GP28 / GP27 / GP12</td></tr>
    <tr><td>C1 rotor stepper: STEP / DIR / DIAG</td><td>GP26 / GP22 / GP13</td></tr>
    <tr><td>C2 rotor stepper: STEP / DIR / DIAG</td><td>GP8 / GP7 / GP9</td></tr>
    <tr><td>C3 rotor stepper: STEP / DIR / DIAG</td><td>GP21 / GP20 / GP14</td></tr>
    <tr><td>Carousel (classification channel) stepper: STEP / DIR / DIAG</td><td>GP19 / GP18 / GP15</td></tr>
    <tr><td>Driver enable, shared by all five</td><td>GP0</td></tr>
    <tr><td>Driver UART, drivers 1 to 4 (chute, C1, C3, carousel)</td><td>GP16 (TX), GP17 (RX)</td></tr>
    <tr><td>Driver UART, driver 5 (C2)</td><td>GP4 (TX), GP5 (RX)</td></tr>
    <tr><td>Camera lamps (PWM outputs)</td><td>GP1, GP6</td></tr>
    <tr><td>Switch inputs (limit switch)</td><td>GP3, GP2</td></tr>
    <tr><td>Servo chip (I²C): SDA / SCL</td><td>GP10 / GP11</td></tr>
  </tbody>
</table>

In this table, GP and a number (for example GP28) name one pin on the Pico. STEP, DIR, DIAG, UART and enable are explained on [The motors]({{ '/lab/motors/' | relative_url }}), and the I²C pins on [The servos and the layer adapter boards]({{ '/lab/servos/' | relative_url }}).

The full circuit is the board's schematic: <a href="https://assets.basically.website/sorter-docs/basically-board-v1-3-schematic-1a2945526770.pdf">basically board v1.3 schematic (PDF)</a>, drawn from <a href="https://github.com/basicallysource/sorter-v2/tree/main/electronics/KiCad/1_Distribution_Board">the KiCad project</a>, which is the file to open if you want to edit or export it yourself.

The pin map is the file [`hwcfg_basically_v1_2.h`](https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/hwcfg_basically_v1_2.h), and that file is the one to trust if this table and the firmware ever disagree. The v1.3 board uses the file named `v1_2`; that is correct, not a mistake. Other boards have their own file next to it: [`hwcfg_skr_pico.h`](https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/hwcfg_skr_pico.h) for the BigTreeTech SKR Pico and [`hwcfg_basically_v1_1.h`](https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/hwcfg_basically_v1_1.h) for the earlier board.

<ul class="bulleted-list">
  <li>Fitting the Pico's headers: <a href="{{ '/hardware/helpers/pico-headers/' | relative_url }}">Pico headers</a></li>
  <li>Flashing the firmware: <a href="{{ '/hardware/software-setup/' | relative_url }}">Software setup</a></li>
</ul>

## Why one board

<ul class="bulleted-list">
  <li><strong>The first machines used two boards.</strong> A Pico runs four steppers and the machine needs five, so the early setup used two SKR Pico boards (<a href="https://discord.com/channels/1430279849171222682/1460692585881534579/1481604115480969269">March 2026</a>).</li>
  <li><strong>The plan to merge them.</strong> Putting everything on one board was raised at the <a href="https://www.youtube.com/watch?v=Jl2zgY1sGUw">8 March 2026 meeting</a>, as a more unified system. At the <a href="https://www.youtube.com/watch?v=PBEk7i_vIVY">29 March 2026 meeting</a> the design change was to add one more driver socket on the second serial port that the Pico has.</li>
  <li><strong>The result.</strong> The fifth stepper worked, the servo chip add-on module was no longer needed, and a machine needs one board where the first revision needed two (<a href="https://discord.com/channels/1430279849171222682/1437436041685631129/1494941858143404103">April 2026</a>).</li>
</ul>

## The camera lamps

The two lamp outputs are PWM pins. PWM switches a pin on and off very fast, and the share of time it is on sets the brightness. The Orange Pi turns a brightness percentage into a duty value, which says how much of the time the pin is on (a number from 0 to 65535), and sends it as a `WRITE_PWM` command for that output. The Pico sets it and keeps it until told otherwise.

What the lamp ports do with that signal, and what is plugged into them, is on [Power distribution]({{ '/lab/power/' | relative_url }}) under the lamps and the fan.

<ul class="bulleted-list">
  <li>Percentage to duty on the Orange Pi: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/irl/leds.py"><code>irl/leds.py</code></a></li>
  <li>The endpoint the UI calls: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/server/routers/leds.py"><code>server/routers/leds.py</code></a></li>
  <li>The firmware handler: <code>CMDH_digital_write_pwm</code> in <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp"><code>sorter_interface_firmware.cpp</code></a></li>
</ul>

## The switches

The two switch inputs are plain digital inputs, on or off, that the Orange Pi reads with a `READ` command. The chute limit switch plugs into the one the board prints `HALL_SW_0`. The chute is turned back to this switch to find its home position, which is described on [The motors]({{ '/lab/motors/' | relative_url }}).

The DIAG inputs that report a blocked motor are not switches. They are covered on [The motors]({{ '/lab/motors/' | relative_url }}) too.
