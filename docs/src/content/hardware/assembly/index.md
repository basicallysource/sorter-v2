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
  <figcaption>The finished machine cut down the middle, so the sections below have something to build towards. Feeder on top, chute down the centre, bins on the frame. Click to enlarge. <cite>Rendered from the machine's CAD rather than from a build. Renderer not recorded.</cite></figcaption>
</figure>

Before starting, source everything on the [Bill of materials](https://parts-calculator.basically.website/hardware) and print the required parts — see [Parts]({{ '/hardware/parts/' | relative_url }}) for individual part references. Then follow the sections below top to bottom.

A few names recur across these sections and are worth fixing here, once: the feeder's three channels are C1, C2 and C3, first through third; "the control board" means basically board v1.3, the basically Embedded Control Board; and the printed enclosure around each of the PSU, Orange Pi and control board is the same kind of part even though each page names its own differently (housing, box, mount).

## Order of operations

1. **[Distribution]({{ '/hardware/assembly/distribution/' | relative_url }})** — bin frame, top interface, and chute. The interface layer is built as part of distribution.
2. **[Feeder]({{ '/hardware/assembly/feeder/' | relative_url }})** — the C-channel stages that meter parts in.
3. **[Electronics]({{ '/hardware/electronics/' | relative_url }})** — boards, wiring, and steppers.
4. **[Install the bins]({{ '/hardware/assembly/install-bins/' | relative_url }})** — printed or laser cut, dropped into the finished tower.
5. **[Software setup]({{ '/hardware/software-setup/' | relative_url }})** — flash and configure. Hands off to the [Sorter]({{ '/sorter/' | relative_url }}) section.

<div class="clear-float"></div>
