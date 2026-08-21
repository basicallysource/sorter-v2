---
layout: default
title: Pico headers
type: how-to
section: hardware
slug: electronics-pico-headers
kicker: Electronics — Pico headers
lede: Soldering 2.54 mm header pins to the Raspberry Pi Pico so it can seat in the control board.
permalink: /hardware/electronics/installation/pico-headers/
author: barthel
contributors: [spencer]
warning: >-
  **Skeleton page.** The parts are recorded in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=pico-headers); the
  procedure is not recorded anywhere. Nothing here has been checked against a build.
parts_needed:
  - part: mcu-rpi-pico
    qty: 1
  - part: header-pins-254
    qty: 20
---

The Pico ships bare. The control board expects it on 2.54 mm headers, so the pins are a separate purchase and a soldering job before the board goes on its [mount]({{ '/hardware/electronics/installation/control-board-mount/' | relative_url }}).

- **One per machine**, the same Pico the control board carries.
- 20 header pins, two 20-pin rows broken to length.

{% include step.html n="1" title="Break the headers to length" %}

Two rows of 20. Snap them off a breakaway strip.

<div class="img-placeholder">Image coming</div>

{% include step.html n="2" title="Solder them on" %}

Which side the pins go on, and therefore which way up the Pico sits in the board, is not recorded here. Check the board before soldering, because it cannot be undone easily.

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Seat it in the board" %}

The Pico goes into its socket on the basically Embedded Control Board. Flashing the firmware is covered in [software setup]({{ '/hardware/assembly/software-setup/' | relative_url }}).
