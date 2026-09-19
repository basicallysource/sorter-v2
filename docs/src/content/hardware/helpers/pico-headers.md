---
layout: default
title: Soldering Pico headers
type: how-to
section: hardware
slug: helper-pico-headers
kicker: Helpers — Soldering Pico headers
lede: Soldering 2.54 mm header pins to the Raspberry Pi Pico so it can seat in the control board.
permalink: /hardware/helpers/pico-headers/
author: barthel
contributors: [spencer]
og_image: https://assets.basically.website/sorter-docs/pico-headers-soldered-plain-full-fc3efcd791b5.jpg
warning: >-
  **AI-generated first draft.** Written from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=pico-headers), not from
  an actual build. The parts and quantities are real. The soldering is not photographed on a build.
parts_needed:
  - part: mcu-rpi-pico
    qty: 1
  - part: header-pins-254
    qty: 40
tools_needed: ["Soldering iron and solder", "Side cutters or pliers, to break the strip"]
---

The Pico ships bare. It will not seat in the [basically Embedded Control Board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}) until 2.54 mm header pins are soldered along both its long edges.

{% include step.html n="1" title="Break the strip into two rows of 20" %}

The pins arrive as one long breakaway strip. Break two rows of 20 off it. The strip snaps between any two pins, and side cutters or pliers give a cleaner break than fingers.

{% include step.html n="2" title="Solder the rows to the Pico" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The pins point away from the chip side</b>, the side with the black chip, the USB socket and the button. The plastic of each row sits flat against the other face, and you solder on the chip side. Undoing this means desoldering twenty pins.</p>
</div>

Set the iron to around 350C (660F), or 320C (610F) if your solder is leaded.

<ol class="numbered-steps">
  <li>Stand one row of 20 pins with the long ends down, in a breadboard if you have one.</li>
  <li>Lower the Pico onto the row, chip side up, until the plastic sits flat against it.</li>
  <li>Solder the pin at each end of the row.</li>
  <li>Check the row is square to the Pico, then solder the other 18.</li>
  <li>Do the other long edge the same way.</li>
</ol>

<div class="img-placeholder">Image coming: one row soldered along a long edge of the Pico, chip side up, the second row not yet on</div>

## The finished result

A Pico with two rows of 20 pins soldered on, pointing away from the chip side.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-soldered-plain-full-fc3efcd791b5.jpg" alt="A Raspberry Pi Pico on a white background, seen at an angle from above with the chip and micro USB socket facing up, and two rows of twenty header pins soldered along its long edges pointing down away from the board">
  <figcaption><cite>Manufacturer photo (Raspberry Pi Pico with headers fitted; seller not recorded).</cite></figcaption>
</figure>

It goes into its sockets in step 2 of [preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}). Flashing the firmware is covered in [software setup]({{ '/hardware/assembly/software-setup/' | relative_url }}).
