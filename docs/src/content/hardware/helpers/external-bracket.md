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
  - part: scr-m5-16-shcs
    qty: 2
tools_needed: [Hex key]
---

These three printed parts never bolt together into one stand-alone unit anywhere on the machine. A side bracket and cover close off one layer's own corner, clamped directly onto that corner's own vertical extrusion; a bottom-vertical belongs to the layer above and reaches down to that same extrusion, its flange screwing into the side bracket of the layer above it, not the side bracket in its own corner. This page shows those two joints on their own, off the machine, since nowhere else has clean photos of them. For how they actually come together at a real corner, and around the vertical extrusion between them, see [regular layers, step 1]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}#step-1) and [step 3]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}#step-3).

Three printed parts. **You need 6 per layer of the distribution frame, plus one extra set per interface** (side bracket and cover only there, no bottom-vertical leg — see [top interface, step 13]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}#step-13)).

{% include fastener-legend.html %}

- No heat inserts are used on this assembly. Joining is **self-tap**: the {% include fastener.html size="M5" variant="socket-button" length="16" %} screws thread directly into the printed plastic.
- The most-used M5 in the machine, the same screw used on every external bracket, every bin bracket, every interface rib, and every lazy Susan extrusion mount.
- Across the bracket's two real joints, **4** of these screws are used in total: **2** join the bottom-vertical's flange to the side bracket above it, shown in Step 1 below, and **2** clamp the side bracket onto its own corner's vertical extrusion — that clamp joint is covered on whichever page you're installing from, since the extrusion piece and its handling differ by context. The **cover clips on**, it takes no screws.
- Matching parts from the same print run are embossed with a shared set code (e.g. **"b2"**) on both the side bracket and the bottom-vertical part. Keep marked pairs together so brackets don't get mixed across sets.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/parts-laid-out-cropped-full-5f71f37e8388.jpg" alt="Side bracket and bottom-vertical leg, with the four M5 × 16 mm screws they use">
  <figcaption>Side bracket and bottom-vertical, with all four {% include fastener.html size="M5" variant="socket-button" length="16" %} screws the bracket uses across both its joints — two for the flange joint below, two for the extrusion clamp covered elsewhere. The cover is shown in Step 2. <cite>Photo: Christoph, cropped to drop the extrusion offcut this page no longer covers.</cite></figcaption>
</figure>

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-external-bracket-side-bracket-full-6649e3954a49.jpg" alt="Close-up of the side bracket alone, showing the U-shaped extrusion clamp and the two mounting-hole wings">
    <figcaption>The side bracket on its own: the U-shaped opening clamps around the extrusion, and each of the two wings carries a pair of mounting holes. <cite>Photo: Christoph.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-external-bracket-bottom-vertical-flange-full-4b9a511aea49.jpg" alt="Close-up of the bottom-vertical part's top flange, showing the holes used to screw it to the side bracket">
    <figcaption>The bottom-vertical part's top flange: the square socket sleeves over the extrusion, and the holes around it are what the two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws in Step 1 go into. <cite>Photo: Christoph.</cite></figcaption>
  </figure>
</div>

{% include step.html n="1" title="The layer-to-layer joint: bottom-vertical to the side bracket above" %}

A finished layer's own corner already has its side bracket clamped onto the bottom of its own vertical extrusion, and its bottom-vertical sleeved over that same extrusion's exposed top, foot resting near its own collar. Setting the next layer down brings that bottom-vertical's flange up against the **side bracket of the layer above** — not the side bracket in its own corner — and this is the screw joint that actually pins the two layers together.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Drive these tight — self-tapping screws into printed plastic hold best if seated firmly the first time; repeated removal and reinsertion strips the plastic threads.</p>
</div>

Line up the screw holes shown above and drive two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws down through the bottom-vertical's flange into the side bracket above it.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-external-bracket-step1-screwed-underside-full-d3637471f50a.jpg" alt="Bottom-vertical leg screwed into the underside of the side bracket, seen from above through the square extrusion socket">
  <figcaption>Two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws join the bottom-vertical's flange to the side bracket above it. Viewed from above, looking down through the square socket the extrusion passes through. <cite>Photo: Christoph.</cite></figcaption>
</figure>

{% include step.html n="2" title="The cover: clip-fit, no screws" %}

Clip the cover onto the side bracket to close it off. Unlike the flange joint above, this one happens within a single corner: the cover clips onto its own corner's side bracket before that corner's vertical extrusion goes in, since it's tricky to fit afterward (see [regular layers, step 1]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}#step-1)). The cover takes no screws, it's a snap fit.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-external-bracket-step4-cover-unattached-full-9b93d76f9459.jpg" alt="The unattached cover sitting next to the assembled bracket, at the face where it clips on">
    <figcaption>The cover (left), not yet attached, next to the face of the assembly it clips onto. The extrusion in this photo is shown for demo only, not part of this step. <cite>Photo: Christoph.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-external-bracket-step4-cover-clipped-on-full-1fea5b9a357c.jpg" alt="Finished bracket with the cover clipped into place">
    <figcaption>Cover clipped into place. It sits flush against the side bracket, which is why the seam is subtle in photos. The extrusion in this photo is shown for demo only, not part of this step. <cite>Photo: Christoph.</cite></figcaption>
  </figure>
</div>
