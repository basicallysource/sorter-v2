---
layout: default
title: Assembling External bracket
type: how-to
section: hardware
slug: helper-external-bracket
kicker: Helpers — Assembling External bracket
lede: The bracket that mounts a distribution-frame vertical extrusion to the frame and gives it a mounting point.
permalink: /hardware/helpers/external-bracket/
author: christoph
contributors: [barthel]
last_verified: 2026-08-03
parts_needed:
  - part: ext-bracket-left
    qty: 1
  - part: ext-bracket-bottom-vertical
    qty: 1
  - part: ext-bracket-cover
    qty: 1
  - part: ext-2020-c
    qty: 1
  - part: scr-m5-16-shcs
    qty: 4
---

Three printed parts that bolt together into one external bracket. **6 per distribution frame (per layer), plus one set per interface** (side and cover only there, no bottom vertical — see [top interface, step 13]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}#step-13)).

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

- No heat inserts are used on this assembly. Joining is **self-tap**: the {% include fastener.html size="M5" variant="socket-button" length="16" %} screws thread directly into the printed plastic.
- The most-used M5 in the machine, the same screw used on every external bracket, every bin bracket, every interface rib, and every lazy Susan extrusion mount.
- Of the four {% include fastener.html size="M5" variant="socket-button" length="16" %} screws: **2** join the bottom-vertical part to the side bracket, and **2** clamp the side bracket against the C-Layer vertical support to hold it in place. The **cover clips on**, it takes no screws.
- Matching parts from the same print run are embossed with a shared set code (e.g. **"b2"**) on both the side bracket and the bottom-vertical part, keep marked pairs together so brackets don't get mixed across sets.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-external-bracket-parts-laid-out-full-0a59300a73b4.jpg" alt="Side bracket, bottom-vertical leg, cover, an extrusion offcut, and the four M5 × 16 mm screws laid out before assembly">
  <figcaption>Parts for one bracket, laid out before assembly: side bracket, bottom-vertical leg, C-Layer vertical support, and the four {% include fastener.html size="M5" variant="socket-button" length="16" %} screws. The cover is fitted last, in Step 4. Photo: Christoph.</figcaption>
</figure>

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-external-bracket-side-bracket-full-6649e3954a49.jpg" alt="Close-up of the side bracket alone, showing the U-shaped extrusion clamp and the two mounting-hole wings">
    <figcaption>The side bracket on its own: the U-shaped opening clamps around the extrusion, and each of the two wings carries a pair of mounting holes. Photo: Christoph.</figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-external-bracket-bottom-vertical-flange-full-4b9a511aea49.jpg" alt="Close-up of the bottom-vertical part's top flange, showing the holes used to screw it to the side bracket">
    <figcaption>The bottom-vertical part's top flange, before assembly: the square socket takes the extrusion, and the holes around it are what the two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws in Step 1 go into. Photo: Christoph.</figcaption>
  </figure>
</div>

{% include step.html n="1" title="Mount the bottom-vertical leg to the side bracket" %}

Set the bottom-vertical leg's flanged top into the U-shaped opening of the side bracket, tube pointing down. Line up the screw holes shown above and drive two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws down through the flange into the side bracket.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-external-bracket-step1-screwed-underside-full-d3637471f50a.jpg" alt="Bottom-vertical leg screwed into the underside of the side bracket, seen from above through the square extrusion socket">
  <figcaption>Two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws join the bottom-vertical leg to the side bracket. Viewed from above, looking down through the square socket that will receive the extrusion. Photo: Christoph.</figcaption>
</figure>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Drive these tight. As self-tapping screws into printed plastic, they hold best if seated firmly the first time, repeated removal and reinsertion strips the plastic threads.</p>
</div>

{% include step.html n="2" title="Insert the C-Layer vertical support" %}

Slide the C-Layer vertical support (the vertical aluminum extrusion) down through the side bracket's U-shaped clamp and into the square socket in the bottom-vertical leg below. The socket is sized to the extrusion's profile, so it can only seat in the correct orientation.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-external-bracket-step2-extrusion-inserted-full-c56df607b17c.jpg" alt="C-Layer vertical support extrusion inserted down through the side bracket and into the square socket of the bottom-vertical leg">
    <figcaption>C-Layer vertical support seated through the side bracket and into the bottom-vertical leg's socket. It isn't held in place yet, that's Step 3. Photo: Christoph.</figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/final4-hires-full-c713a740a66b.png" alt="Vertical cross-section through the side bracket and cover, with the extrusion running through the bore as a hatched strip and a dashed line marking the clamp screw">
    <figcaption>The collar in section, cut through the centre of the bore. Tan is the side bracket and cover; the hatched strip is the extrusion. The dashed line marks the clamp screw from Step 3. Drawn from the part geometry, not from a build.</figcaption>
  </figure>
</div>

{% include step.html n="3" title="Screw the bracket down onto the extrusion" %}

Two more {% include fastener.html size="M5" variant="socket-button" length="16" %} screws clamp the side bracket against the C-Layer vertical support to hold it firmly in place.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-external-bracket-step3-screw-hole-empty-full-1086433be655.jpg" alt="Retention screw hole empty, before the screw is driven in">
    <figcaption>Before: retention-screw hole empty. Photo: Christoph.</figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-external-bracket-step3-screw-driven-in-full-259bbc4b6fdb.jpg" alt="Retention screw driven in, seated flush in the hex socket">
    <figcaption>After: {% include fastener.html size="M5" variant="socket-button" length="16" %} screw driven in, clamping the bracket against the extrusion. Repeat for the second hole on the opposite face. Photo: Christoph.</figcaption>
  </figure>
</div>

{% include step.html n="4" title="Clip on the cover" %}

Clip the cover onto the side bracket to close it off. The cover takes no screws, it's a snap fit.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-external-bracket-step4-cover-unattached-full-9b93d76f9459.jpg" alt="The unattached cover sitting next to the assembled bracket, at the face where it clips on">
    <figcaption>The cover (left), not yet attached, next to the face of the assembly it clips onto. Photo: Christoph.</figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-external-bracket-step4-cover-clipped-on-full-1fea5b9a357c.jpg" alt="Finished bracket with the cover clipped into place">
    <figcaption>Cover clipped into place. It sits flush against the side bracket, which is why the seam is subtle in photos. Photo: Christoph.</figcaption>
  </figure>
</div>

This is the bracket as a stand-alone unit. For how it's actually installed on the frame — and the one difference at the layer-to-layer joint — see [regular layers, step 3]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}#step-3) and [step 5]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}#step-5).
