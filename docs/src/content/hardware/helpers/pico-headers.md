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
og_image: https://assets.basically.website/sorter-docs/pico-headers-soldered-build-angled-w1600-fd41bda1d6d3.jpg
last_verified: 2026-09-21
parts_needed:
  - part: mcu-rpi-pico
    qty: 1
  - part: header-pins-254
    qty: 40
tools_needed: ["Soldering iron and solder", "Side cutters or pliers, to break the strip", "A breadboard, or a piece of soft wood and a vice"]
---

The Pico ships bare. It will not seat in the [basically Embedded Control Board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}) until 2.54 mm header pins are soldered along both its long edges.

{% include step.html n="1" title="Break the strip into two rows of 20" %}

The pins arrive as one long breakaway strip. Break two rows of 20 off it. The strip snaps between any two pins, and side cutters or pliers give a cleaner break than fingers.

{% include step.html n="2" title="Fit both rows before you solder anything" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The pins point away from the chip side</b>, the side with the black chip, the USB socket and the button. The plastic of each row sits flat against the other face, and you solder on the chip side. Undoing this means desoldering twenty pins.</p>
</div>

Push both rows of 20 into the Pico, long ends down, until the plastic sits flat against the board. Both rows go in now, before the iron touches anything: solder one row on its own and the second one has to follow whatever angle the first one set, and the Pico will not sit flat in the control board.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-rows-fitted-w1600-10ae7c024dc7.jpg" alt="A Raspberry Pi Pico held chip side up with both rows of twenty header pins pushed into its long edges, the black plastic of each row flat against the underside and the pins pointing down">
  <figcaption>Both rows in, nothing soldered yet. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="3" title="Stand the pins in something that holds them square" %}

A breadboard does this if you have one. If you do not, two saw cuts in a piece of soft wood do the same job: cut them 17.8 mm (0.7 in) apart, which is the spacing of the Pico's two rows, drop the pins into the cuts and hold the wood in a vice. The Pico sits flat on the wood with both of your hands free.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-wood-jig-vice-w1600-6c4d48fd9cff.jpg" alt="A Pico resting flat on a block of soft wood held in a vice, with its two rows of pins dropped into a pair of saw cuts running along the block">
  <figcaption>Two saw cuts in a scrap of wood, held in a vice. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="4" title="Solder the four corners, then the rest" %}

Set the iron to around 350C (660F), or 320C (610F) if your solder is leaded.

Use as little flux as the joint needs. Get each joint hot enough that the solder runs down into the hole instead of sitting on top of it, and no hotter: the black plastic of the header softens if you dwell on a pin. Pins and board straight out of the packet solder best, since dust and finger oil both make it harder.

Solder one pin at each end of both rows, four joints in total. Check that the Pico is still flat against the plastic and that both rows are square to it; if one corner stands proud, reheat that joint and press the board down by its edge. Then solder the remaining 36.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-soldering-first-pin-w1600-8a47ed674f29.jpg" alt="A soldering iron tip and a length of solder meeting a corner pin on the chip side of a Pico, the board sitting on its wooden support in a vice">
  <figcaption>The first corner joint. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

## The finished result

A Pico with two rows of 20 pins soldered on, pointing away from the chip side.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-soldered-build-angled-w1600-fd41bda1d6d3.jpg" alt="A Raspberry Pi Pico on a white background, seen at an angle from above with the chip and micro USB socket facing up, forty bright solder joints along its long edges and the pins pointing down away from the board">
  <figcaption><cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

It goes into its sockets in step 2 of [preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}). Flashing the firmware is covered in [software setup]({{ '/hardware/software-setup/' | relative_url }}).
