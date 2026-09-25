---
layout: default
title: Assembly
type: landing
section: hardware
slug: assembly
kicker: Hardware — Assembly
lede: Build order for the machine. Follow the sections top to bottom.
permalink: /hardware/assembly/
author: spencer
---

<figure class="figure-float-right">
  <a href="https://assets.basically.website/web/section-full-e1f0ccc4b3e9.png" target="_blank" rel="noopener">
    <img src="https://assets.basically.website/web/section-full-e1f0ccc4b3e9.png" alt="Cutaway render of the whole machine sliced down its centre line: the hopper and the feeder's channels on top, the chute running down the middle of the tower, and the cardboard bins fanned out on both sides of the frame down to the casters">
  </a>
  <figcaption>Click to enlarge. <cite>Rendered from the machine's CAD rather than from a build. Renderer not recorded.</cite></figcaption>
</figure>

Before starting, source everything on the [Bill of materials](https://parts-calculator.basically.website/hardware) and print the required parts. [Printing the parts]({{ '/hardware/printing/' | relative_url }}) covers what printer they need and how they go on the plate, and [Parts]({{ '/hardware/parts/' | relative_url }}) has reference pages for individual parts. Then follow the sections below top to bottom.

A few names recur across these sections and are worth fixing here, once: the feeder's four channels are C1, C2, C3 and C4, top to bottom, and C4 is also called the classification channel; and "the control board" means basically board v1.3, the basically Embedded Control Board.

## Order of operations

<ol class="numbered-steps">
  <li><strong><a href="{{ '/hardware/assembly/distribution/' | relative_url }}">Distribution</a></strong>. Bin frame, top interface, and chute. The interface layer is built as part of distribution.</li>
  <li><strong><a href="{{ '/hardware/assembly/feeder/' | relative_url }}">Feeder</a></strong>. The C-channel stages that meter parts in.</li>
  <li><strong><a href="{{ '/hardware/electronics/' | relative_url }}">Electronics</a></strong>. Boards, wiring, and steppers.</li>
  <li><strong><a href="{{ '/hardware/assembly/install-bins/' | relative_url }}">Install the bins</a></strong>. Printed or laser cut, dropped into the finished tower.</li>
  <li><strong><a href="{{ '/hardware/software-setup/' | relative_url }}">Software setup</a></strong>. Flash and configure. Hands off to the <a href="{{ '/sorter/' | relative_url }}">Sorter</a> section.</li>
</ol>

## The finished result

Assembly's three sections each end in one of these. The electronics go on between the feeder and the bins.

<div class="img-row">
  <figure>
    <div class="img-placeholder">Image coming: the standing hex frame on its casters with the top interface under its deck, a chute in every layer and the bottom interface under them, no bins and no feeder yet</div>
    <figcaption><a href="{{ '/hardware/assembly/distribution/' | relative_url }}">Distribution</a>, the standing tower with its chutes in. <cite>Not photographed on a build yet.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-camera-lamps-from-above-w1600-285496e1bd00.jpg" alt="The feeder from above on a built machine: three camera lamps over their channels, each with its camera board in the middle of the cover and its leads running off to one side, with the black bulk hopper at the left and the steppers grouped in the centre">
    <figcaption><a href="{{ '/hardware/assembly/feeder/' | relative_url }}">Feeder</a>, four channels at their heights with three lamps over them. <cite>Photo: Daddy-O's Bricks - Bill.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/install-bins-printed-bins-from-above-w1600-3edc30bd133f.jpg" alt="A loaded distribution stack seen from above and to one side, five layers of blue printed bins radiating out around the corner column, casters on the floor below">
    <figcaption><a href="{{ '/hardware/assembly/install-bins/' | relative_url }}">Install the bins</a>, every bay on every layer loaded. <cite>Photo: Daddy-O's Bricks - Bill.</cite></figcaption>
  </figure>
</div>

<div class="clear-float"></div>
