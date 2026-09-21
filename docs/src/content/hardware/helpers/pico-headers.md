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
og_image: https://assets.basically.website/sorter-docs/pico-headers-soldered-build-angle-w1600-8a2bec64f920.jpg
parts_needed:
  - part: mcu-rpi-pico
    qty: 1
  - part: header-pins-254
    qty: 40
tools_needed: ["Soldering iron and solder", "Side cutters or pliers, to break the strip", "A strip of wood or a breadboard to stand the Pico on"]
---

The Pico ships bare. It will not seat in the [basically Embedded Control Board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}) until 2.54 mm header pins are soldered along both its long edges.

{% include step.html n="1" title="Break the strip into two rows of 20" %}

The pins arrive as one long breakaway strip. Break two rows of 20 off it. The strip snaps between any two pins, and side cutters or pliers give a cleaner break than fingers.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-rows-of-20-broken-w1600-190c163caa68.jpg" alt="A bare Raspberry Pi Pico on a white surface with two broken-off rows of twenty black header pins lying below it">
  <figcaption>Two rows of 20 off the strip, next to the bare Pico. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="2" title="Fit both rows, then solder" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Fit both rows before you solder anything.</b> Solder one row on its own and nothing holds the second one in the same plane, so the Pico ends up sitting on a twist and will not go flat into the control board's sockets. Pushed in dry, the two rows hold each other square and the board rests flat on them.</p>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The pins point away from the chip side</b>, the side with the black chip, the USB socket and the button. The plastic of each row sits flat against the other face, and you solder on the chip side. Undoing this means desoldering forty pins.</p>
</div>

Set the iron to around 350C (660F), or 320C (610F) if your solder is leaded.

<ol class="numbered-steps">
  <li>Push a row into each long edge of the Pico, long ends down, until the plastic sits flat against the board. Friction holds both rows there on their own.</li>
  <li>Stand the Pico chip side up on something narrower than the gap between the two rows, so the pins hang clear of the bench: a strip of wood, or a breadboard.</li>
  <li>Solder one pin at each of the four corners.</li>
  <li>Look along the board. If a row leans, or a plastic body has lifted off the Pico, reheat that corner and press it down before going further.</li>
  <li>Solder the remaining 36.</li>
</ol>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-both-rows-fitted-w1600-10ae7c024dc7.jpg" alt="A Raspberry Pi Pico chip side up with a row of twenty header pins pushed into each long edge, the black plastic bodies flat against the underside and the long pins pointing down">
  <figcaption>Both rows pushed in by hand, nothing soldered yet. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-dry-fit-jig-side-w1600-cf7c0d9f83af.jpg" alt="Side view of the Pico resting chip side up on a narrow strip of wood, with the two rows of header pins hanging down either side of the strip and the board sitting flat on their plastic">
  <figcaption>Standing on a strip of wood narrower than the two rows, so both sets of pins hang clear and the board sits flat. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-soldering-in-jig-w1600-8a47ed674f29.jpg" alt="A soldering iron tip and a length of solder wire meeting a pad at the corner of the Pico while it stands on the wooden strip">
  <figcaption>A corner pin first, with the board still held square by both rows. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-soldered-side-flush-w1600-5c3fab4115be.jpg" alt="Close side view of the soldered Pico showing a solder fillet on every pad along the chip side and the black plastic of the header pressed flat against the underside of the board">
  <figcaption>What to check for: a fillet on every pad, and no gap between the plastic and the board. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

## The finished result

A Pico with two rows of 20 pins soldered on, pointing away from the chip side, and the board flat on both of them.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-soldered-build-angle-w1600-8a2bec64f920.jpg" alt="A soldered Raspberry Pi Pico seen at an angle from above, chip side and micro USB socket facing up, with two rows of twenty header pins soldered along its long edges pointing down away from the board">
  <figcaption>A Pico off a build, both rows on. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

It goes into its sockets in step 2 of [preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}). Flashing the firmware is covered in [software setup]({{ '/hardware/software-setup/' | relative_url }}).
