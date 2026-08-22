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
    <img src="https://img.basically.website/web/assembly/regular-layers/frame-corner-joint.8cbfd8b7506bf318.png" alt="Two A/G aluminum extrusions meeting at an External bracket — side, forming one corner of the hexagon">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/frame-corner-joint-angled.e9321cce8978898d.png" alt="Angled view of the same corner joint, showing the fasteners along the extrusion">
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
    <img src="https://img.basically.website/web/assembly/regular-layers/extrusion-tnut-holes.51f13d97da6705d7.png" alt="Side view of an A/G extrusion showing the row of holes where T-nuts sit and the screws pass through">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/extrusion-into-bracket.f7f3b91c6fa374d4.png" alt="An A/G extrusion sliding into an External bracket — side">
  </figure>
</div>

Repeat these steps to make two semi-circles of three sections of extrusion and three External bracket — sides, then slot the two half-hexagons together into a full hexagon and secure it with 2 more {% include fastener.html size="M5" variant="socket-button" length="16" %} screws. Joining in this manner, rather than working your way around the hexagon, prevents having to force the brackets into awkward angles.

<img class="doc-figure" src="https://img.basically.website/web/assembly/regular-layers/two-half-hexagons.cfd5d241ba46d491.png" alt="Two three-section half-hexagons laid out before being joined into a full hexagon">

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/hexagon-assembled.9f17d897cec87f50.png" alt="The completed hexagon frame of six A/G extrusions and six corner brackets">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/hexagon-assembled-top.b6db35fc036a5185.png" alt="Top-down view of the completed hexagon frame">
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

<img class="doc-figure" src="https://img.basically.website/web/assembly/regular-layers/spoke-brackets-attached.bdf5459b2c7f06bc.png" alt="Two Frame 90° brackets fastened to the inner face of an A/G extrusion, seen from inside the hexagon">

Loosely attach the long side of 2 Frame 90° brackets to the inner of one piece of the A/G (Outer horizontal / Horizontal interface frame) extrusion of your hexagon using 2 {% include fastener.html size="M5" variant="socket-button" length="12" %} screws, either into your 2 existing slide-in T-nuts or with drop-in / roll-in T-nuts.

Slide piece B/H (Spoke / Interface spoke (short)) of aluminum extrusion into the 2 Frame 90° brackets that you have just placed, and secure it with 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws tapped directly into the Frame 90° brackets, bracing against the extrusion. You can now tighten up the {% include fastener.html size="M5" variant="socket-button" length="12" %} screws that were previously holding the Frame 90° brackets loosely in place.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/spoke-installed.63790c0e4cedaa87.png" alt="A B/H spoke extrusion standing up in the two Frame 90° brackets">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/spoke-crossbeams-first.4fbd6e2771158f5a.png" alt="A spoke with a Frame crossbeam slid into place on each side">
  </figure>
</div>

On each side of this B/H (Spoke / Interface spoke (short)) slide a Frame crossbeam into place until it is level with the end of the extrusion, and secure it with an {% include fastener.html size="M5" variant="socket-button" length="20" %} screw.

Perform these steps 2 more times, on every 2nd side of the hexagon.

<img class="doc-figure" src="https://img.basically.website/web/assembly/regular-layers/spokes-crossbeams-top.fdcfbec44d9a095d.png" alt="Top-down view of three spokes with crossbeams, forming a partial inner ring">

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/spokes-progress-1.6856de61dff00eff.png" alt="The hexagon partway through spoke installation, some sides done">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/spokes-progress-2.6b214ce9f91d3556.png" alt="More spokes and crossbeams filled in around the hexagon">
  </figure>
</div>

On each of the remaining 3 sides of the hexagon, use 2 {% include fastener.html size="M5" variant="socket-button" length="12" %} screws (either into your 2 existing slide-in T-nuts or with drop-in / roll-in T-nuts) to loosely fasten 2 Frame 90° brackets, aligning them with the gap in the Frame crossbeams. Slide the remaining B/H (Spoke / Interface spoke (short)) pieces into the slots, through both the Frame crossbeams and Frame 90° brackets.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/spokes-progress-3.46d6de1f2fd52a75.png" alt="Nearly all spokes and crossbeams installed">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/spokes-nearly-complete.8aeb3500e2d37363.png" alt="The spoke ring almost complete, seen at an angle">
  </figure>
</div>

<img class="doc-figure" src="https://img.basically.website/web/assembly/regular-layers/spokes-complete-top.517a329e0407cb17.png" alt="Top-down view of the finished hexagon with all six spokes and crossbeams forming the central ring">

Secure them in place with 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws tapped into the Frame 90° brackets and 2 {% include fastener.html size="M5" variant="socket-button" length="20" %} screws through the Frame crossbeams. You can now tighten up the {% include fastener.html size="M5" variant="socket-button" length="12" %} screws that were previously holding the Frame 90° brackets loosely in place.

