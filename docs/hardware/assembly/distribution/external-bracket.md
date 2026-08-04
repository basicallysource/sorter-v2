---
layout: default
title: External bracket
type: how-to
section: hardware
slug: assembly-external-bracket
kicker: Distribution — External bracket
lede: The bracket that mounts a distribution-frame vertical extrusion to the frame and gives it a mounting point.
permalink: /hardware/assembly/distribution/external-bracket/
author: christoph
last_verified: 2026-08-03
parts_needed:
  - part: ext-bracket-left
  - part: ext-bracket-bottom-vertical
  - part: ext-bracket-cover
  - part: scr-m5-16-shcs
    qty: 4
---

Three printed parts that bolt together into one external bracket. **6 per distribution frame (per layer), plus one set per interface.**

| Part | Qty per bracket | Qty per machine (6 brackets/layer) | Weight | STL |
|---|---|---|---|---|
| External bracket — side | 1 | 6 | 48.5 g | [Download STL](https://sorter-v2-parts.nyc3.cdn.digitaloceanspaces.com/stl/da4b3abd3db72070484178ef5aa1d0906397c6a310bdf0e22f724940bd62dba2.stl) |
| External bracket — bottom vertical | 1 | 6 | 50.6 g | [Download STL](https://sorter-v2-parts.nyc3.cdn.digitaloceanspaces.com/stl/313397afb08fc1943f045905b96131f73f1dc70c05d59fd2583c77da38318c36.stl) |
| External bracket — cover | 1 | 6 | 12.4 g | [Download STL](https://sorter-v2-parts.nyc3.cdn.digitaloceanspaces.com/stl/f99e33cea11551b8222feac91c28015488ff2c239e632f5098322e7ea10fc96c.stl) |

**Other parts**

| Part | Qty per bracket | Notes |
|---|---|---|
| C-Layer vertical support (extrusion) | 1 | The vertical aluminum extrusion the bracket clamps onto. |

- No heat inserts are used on this assembly. Joining is **self-tap**: the M5 × 16 mm screws thread directly into the printed plastic.
- The most-used M5 in the machine, the same screw used on every external bracket, every bin bracket, every interface rib, and every lazy Susan extrusion mount.
- Of the four M5 × 16 mm screws: **2** join the bottom-vertical part to the side bracket, and **2** clamp the side bracket against the C-Layer vertical support to hold it in place. The **cover clips on**, it takes no screws.
- Matching parts from the same print run are embossed with a shared set code (e.g. **"b2"**) on both the side bracket and the bottom-vertical part, keep marked pairs together so brackets don't get mixed across sets.

<figure>
  <img class="doc-figure" src="https://img.basically.website/web/assembly/external-bracket/parts-laid-out.jpg" alt="Side bracket, bottom-vertical leg, cover, an extrusion offcut, and the four M5 × 16 mm screws laid out before assembly">
  <figcaption>Parts for one bracket, laid out before assembly: side bracket, bottom-vertical leg, C-Layer vertical support, and the four M5 × 16 mm screws. The cover is fitted last, in Step 4.</figcaption>
</figure>

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/external-bracket/side-bracket.jpg" alt="Close-up of the side bracket alone, showing the U-shaped extrusion clamp and the two mounting-hole wings">
    <figcaption>The side bracket on its own: the U-shaped opening clamps around the extrusion, and each of the two wings carries a pair of mounting holes.</figcaption>
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/external-bracket/bottom-vertical-flange.jpg" alt="Close-up of the bottom-vertical part's top flange, showing the holes used to screw it to the side bracket">
    <figcaption>The bottom-vertical part's top flange, before assembly: the square socket takes the extrusion, and the holes around it are what the two M5 × 16 mm screws in Step 1 go into.</figcaption>
  </figure>
</div>

{% include step.html n="1" title="Mount the bottom-vertical leg to the side bracket" %}

Set the bottom-vertical leg's flanged top into the U-shaped opening of the side bracket, tube pointing down. Line up the screw holes shown above and drive two M5 × 16 mm socket head screws down through the flange into the side bracket.

<figure>
  <img class="doc-figure" src="https://img.basically.website/web/assembly/external-bracket/step1-screwed-underside.jpg" alt="Bottom-vertical leg screwed into the underside of the side bracket, seen from above through the square extrusion socket">
  <figcaption>Two M5 × 16 mm screws join the bottom-vertical leg to the side bracket. Viewed from above, looking down through the square socket that will receive the extrusion.</figcaption>
</figure>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Drive these tight. As self-tapping screws into printed plastic, they hold best if seated firmly the first time, repeated removal and reinsertion strips the plastic threads.</p>
</div>

{% include step.html n="2" title="Insert the C-Layer vertical support" %}

Slide the C-Layer vertical support (the vertical aluminum extrusion) down through the side bracket's U-shaped clamp and into the square socket in the bottom-vertical leg below. The socket is sized to the extrusion's profile, so it can only seat in the correct orientation.

<figure>
  <img class="doc-figure" src="https://img.basically.website/web/assembly/external-bracket/step2-extrusion-inserted.jpg" alt="C-Layer vertical support extrusion inserted down through the side bracket and into the square socket of the bottom-vertical leg">
  <figcaption>C-Layer vertical support seated through the side bracket and into the bottom-vertical leg's socket. It isn't held in place yet, that's Step 3.</figcaption>
</figure>

{% include step.html n="3" title="Screw the bracket down onto the extrusion" %}

Two more M5 × 16 mm screws clamp the side bracket against the C-Layer vertical support to hold it firmly in place.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/external-bracket/step3-screw-hole-empty.jpg" alt="Retention screw hole empty, before the screw is driven in">
    <figcaption>Before: retention-screw hole empty.</figcaption>
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/external-bracket/step3-screw-driven-in.jpg" alt="Retention screw driven in, seated flush in the hex socket">
    <figcaption>After: M5 × 16 mm screw driven in, clamping the bracket against the extrusion. Repeat for the second hole on the opposite face.</figcaption>
  </figure>
</div>

{% include step.html n="4" title="Clip on the cover" %}

Clip the cover onto the side bracket to close it off. The cover takes no screws, it's a snap fit.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/external-bracket/step4-cover-unattached.jpg" alt="The unattached cover sitting next to the assembled bracket, at the face where it clips on">
    <figcaption>The cover (left), not yet attached, next to the face of the assembly it clips onto.</figcaption>
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/external-bracket/step4-cover-clipped-on.jpg" alt="Finished bracket with the cover clipped into place">
    <figcaption>Cover clipped into place. It sits flush against the side bracket, which is why the seam is subtle in photos.</figcaption>
  </figure>
</div>
