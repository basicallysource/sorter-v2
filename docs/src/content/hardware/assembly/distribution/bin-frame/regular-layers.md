---
layout: default
title: Regular layers
type: how-to
section: hardware
slug: assembly-regular-layers
kicker: Bin frame — Regular layers
lede: The repeating bin layers above the base. Build N−2 for an N-layer machine.
permalink: /hardware/assembly/distribution/bin-frame/regular-layers/
author: zed0
contributors: [brickcyclealice, barthel]
warning: >-
  **Reorganized to reference [Build the hex frame]({{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }})
  instead of describing frame construction inline, not yet reviewed by a
  builder.** The old steps 1-2 (outer ring, spokes) are gone; build a hex
  frame on that page first. Correct it as you build.
parts_needed:
  - part: ext-bracket-bottom-vertical
    qty: 6
  - part: ext-2020-c
    qty: 6
  - part: scr-m5-16-shcs
    qty: 36
---

Each layer holds one chute-and-bin pair (built separately) that catches pieces routed to it; a regular layer's job is simply to repeat the same hexagonal ring, vertical supports, and flange joint as the layer below it, so the stack can go as tall as the machine needs.

This guide covers creating a regular layer. It's also the basis for creating the top and bottom layers, so build N−2 of these for an N-layer machine (the [bottom two layers]({{ '/hardware/assembly/distribution/bin-frame/bottom-two-layers/' | relative_url }}) are covered separately).

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}">hex frame</a> before you start.</strong> It's a required component of this page, not covered here.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/hex-frame-finished-top-down-full-c6abfb4dad6e.jpg" alt="A finished hex frame from above, the alternating grey spoke and teal crossbeam pieces forming the inner ring inside the aluminum outer hexagon">
    <figcaption>A finished hex frame. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

The aluminum extrusion is cut to length; the [framing cut list](https://parts-calculator.basically.website/framing) has the exact dimensions for piece C. The bin retainers in step 2 are the only thing on this layer that takes {% include fastener.html size="M5" variant="t-nut" text="M5 T-nuts" %}, and they carry their own parts on their own page, so neither the retainers nor their fasteners are in the list above.

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

Slot piece C (Layer vertical support) of aluminum extrusion between the External bracket — cover and the External bracket — side. At typical cut length, piece C sits about 3 mm short of both the top and bottom of the bracket run. Position it so that 3 mm gap is at the bottom, leaving the extrusion flush (or nearly flush) at the top. Use 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws tapped through the holes near the bottom of the External bracket — side to secure the extrusion.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-vertical-bottom-bracket-w1600-a45e5b572247.png" alt="Close-up of an External bracket — bottom vertical at the base of a corner vertical extrusion">
    <figcaption><cite>Photo: zed0.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-verticals-top-w1600-400576ddb1b6.png" alt="Top view of the layer with vertical supports and bottom brackets at every corner">
    <figcaption><cite>Photo: zed0.</cite></figcaption>
  </figure>
</div>

On each corner, slide an External bracket — bottom vertical onto piece C (Layer vertical support), ensuring the angles of the External bracket — bottom vertical align at the bottom. Secure them with 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws through the outer holes on the External bracket — bottom vertical. The extrusion will typically sit a few millimeters below the top of the bracket. That's expected and doesn't affect fit. If it's flush or proud of the top, piece C is probably cut long, check it against the [framing cut list](https://parts-calculator.basically.website/framing).

Matching parts from the same print run are embossed with a shared set code (e.g. **"b2"**) on both the External bracket — side and the External bracket — bottom vertical. Keep marked pairs together so brackets don't get mixed across corners.

{% include step.html n="2" title="Add the bin retainers" %}

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-regular-layers-bin-retainers-installed-w1600-31bf32089e71.png" alt="Bin retainers fastened to the outer faces of the hexagon frame">
  <figcaption><cite>Photo: zed0.</cite></figcaption>
</figure>

Twelve retainers go on each layer, six pairs, one pair per face of the hexagon. They are the same on every bin layer, so the step is on its own page: **[Bin retainers]({{ '/hardware/assembly/distribution/bin-frame/bin-retainers/' | relative_url }})**, including the T-nuts they fasten into. Do it now, with the covers on and before the layer goes onto the stack, so you are still working on a frame you can turn around.

A regular layer is now complete.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>You will also need to construct a <a href="{{ '/hardware/assembly/distribution/chute/' | relative_url }}">Chute core</a> for each layer you build.</strong> Not covered on this page.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

{% include step.html n="3" title="Join the layer to the one below" %}

<figure class="figure-float-right">
  <a href="https://assets.basically.website/sorter-docs/assembly-regular-layers-layer-joint-section-full-71e3c366f4e7.png" target="_blank" rel="noopener">
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-layer-joint-section-w1600-b40f8b102c10.jpg" alt="Vertical cross-section through one corner of two stacked layers, with the lower layer's extrusion and bottom-vertical tube in blue, the upper layer's bracket in purple, the two screw pairs dashed in red, and six numbered callouts">
  </a>
  <figcaption>One corner where any two layers meet, cut through the centre of the profile. Blue is the lower layer, purple the layer above. The numbers match the list below. Click to enlarge. <cite>Drawn from the part geometry rather than from a build, by Balloon.</cite></figcaption>
</figure>

A finished layer already carries everything that spans up to the next one: piece C standing out of its External bracket — side, and the External bracket — bottom vertical capping that extrusion. Joining two layers is therefore only the flange joint at each of the six corners.

Set the next layer down so that each External bracket — bottom vertical's flange face meets the underside of that layer's External bracket — side, and drive 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws up through each flange into the bracket above. **That pair is the whole layer-to-layer fastening, 12 screws per joint.**

The numbers on the drawing:

<ol class="keyed-list">
  <li><strong>External bracket — side and cover</strong>, the 60.5 mm collar at each frame.</li>
  <li><strong>Piece C</strong>, 154 mm cut. It starts 3 mm above its own collar's underside and ends 3 mm below the flange face of the collar above, so it spans the whole 160 mm between one frame and the next.</li>
  <li><strong>External bracket — bottom vertical</strong>, 119.6 mm of tube. It sleeves the upper part of piece C, so the extrusion is not visible on an assembled machine, and its foot seats on the rim of its own layer's collar. That seat is what sets the 160 mm spacing between frames.</li>
  <li class="key-screw"><strong>The two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws that join the layers</strong>, up through the flange into the bracket above. The flange has a 5.6 mm clearance hole through 8 mm of plastic and the bracket above a 4.4 mm self-tapping hole 10 mm deep, so the screw is 8 mm of clearance and 8 mm of thread, and a longer one bottoms out before it clamps.</li>
  <li class="key-screw"><strong>The two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws that clamp the bracket onto the extrusion</strong>, self-tapping through the bracket wall. Piece C is held only here, in its own layer's bracket, and nothing screws into it from the layer above.</li>
  <li class="key-note"><strong>Where two pieces of C meet</strong>: they stop about 3 mm short of each other at the flange face and never touch.</li>
</ol>

Both screw pairs are drawn dashed because neither lies in the plane of the cut: the joining pair sits 20.6 mm either side of it, and the clamping pair comes in at 45° to it.