<div class="callout">
  <p>If you are currently building the interface layer, stop here and return to the interface layer guide.</p>
</div>

{% include step.html n="3" title="Install the verticals" %}

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/vertical-corner-detail.6f223d95295eb5c8.png" alt="A corner with piece C vertical extrusion held between the External bracket — cover and the External bracket — side, seen from below">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/verticals-installed.c9fb491ca7ad6eb3.png" alt="The hexagon with vertical supports standing up at each corner">
  </figure>
</div>

On each corner of your hexagon, slot an External bracket — cover onto the External bracket — side (do this before attaching the extrusion, since it's tricky to get in place afterwards). Slot piece C (Layer vertical support) of aluminum extrusion between the External bracket — cover and the External bracket — side. At typical cut length you can leave this 3 mm short at either end, so try to align it about 3 mm above the bottom. Use 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws tapped through the holes near the bottom of the External bracket — side to secure the extrusion.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/vertical-bottom-bracket.85c0929e5a4e4ed0.png" alt="Close-up of an External bracket — bottom vertical at the base of a corner vertical extrusion">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/verticals-top.a0ee60c91903c400.png" alt="Top view of the layer with vertical supports and bottom brackets at every corner">
  </figure>
</div>

On each corner, slide an External bracket — bottom vertical onto piece C (Layer vertical support), ensuring the angles of the External bracket — bottom vertical align at the bottom. Secure them with 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws through the outer holes on the External bracket — bottom vertical. The extrusion will likely rest a few mm below the top.

{% include step.html n="4" title="Add the bin retainers" %}

<img class="doc-figure" src="https://img.basically.website/web/assembly/regular-layers/bin-retainers-installed.945ecff28147b1f1.png" alt="Bin retainers fastened to the outer faces of the hexagon frame">

On each side of the hexagon, attach both the Bin retainer (left) and Bin retainer (right) to the front side of A/G (Outer horizontal / Horizontal interface frame) using 4 {% include fastener.html size="M5" variant="socket-button" length="12" %} screws, either into the T-nuts already installed there or with drop-in / roll-in T-nuts.

A regular layer is now complete. You will also need to construct a [Chute core]({{ '/hardware/assembly/distribution/chute/' | relative_url }}) for each layer you build.

{% include step.html n="5" title="Join the layer to the one below" %}

<figure class="figure-float-right">
  <a href="https://img.basically.website/originals/assembly/regular-layers/layer-joint-section.11acc0911bc91277.png" target="_blank" rel="noopener">
    <img src="https://img.basically.website/web/assembly/regular-layers/layer-joint-section.21c4ee094a2c72b8.jpg" alt="Vertical cross-section through one corner of two stacked layers, with the lower layer's extrusion and bottom-vertical tube in blue, the upper layer's bracket in purple, the two screw pairs dashed in red, and six numbered callouts">
  </a>
  <figcaption>Section through one corner, cut through the centre of the profile. Blue is the lower layer, purple the layer above. Click to enlarge. Drawn from the part geometry rather than from a build.</figcaption>
</figure>

A finished layer already carries everything that spans up to the next one: piece C standing out of its External bracket — side, and the External bracket — bottom vertical capping that extrusion. Joining two layers is therefore only the flange joint at each of the six corners.

Set the next layer down so that each External bracket — bottom vertical's flange face meets the underside of that layer's External bracket — side, and drive 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws up through each flange into the bracket above. **That pair is the whole layer-to-layer fastening, 12 screws per joint.**

What the numbers mark:

1. **External bracket — side and cover**, the 60.5 mm collar at each frame.
2. **Piece C**, 154 mm cut. It starts 3 mm above its own collar's underside and ends 3 mm below the flange face of the collar above, so it spans the whole 160 mm between one frame and the next.
3. **External bracket — bottom vertical**, 119.6 mm of tube. It sleeves the upper part of piece C, so the extrusion is not visible on an assembled machine, and its foot seats on the rim of its own layer's collar. That seat is what sets the 160 mm spacing between frames.
4. **The two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws that join the layers**, up through the flange into the bracket above. The flange has a 5.6 mm clearance hole through 8 mm of plastic and the bracket above a 4.4 mm self-tapping hole 10 mm deep, so the screw is 8 mm of clearance and 8 mm of thread, and a longer one bottoms out before it clamps.
5. **The two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws that clamp the bracket onto the extrusion**, self-tapping through the bracket wall. Piece C is held only here, in its own layer's bracket, and nothing screws into it from the layer above.
6. **Where two pieces of C meet**: they stop about 3 mm short of each other at the flange face and never touch.

Both screw pairs are drawn dashed because neither lies in the plane of the cut: the joining pair sits 20.6 mm either side of it, and the clamping pair comes in at 45° to it.
