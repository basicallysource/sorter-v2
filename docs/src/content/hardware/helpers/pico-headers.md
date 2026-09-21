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
contributors: [spencer, brickcyclealice]
last_verified: 2026-09-21
og_image: https://assets.basically.website/sorter-docs/pico-headers-finished-build-w1600-fd41bda1d6d3.jpg
parts_needed:
  - part: mcu-rpi-pico
    qty: 1
  - part: header-pins-254
    qty: 40
tools_needed: ["Soldering iron and solder", "Side cutters or pliers, to break the strip", "A breadboard, or a block of soft wood and a vice"]
---

The Pico ships bare. It will not seat in the [basically Embedded Control Board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}) until 2.54 mm header pins are soldered along both its long edges.

{% include step.html n="1" title="Break the strip into two rows of 20" %}

The pins arrive as one long breakaway strip. Break two rows of 20 off it. The strip snaps between any two pins, and side cutters or pliers give a cleaner break than fingers.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-rows-broken-off-w1600-190c163caa68.jpg" alt="A bare Raspberry Pi Pico above two broken-off rows of twenty black header pins on a white surface">
  <figcaption>Two rows of 20, and the bare Pico. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="2" title="Fit both rows before you solder anything" %}

Push both rows into the Pico's holes by hand, one down each long edge, before the iron comes anywhere near it.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The pins point away from the chip side</b>, the side with the black chip, the USB socket and the button. The plastic of each row sits flat against the other face, and you solder on the chip side. Undoing this means desoldering twenty pins.</p>
</div>

Both rows in first is what keeps the Pico flat. Solder one row on its own and the board has nothing holding up its other edge, so it sets at an angle and will not drop into the control board's sockets.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-both-rows-fitted-w1600-10ae7c024dc7.jpg" alt="A Raspberry Pi Pico chip side up with both rows of header pins pushed into its holes and not yet soldered, the black plastic sitting flat under the board">
  <figcaption>Both rows fitted, nothing soldered yet. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="3" title="Stand it in something that holds the pins square" %}

Stand the pins in a breadboard, chip side up, so the Pico sits level and both hands are free.

If you do not have one, cut two saw slots a Pico's width apart in a block of soft wood, drop a row into each, and hold the block in a vice.

<div class="img-row">
  <figure><img src="https://assets.basically.website/sorter-docs/pico-headers-wood-jig-w1600-e6ba852126a4.jpg" alt="A Raspberry Pi Pico sitting flat on a block of soft wood, its two rows of pins dropped into two saw slots cut into the block"><figcaption>Two saw slots in a block of wood do the same job as a breadboard. <cite>Photo: BrickCycleAlice.</cite></figcaption></figure>
  <figure><img src="https://assets.basically.website/sorter-docs/pico-headers-jig-in-vice-w1600-6c4d48fd9cff.jpg" alt="The wooden block with the Pico on it clamped upright between the jaws of a vice"><figcaption>The block in a vice, with the chip side facing you. <cite>Photo: BrickCycleAlice.</cite></figcaption></figure>
</div>

{% include step.html n="4" title="Solder the 40 joints" %}

Set the iron to around 350C (660F), or 320C (610F) if your solder is leaded.

<ol class="numbered-steps">
  <li>Solder the pin at each end of one row.</li>
  <li>Check the Pico is still sitting flat and square on the pins. While only those two are soldered you can reheat one and push it straight.</li>
  <li>Solder the rest of that row, then do the other one.</li>
</ol>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-soldering-w1600-8a47ed674f29.jpg" alt="A soldering iron tip and a length of solder meeting a header pin on the chip side of a Pico held in the wooden block">
  <figcaption>Solder on the chip side, one pin at a time. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<div class="callout">
  <p><b>Getting clean joints.</b> Use the parts straight out of the packet: dust and finger oil on the pins or the pads fight the solder. Flux-cored solder carries enough flux on its own, so if you add any extra, add a little. Heat the pin and the pad together until the solder runs into the hole on its own, and then take the iron off: solder that has to be pushed into place was too cold, and an iron parked on a pin softens the black plastic holding the row out of square.</p>
</div>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-joints-chip-side-w1600-78b9af1ae940.jpg" alt="The chip side of a finished Pico seen from above, with all forty header pins soldered into their holes">
  <figcaption>All 40 joints, on the chip side. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

## The finished result

A Pico with two rows of 20 pins soldered on, pointing away from the chip side.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-finished-build-w1600-fd41bda1d6d3.jpg" alt="A finished Raspberry Pi Pico at an angle on a white surface, chip side up, with two rows of twenty soldered header pins pointing down away from the board">
  <figcaption><cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

It goes into its sockets in step 2 of [preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}). Flashing the firmware is covered in [software setup]({{ '/hardware/software-setup/' | relative_url }}).
