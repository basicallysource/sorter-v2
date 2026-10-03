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

<div class="callout">
  <p><b>This step is optional.</b> The parts catalog buys a Pico with its two rows of 20 pins already fitted, so a standard build skips this page. The bare Pico and the 40 header pins listed above are not counted into a machine's parts list, so buy them only if you would rather solder the pins on yourself.</p>
</div>

A bare Pico will not seat in the [basically Embedded Control Board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}) until 2.54 mm header pins are soldered along both its long edges.

{% include step.html n="1" title="Break the strip into two rows of 20" %}

The pins arrive as one long breakaway strip. Break two rows of 20 off it. The strip snaps between any two pins, and side cutters or pliers give a cleaner break than fingers.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-rows-of-20-broken-w1600-190c163caa68.jpg" alt="A bare Raspberry Pi Pico on a white surface with two broken-off rows of twenty black header pins lying below it">
  <figcaption>Two rows of 20 off the strip, next to the bare Pico. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="2" title="Fit both rows before you solder anything" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The pins point away from the chip side</b>, the side with the black chip, the USB socket and the button. The plastic of each row sits flat against the other face, and you solder on the chip side. Undoing this means desoldering forty pins.</p>
</div>

Push both rows of 20 into the Pico, long ends down, until the plastic sits flat against the board. Both rows go in now, before the iron touches anything: solder one row on its own and the second one has to follow whatever angle the first one set, and the Pico will not sit flat in the control board.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-both-rows-unsoldered-w1600-cf7c0d9f83af.jpg" alt="A side view of a Raspberry Pi Pico chip side up with a row of twenty header pins pushed into each long edge, both rows of black plastic flat against the underside, the pads still bare gold with no solder on them">
  <figcaption>Both rows in, pads still bare. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="3" title="Stand the pins in something that holds them square" %}

A breadboard does this if you have one. If you do not, two saw cuts in a piece of soft wood do the same job: cut them 17.8 mm (0.7 in) apart, which is the spacing of the Pico's two rows, drop the pins into the cuts and hold the wood in a vice. The Pico sits flat on the wood with both of your hands free.

<div class="img-row">
  <figure><img src="https://assets.basically.website/sorter-docs/pico-headers-wood-jig-w1600-e6ba852126a4.jpg" alt="A Raspberry Pi Pico sitting flat on a block of soft wood, its two rows of pins dropped into two saw slots cut into the block"><figcaption>A row of pins in each saw cut, the board flat on the wood. <cite>Photo: BrickCycleAlice.</cite></figcaption></figure>
  <figure><img src="https://assets.basically.website/sorter-docs/pico-headers-wood-jig-vice-w1600-6c4d48fd9cff.jpg" alt="The wooden block with the Pico standing on it, clamped between the jaws of a vice"><figcaption>The block in a vice, chip side up and both hands free. <cite>Photo: BrickCycleAlice.</cite></figcaption></figure>
</div>

{% include step.html n="4" title="Solder the four corners, then the rest" %}

Set the iron to around 350C (660F), or 320C (610F) if your solder is leaded.

<div class="callout">
  <p><b>Getting clean joints.</b> Use the parts straight out of the packet: dust and finger oil on the pins or the pads fight the solder. Flux-cored solder carries enough flux on its own, so if you add any extra, add a little. Heat the pin and the pad together until the solder runs into the hole on its own, then take the iron off. Solder that has to be pushed into place was too cold, and an iron parked on a pin softens the black plastic that is holding the row square.</p>
</div>

Solder one pin at each end of both rows, four joints in total. Then look along the board: if a row leans, or a plastic body has lifted off the Pico, reheat that corner and press it down before going further. Then solder the remaining 36.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-soldering-first-pin-w1600-8a47ed674f29.jpg" alt="A soldering iron tip and a length of solder meeting a corner pin on the chip side of a Pico, with the pin at the far end of the same row already soldered, the board sitting on its wooden support in a vice">
  <figcaption>Tacking the corners: the second one going in, the first already done. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-soldered-side-flush-w1600-5c3fab4115be.jpg" alt="Close side view of the soldered Pico showing a solder fillet on every pad along the chip side and the black plastic of the header pressed flat against the underside of the board">
  <figcaption>What to check when you are done: a fillet on every pad, and no gap between the plastic and the board. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

## The finished result

A Pico with two rows of 20 pins soldered on, pointing away from the chip side.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/pico-headers-soldered-build-angled-w1600-fd41bda1d6d3.jpg" alt="A Raspberry Pi Pico on a white background, seen at an angle from above with the chip and micro USB socket facing up, forty bright solder joints along its long edges and the pins pointing down away from the board">
  <figcaption><cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

It goes into its sockets in step 2 of [preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}). Flashing the firmware is covered in [software setup]({{ '/hardware/software-setup/' | relative_url }}).
