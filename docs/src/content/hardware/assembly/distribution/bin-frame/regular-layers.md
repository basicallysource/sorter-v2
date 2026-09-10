---
layout: default
title: Regular layers
type: how-to
section: hardware
slug: assembly-regular-layers
kicker: Bin frame — Regular layers
lede: The repeating bin layers above the base. Build N−1 for an N-layer machine.
permalink: /hardware/assembly/distribution/bin-frame/regular-layers/
og_image: https://assets.basically.website/sorter-docs/assembly-regular-layers-finished-square-full-779529c4b5f5.png
author: zed0
contributors: [brickcyclealice, barthel]
parts_needed:
  - part: ext-bracket-bottom-vertical
    qty: 6
  - part: ext-2020-c
    qty: 6
  - part: scr-m5-16-shcs
    qty: 24
---

Each layer holds one chute-and-bin pair (built separately) that catches pieces routed to it; a regular layer's job is simply to repeat the same hexagonal ring, vertical supports, and flange joint as the layer below it, so the stack can go as tall as the machine needs.

This guide covers creating a regular layer, and every bin layer but the lowest one is a regular layer, so build **N−1 of these for an N-layer machine**. The [bottom layer]({{ '/hardware/assembly/distribution/bin-frame/bottom-layer/' | relative_url }}) is the remaining one: it is this layer with foot extensions in place of piece C and the casters under them, and it has its own page.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}">hex frame</a> before you start.</strong> It's a required component of this page, not covered here.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-hex-frame-finished-top-down-w1600-a62a42d595ca.jpg" alt="A finished hex frame from above: six B spokes and their printed crossbeams forming the inner ring inside the aluminum outer hexagon, with a printed corner bracket at each of the six vertices">
    <figcaption>A finished hex frame. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

The aluminum extrusion is cut to length; the [framing cut list](https://parts-calculator.basically.website/framing) has the exact dimensions for piece C. Nothing on this page takes a {% include fastener.html size="M5" variant="t-nut" text="T-nut" %}.

The 24 {% include fastener.html size="M5" variant="socket-button" length="16" %} in the list above are two pairs at each of the six corners, and nothing else on this page takes a screw:

- **12** clamping the External bracket — side onto piece C, 2 per corner (step 1)
- **12** through the External bracket — bottom vertical's outer holes onto the same extrusion, 2 per corner (step 1)

The hex frame's own 12 are on [its page]({{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}), the bin retainers' 24 are on [theirs]({{ '/hardware/assembly/distribution/bin-frame/bin-retainers/' | relative_url }}), and the 12 that join this layer to the one below it are on [Stacking the layers]({{ '/hardware/assembly/distribution/stacking-the-layers/' | relative_url }}), so a complete layer, joint included, is 72.

{% include fastener-legend.html %}

{% include step.html n="1" title="Install the verticals" %}

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-vertical-corner-detail-w1600-81d31a256733.png" alt="A corner with piece C vertical extrusion held between the External bracket — cover and the External bracket — side, seen from below">
    <figcaption><cite>Photo: zed0.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-verticals-installed-full-b1393c02452b.png" alt="The hexagon with vertical supports standing up at each corner">
    <figcaption><cite>Photo: zed0.</cite></figcaption>
  </figure>
</div>

<div class="callout">
  <p>The External bracket — covers are already on, fitted in <a href="{{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}#step-9">Build the hex frame, step 9</a>. If a corner is missing one, put it on before you stand piece C in it, because it is difficult to slide on afterwards.</p>
</div>

Slot a length of aluminum extrusion, **piece C (Layer vertical support), 154 mm**, between the External bracket — cover and the External bracket — side. At typical cut length, piece C sits about 3 mm short of both the top and bottom of the bracket run. Position it so that 3 mm gap is at the bottom, leaving the extrusion flush (or nearly flush) at the top. Use 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws tapped through the holes near the bottom of the External bracket — side to secure the extrusion.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-extrusion-below-bracket-top-w1600-d4f8bd1028e9.jpg" alt="Looking down onto the top of an External bracket — bottom vertical, with the end of piece C visible in the square socket sitting a few millimetres below the bracket's top face">
    <figcaption>Piece C sitting about 3 mm below the top of the bracket, which is what it should look like. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-corner-underside-w1600-a5f70eb168c7.jpg" alt="A layer corner seen from underneath: the end of piece C sitting below the rim of the collar, with the bracket's screws in their holes and the External bracket — bottom vertical tube below">
    <figcaption>The same thing from underneath, with the bracket's screws in place. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

On each corner, slide an External bracket — bottom vertical onto piece C (Layer vertical support), ensuring the angles of the External bracket — bottom vertical align at the bottom. Secure them with 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws through the outer holes on the External bracket — bottom vertical. The extrusion will typically sit a few millimeters below the top of the bracket. That's expected and doesn't affect fit. If it's flush or proud of the top, piece C is probably cut long, check it against the [framing cut list](https://parts-calculator.basically.website/framing).

Matching parts from the same print run are embossed with a shared set code (e.g. **"b2"**) on both the External bracket — side and the External bracket — bottom vertical. Keep marked pairs together so brackets don't get mixed across corners.

## The finished result

The hexagon closed, with a vertical standing in every corner under its External bracket — bottom vertical.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-regular-layers-finished-square-full-779529c4b5f5.png" alt="A finished regular layer from above: the hexagon of extrusion with its spokes and crossbeams, and a vertical support capped by an External bracket — bottom vertical standing at each of the six corners">
  <figcaption>A finished regular layer, from above. <cite>Photo: zed0.</cite></figcaption>
</figure>

The [Bin frame]({{ '/hardware/assembly/distribution/bin-frame/' | relative_url }}) page contains the instructions for the entire stack, and is where you should return once you're done here.
