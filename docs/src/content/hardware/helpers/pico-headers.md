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
  an actual build. The parts and quantities are real. The soldering is not photographed on a
  build; the finished result below is a supplier photo of a Pico with the pins already on.
parts_needed:
  - part: mcu-rpi-pico
    qty: 1
  - part: header-pins-254
    qty: 40
tools_needed: ["Soldering iron and solder", "Side cutters or pliers, to break the strip"]
---

The Pico ships bare. The [basically Embedded Control Board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}) takes it on 2.54 mm header pins, so the pins are a separate purchase and a soldering job before the board is worked on.

{% include step.html n="1" title="Break the strip into two rows of 20" %}

The pins arrive as one long breakaway strip. Break it into two rows of 20 pins, which is the 40 the Pico takes. It snaps between any two pins; side cutters or pliers give a cleaner break than fingers.

{% include step.html n="2" title="Solder the rows to the Pico" %}

A row goes in the 20 holes down each long edge. The three holes in the short end of the board are the debug pads and take nothing here.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The pins point away from the chip side.</b> The chip side is the one carrying the RP2040 chip, the USB socket and the BOOTSEL button. The black plastic of each row sits flat against the other face, and you solder on the chip side. Getting this wrong means desoldering twenty pins, so check it before the iron touches anything.</p>
</div>

<ol class="numbered-steps">
  <li>Stand one row of 20 pins with the long ends down, in a breadboard if you have one.</li>
  <li>Lower the Pico onto the row, chip side up, until the plastic is flat against the board.</li>
  <li>Solder the two end pins first. Check the row sits square, then solder the other 18.</li>
  <li>Do the other edge the same way.</li>
</ol>

<div class="img-placeholder">Image coming: one row soldered along a long edge of the Pico, chip side up, the second row not yet on</div>

## The finished result

A Pico with two rows of 20 pins soldered on, both rows pointing away from the chip side.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-soldered-plain-full-fc3efcd791b5.jpg" alt="A Raspberry Pi Pico on a white background, seen at an angle from above with the chip and micro USB socket facing up, two rows of twenty header pins soldered along its long edges and pointing down away from the board, the solder visible on each joint and the three DEBUG pads at the near end left bare">
  <figcaption>Pins on both long edges, pointing away from the chip side, soldered on the chip side. The three DEBUG pads at the near end stay bare. <cite>Manufacturer photo (Raspberry Pi Pico with headers fitted; seller not recorded).</cite></figcaption>
</figure>

It goes into its sockets in step 2 of [preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}). Flashing the firmware is covered in [software setup]({{ '/hardware/assembly/software-setup/' | relative_url }}).
