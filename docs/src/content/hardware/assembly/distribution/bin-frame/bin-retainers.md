---
layout: default
title: Bin retainers
type: how-to
section: hardware
slug: assembly-bin-retainers
kicker: Bin frame — Bin retainers
lede: The pair of rails on each face of a layer that a bin slides into. Same on every bin layer.
permalink: /hardware/assembly/distribution/bin-frame/bin-retainers/
author: barthel
contributors: [zed0, brickcyclealice]
warning: >-
  **Split out of Regular layers and Bottom two layers, which described this
  twice, not yet reviewed by a builder in this form.** The step itself is
  unchanged from those pages. Correct it as you build.
parts_needed:
  - part: bin-retainer-left
    qty: 6
  - part: bin-retainer-right
    qty: 6
  - part: scr-m5-16-shcs
    qty: 24
  - part: tnut-m5-2020
    qty: 24
tools_needed: [Hex key]
---

Every bin layer gets the same twelve retainers: a Bin retainer (left) and a Bin retainer (right) on the front face of each of the six A/G extrusions, so each of the six faces has a pair that a bin slides down between. The quantities above are **for one layer**. [Regular layers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}) and [Bottom two layers]({{ '/hardware/assembly/distribution/bin-frame/bottom-two-layers/' | relative_url }}) both send you here.

**Do this after the layer's External bracket — covers are on.** The retainers run right out to the corners, so leave them off until the corner is finished.

{% include fastener-legend.html %}

{% include step.html n="1" title="Put four T-nuts in each face" %}

Drop 4 {% include fastener.html size="M5" variant="t-nut" text="M5 T-nuts" %} into the outward-facing slot of each A/G extrusion, two per retainer. They do not have to be positioned accurately: slide them along to meet the retainer's holes once it is held in place.

The T-nuts specified for the machine are the roll-in kind, so they go into the slot here, at this step, with the frame already built. See [Fitting T-nuts]({{ '/hardware/helpers/t-nuts/' | relative_url }}) if you bought a different style, because slide-in nuts have to go in much earlier.

{% include step.html n="2" title="Fasten the retainers" %}

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-regular-layers-bin-retainers-installed-w1600-31bf32089e71.png" alt="Bin retainers fastened to the outer faces of the hexagon frame">
  <figcaption><cite>Photo: zed0.</cite></figcaption>
</figure>

On each side of the hexagon, hold both the Bin retainer (left) and the Bin retainer (right) against the front face of A/G (Outer horizontal / Horizontal interface frame). The rib along the back of each one drops into the extrusion's slot and sets the height for you; the hook at the top sits on the top face of the extrusion. Fasten each retainer with 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws into the T-nuts.

Each retainer's bore is 12.8 mm deep, so a shorter M5 reaches the extrusion face with nothing left to bite in the T-nut. Use a socket head rather than a button head here: the flat the head lands on stops 4.1 mm below the hole, which a button head overhangs, and a washer will not sit flat on it at all.
