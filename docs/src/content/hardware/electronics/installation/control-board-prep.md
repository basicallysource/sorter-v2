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
  - part: drv-tmc2209
    qty: 5
  - part: mcu-rpi-pico
    qty: 1
  - part: jumper-cap-254
    qty: 10
---

Do this with the board loose, before the [housing]({{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}). Solder the [Pico headers]({{ '/hardware/electronics/installation/pico-headers/' | relative_url }}) first.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-prep-board-and-drivers-w1600-f6a7efe7c0f4.jpg" alt="The bare green basically Embedded Control Board on a wooden bench with five blue-finned TMC2209 stepper driver modules laid out in a row above it">
  </figure>
</div>

{% include step.html n="1" title="Seat the five drivers" %}

Heatsink up, EN/MS1/MS2 edge towards the middle of the board. Module and socket are both silkscreened, so match the labels.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-prep-tmc2209-pin-labels-w1600-aed1004e7d8a.jpg" alt="A single TMC2209 V1.3 driver module standing on a bench, blue heatsink upwards, with its pin names readable around the edge">
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-prep-driver-seated-w1600-6f0cbd6bc7ae.jpg" alt="A TMC2209 driver pushed fully down into its socket on the control board, heatsink upwards, with the remaining drivers out of focus behind">
  </figure>
</div>

{% include step.html n="2" title="Seat the Pico" %}

Into the two long sockets down the middle, USB end towards the edge of the board.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-prep-pico-seating-w1600-4b85e9758bc6.jpg" alt="A Raspberry Pi Pico held just above its two long header sockets on the control board, ready to be pushed down, with seated stepper drivers behind it">
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-prep-pico-seated-w1600-f0cbb025b91c.jpg" alt="The Raspberry Pi Pico fully seated in its sockets on the control board, sitting flat and parallel to the board">
  </figure>
</div>

{% include step.html n="3" title="Set the address jumpers" %}

The drivers share a UART bus, so each needs an address, and the address is set by bridging MS1 and MS2: a jumper on pins 1-2 is 3V3 and reads HIGH, on 2-3 is GND and reads LOW, with MS1 the low bit. Two pins allow four addresses, one short of five steppers, so the board runs a second bus for the fifth driver. Ten jumpers in total, two per driver.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-prep-jumper-states-w1600-5c293a831c56.jpg" alt="Annotated close-up of one driver's MS1 and MS2 headers: MS1 boxed in green with its jumper on pins 1 and 2 for 3V3, MS2 boxed in blue with its jumper on pins 2 and 3 for GND, beside a table mapping the four combinations to addresses 0 to 3">
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
  <p>Read the 1 2 3 printed beside every header. The fifth driver's block is mirrored, which is why the board prints <b>!Double check!</b> next to it, and a wrong address fails silently: that driver never answers and its stepper stays unconfigured.</p>
</div>

This is a correctly jumpered board.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-prep-all-jumpers-fitted-w1600-f470f24a8913.jpg" alt="Top-down view of the fully populated control board, with five TMC2209 drivers, the Raspberry Pi Pico, and ten yellow jumpers fitted across the MS1 and MS2 headers">
  </figure>
</div>

Next: [the control board housing]({{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}).
