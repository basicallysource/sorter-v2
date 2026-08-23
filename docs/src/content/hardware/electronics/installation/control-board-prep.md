---
layout: default
title: Preparing the control board
type: how-to
section: hardware
slug: electronics-control-board-prep
kicker: Electronics — Preparing the control board
lede: The five stepper drivers, the Pico, and the jumpers that address the drivers.
permalink: /hardware/electronics/installation/control-board-prep/
author: spencer
parts_needed:
  - part: ctrl-board-basically
    qty: 1
---

Do this with the board loose, before the [housing]({{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}). Solder the [Pico headers]({{ '/hardware/electronics/installation/pico-headers/' | relative_url }}) first.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/control-board-prep/board-and-drivers.21aadf8e90f3e291.jpg" alt="The bare green basically Embedded Control Board on a wooden bench with five blue-finned TMC2209 stepper driver modules laid out in a column beside it">
  </figure>
</div>

## Why the drivers need addresses

The Pico talks to the drivers over a shared single-wire UART, so each one needs its own address. MS1 and MS2 set it, which allows four per bus. Five steppers is one too many, so the board runs two buses: four on uart0 at addresses 0 to 3, and the fifth on uart1 at address 0.

Each MS pin comes out to a 3-pin header:

<dl class="spec-list">
  <dt>Jumper on 1-2</dt><dd>3V3, HIGH</dd>
  <dt>Jumper on 2-3</dt><dd>GND, LOW</dd>
</dl>

MS1 is the low bit, MS2 the high bit.

{% include step.html n="1" title="Seat the five drivers" %}

Heatsink up, EN/MS1/MS2 edge towards the middle of the board. Module and socket are both silkscreened, so match the labels.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/control-board-prep/tmc2209-pin-labels.04b46570bcb6bc2e.jpg" alt="A single TMC2209 V1.3 driver module resting on a bench, blue heatsink upwards, with the pin names GND, VIO, EN and MS1 readable around its edge">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/control-board-prep/driver-seated.95b4e85e70643523.jpg" alt="A TMC2209 driver pushed fully down into its socket on the control board, heatsink upwards, with the remaining drivers out of focus behind">
  </figure>
</div>

{% include step.html n="2" title="Seat the Pico" %}

Into the two long sockets down the middle, USB end towards the edge of the board.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/control-board-prep/pico-seating.8bbfbfca8427e411.jpg" alt="A Raspberry Pi Pico held just above its two long header sockets on the control board, ready to be pushed down, with four seated stepper drivers behind it">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/control-board-prep/pico-seated.22ae8ea3ea49c25d.jpg" alt="The Raspberry Pi Pico fully seated in its sockets on the control board, sitting flat and parallel to the board">
  </figure>
</div>

{% include step.html n="3" title="Set the address jumpers" %}

Ten jumpers, two per driver. Read the 1 2 3 printed beside each header before pushing one on.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/control-board-prep/jumper-states.3f8a3e4c320b08af.jpg" alt="Annotated close-up of one driver's MS1 and MS2 headers: MS1 boxed in green with its jumper on pins 1 and 2 for 3V3, MS2 boxed in blue with its jumper on pins 2 and 3 for GND, beside a table mapping the four MS2/MS1 combinations to addresses 0 to 3">
  </figure>
</div>

<table>
  <thead>
    <tr><th>Channel</th><th>Stepper</th><th>Bus</th><th>Address</th><th>MS1</th><th>MS2</th></tr>
  </thead>
  <tbody>
    <tr><td>0</td><td>chute_stepper</td><td>uart0</td><td>0</td><td>GND (2-3)</td><td>GND (2-3)</td></tr>
    <tr><td>1</td><td>c_channel_1_rotor</td><td>uart0</td><td>1</td><td>3V3 (1-2)</td><td>GND (2-3)</td></tr>
    <tr><td>2</td><td>c_channel_3_rotor</td><td>uart0</td><td>2</td><td>GND (2-3)</td><td>3V3 (1-2)</td></tr>
    <tr><td>3</td><td>carousel</td><td>uart0</td><td>3</td><td>3V3 (1-2)</td><td>3V3 (1-2)</td></tr>
    <tr><td>4</td><td>c_channel_2_rotor</td><td>uart1</td><td>0</td><td>GND (2-3)</td><td>GND (2-3)</td></tr>
  </tbody>
</table>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The fifth driver's headers are mirrored.</b> On the row of four, MS1 is on the left and pin 1 is at the bottom. On the fifth, MS2 is on the left and pin 1 is at the <b>top</b>. The board prints <b>!Double check!</b> there for this reason.</p>
</div>

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/control-board-prep/fifth-driver-mirrored.8a99926501a9d185.jpg" alt="Two annotated close-ups side by side. Left, a driver on uart0 with MS1 on the left and pin 1 marked at the bottom. Right, the fifth driver on uart1 with MS2 on the left and pin 1 marked at the top, next to the board's printed Double check warning">
  </figure>
</div>

A wrong address fails silently: that driver never answers and its stepper stays unconfigured. Compare yours against this before moving on.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/control-board-prep/all-jumpers-fitted.c43ce981ac07b696.jpg" alt="Top-down view of the fully populated control board on a bench, with five TMC2209 drivers, the Raspberry Pi Pico, and ten yellow jumpers fitted across the MS1 and MS2 headers">
  </figure>
</div>

## The RESET button

The button marked RESET, above the Pico, pulls the Pico's RUN pin low and restarts the firmware without cutting 24 V to the drivers. It is not BOOTSEL, the button on the Pico itself, which is what you hold to flash new firmware.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/control-board-prep/reset-button.8c2fea0889c58bb1.jpg" alt="Close-up of the board around the Raspberry Pi Pico, showing the small white RESET tactile button on the board next to the Pico's own BOOTSEL button">
    <figcaption>RESET on the board, BOOTSEL on the Pico.</figcaption>
  </figure>
</div>

Next: [the control board housing]({{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}).
