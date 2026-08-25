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
parts_needed:
  - part: ext-bracket-left
    qty: 6
  - part: ext-bracket-cover
    qty: 6
  - part: ext-bracket-bottom-vertical
    qty: 6
  - part: frame-90deg-bracket
    qty: 12
  - part: frame-crossbeam
    qty: 6
  - part: bin-retainer-left
    qty: 6
  - part: bin-retainer-right
    qty: 6
  - part: ext-2020-ag
    qty: 6
  - part: ext-2020-bh
    qty: 6
  - part: ext-2020-c
    qty: 6
  - part: scr-m5-16-shcs
    qty: 36
  - part: scr-m5-20-shcs
    qty: 12
  - part: scr-m5-12-shcs
    qty: 12
  - part: tnut-m5-2020
    qty: 36
---

This guide covers creating a regular layer. It's also the basis for creating the top and bottom layers, so build N−2 of these for an N-layer machine (the [bottom two layers]({{ '/hardware/assembly/distribution/bin-frame/bottom-two-layers/' | relative_url }}) are covered separately).

Note that some of the ordering in this guide may seem unusual, but it's written this way to avoid both putting unnecessary strain on pieces, and allowing for the use of slide-in T-nuts.

The aluminum extrusion is cut to length; the [framing cut list](https://parts-calculator.basically.website/framing) has the exact dimensions for pieces A/G, B/H and C. The number of {% include fastener.html size="M5" variant="t-nut" text="M5 T-nuts" %} listed above is the minimum you'll need if you thread the printed parts directly wherever possible; this number increases if you use T-nuts throughout instead.

{% include fastener-legend.html %}

{% include step.html n="1" title="Assemble the frame brackets" %}

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-frame-corner-joint-w1600-a47ad55fb797.png" alt="Two A/G aluminum extrusions meeting at an External bracket — side, forming one corner of the hexagon">
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-frame-corner-joint-angled-w1600-6265c41bbf5f.png" alt="Angled view of the same corner joint, showing the fasteners along the extrusion">
  </figure>
</div>

Slide piece A/G (Outer horizontal / Horizontal interface frame) of aluminum extrusion into an External bracket — side. Use an {% include fastener.html size="M5" variant="socket-button" length="16" %} screw to tap directly through the outer of the two adjacent holes on the External bracket — side, bracing it against the extrusion. If you would rather not tap and brace, place T-nuts in the extrusion and use the inner holes to fasten into them instead.

If you are using slide-in T-nuts rather than drop-in or roll-in T-nuts, insert 2 into the innermost section of the extrusion and 4 into the outermost section before connecting the next External bracket — side, as this is the last time the ends of the extrusion are accessible.

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/LWruBv-fMz4"
    title="Assembling the frame brackets"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-extrusion-tnut-holes-w1600-b5863688aeea.png" alt="Side view of an A/G extrusion showing the row of holes where T-nuts sit and the screws pass through">
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-extrusion-into-bracket-w1600-1cd20074b56c.png" alt="An A/G extrusion sliding into an External bracket — side">
  </figure>
</div>

Repeat these steps to make two semi-circles of three sections of extrusion and three External bracket — sides, then slot the two half-hexagons together into a full hexagon and secure it with 2 more {% include fastener.html size="M5" variant="socket-button" length="16" %} screws. Joining in this manner, rather than working your way around the hexagon, prevents having to force the brackets into awkward angles.

<img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-regular-layers-two-half-hexagons-full-5e7c0f80f57f.png" alt="Two three-section half-hexagons laid out before being joined into a full hexagon">

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-hexagon-assembled-full-a1fb3a1b6fb4.png" alt="The completed hexagon frame of six A/G extrusions and six corner brackets">
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-hexagon-assembled-top-w1600-5a469702622a.png" alt="Top-down view of the completed hexagon frame">
  </figure>
</div>

{% include step.html n="2" title="Attach the spokes" %}

Prepare 12 Frame 90° brackets by drilling out the holes on the long side to allow an M5 screw to rotate freely. If you do not have a drill of the correct diameter, this can also be done using an electric screwdriver to overtighten an M5 screw, thus breaking the threads.

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/ULeByfqfVZs"
    title="Preparing the Frame 90° brackets and attaching the spokes"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

<img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-regular-layers-spoke-brackets-attached-w1600-47b3c12e2344.png" alt="Two Frame 90° brackets fastened to the inner face of an A/G extrusion, seen from inside the hexagon">

Loosely attach the long side of 2 Frame 90° brackets to the inner of one piece of the A/G (Outer horizontal / Horizontal interface frame) extrusion of your hexagon using 2 {% include fastener.html size="M5" variant="socket-button" length="12" %} screws, either into your 2 existing slide-in T-nuts or with drop-in / roll-in T-nuts.

Slide piece B/H (Spoke / Interface spoke (short)) of aluminum extrusion into the 2 Frame 90° brackets that you have just placed, and secure it with 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws tapped directly into the Frame 90° brackets, bracing against the extrusion. You can now tighten up the {% include fastener.html size="M5" variant="socket-button" length="12" %} screws that were previously holding the Frame 90° brackets loosely in place.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-spoke-installed-w1600-536d49087ec4.png" alt="A B/H spoke extrusion standing up in the two Frame 90° brackets">
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-spoke-crossbeams-first-full-dca5e96ee46d.png" alt="A spoke with a Frame crossbeam slid into place on each side">
  </figure>
</div>

On each side of this B/H (Spoke / Interface spoke (short)) slide a Frame crossbeam into place until it is level with the end of the extrusion, and secure it with an {% include fastener.html size="M5" variant="socket-button" length="20" %} screw.

Perform these steps 2 more times, on every 2nd side of the hexagon.

<img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-regular-layers-spokes-crossbeams-top-full-d16c233ea6e1.png" alt="Top-down view of three spokes with crossbeams, forming a partial inner ring">

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-spokes-progress-1-w1600-bfbe2a608499.png" alt="The hexagon partway through spoke installation, some sides done">
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-spokes-progress-2-w1600-5a478c564363.png" alt="More spokes and crossbeams filled in around the hexagon">
  </figure>
</div>

On each of the remaining 3 sides of the hexagon, use 2 {% include fastener.html size="M5" variant="socket-button" length="12" %} screws (either into your 2 existing slide-in T-nuts or with drop-in / roll-in T-nuts) to loosely fasten 2 Frame 90° brackets, aligning them with the gap in the Frame crossbeams. Slide the remaining B/H (Spoke / Interface spoke (short)) pieces into the slots, through both the Frame crossbeams and Frame 90° brackets.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-spokes-progress-3-w1600-e63cf43ad122.png" alt="Nearly all spokes and crossbeams installed">
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-spokes-nearly-complete-w1600-8911fb6fef42.png" alt="The spoke ring almost complete, seen at an angle">
  </figure>
</div>

<img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-regular-layers-spokes-complete-top-full-f9b0a154d84b.png" alt="Top-down view of the finished hexagon with all six spokes and crossbeams forming the central ring">

Secure them in place with 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws tapped into the Frame 90° brackets and 2 {% include fastener.html size="M5" variant="socket-button" length="20" %} screws through the Frame crossbeams. You can now tighten up the {% include fastener.html size="M5" variant="socket-button" length="12" %} screws that were previously holding the Frame 90° brackets loosely in place.

<div class="callout">
  <p>If you are currently building the interface layer, stop here and return to the interface layer guide.</p>
</div>

{% include step.html n="3" title="Install the verticals" %}

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-vertical-corner-detail-w1600-81d31a256733.png" alt="A corner with piece C vertical extrusion held between the External bracket — cover and the External bracket — side, seen from below">
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-verticals-installed-full-b1393c02452b.png" alt="The hexagon with vertical supports standing up at each corner">
  </figure>
</div>

On each corner of your hexagon, slot an External bracket — cover onto the External bracket — side (do this before attaching the extrusion, since it's tricky to get in place afterwards). Slot piece C (Layer vertical support) of aluminum extrusion between the External bracket — cover and the External bracket — side. At typical cut length you can leave this 3 mm short at either end, so try to align it about 3 mm above the bottom. Use 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws tapped through the holes near the bottom of the External bracket — side to secure the extrusion.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-vertical-bottom-bracket-w1600-a45e5b572247.png" alt="Close-up of an External bracket — bottom vertical at the base of a corner vertical extrusion">
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-verticals-top-w1600-400576ddb1b6.png" alt="Top view of the layer with vertical supports and bottom brackets at every corner">
  </figure>
</div>

On each corner, slide an External bracket — bottom vertical onto piece C (Layer vertical support), ensuring the angles of the External bracket — bottom vertical align at the bottom. Secure them with 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws through the outer holes on the External bracket — bottom vertical. The extrusion will likely rest a few mm below the top.

Matching parts from the same print run are embossed with a shared set code (e.g. **"b2"**) on both the External bracket — side and the External bracket — bottom vertical. Keep marked pairs together so brackets don't get mixed across corners.

{% include step.html n="4" title="Add the bin retainers" %}

<img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-regular-layers-bin-retainers-installed-w1600-31bf32089e71.png" alt="Bin retainers fastened to the outer faces of the hexagon frame">

On each side of the hexagon, attach both the Bin retainer (left) and Bin retainer (right) to the front side of A/G (Outer horizontal / Horizontal interface frame) using 4 {% include fastener.html size="M5" variant="socket-button" length="12" %} screws, either into the T-nuts already installed there or with drop-in / roll-in T-nuts.

A regular layer is now complete. You will also need to construct a [Chute core]({{ '/hardware/assembly/distribution/chute/' | relative_url }}) for each layer you build.

{% include step.html n="5" title="Join the layer to the one below" %}

<figure class="figure-float-right">
  <a href="https://assets.basically.website/sorter-docs/assembly-regular-layers-layer-joint-section-full-71e3c366f4e7.png" target="_blank" rel="noopener">
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-layer-joint-section-w1600-b40f8b102c10.jpg" alt="Vertical cross-section through one corner of two stacked layers, with the lower layer's extrusion and bottom-vertical tube in blue, the upper layer's bracket in purple, the two screw pairs dashed in red, and six numbered callouts">
  </a>
  <figcaption>One corner where any two layers meet, cut through the centre of the profile. Blue is the lower layer, purple the layer above. The numbers match the list below. Click to enlarge. Drawn from the part geometry rather than from a build.</figcaption>
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
