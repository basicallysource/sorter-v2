---
layout: default
title: Funnel
type: how-to
section: hardware
slug: assembly-funnel
kicker: Chute — Funnel
lede: The funnel that guides parts through the door.
permalink: /hardware/assembly/distribution/chute/funnel/
author: spencer
contributors: [barthel]
warning: >-
  **AI-generated first draft.** Written from the machine assembly tree and parts registry in
  the [parts calculator](https://parts-calculator.basically.website/assembly?focus=chute), not
  from an actual build. No step here has been checked against a machine. Correct it as you
  build.
parts_needed:
  - part: funnel-half
  - part: funnel-third
  - part: funnel-bracket-left
    qty: 1
  - part: funnel-bracket-right
    qty: 1
---

The funnel catches what the door releases and guides it into the bin below. It hangs off two printed brackets that are part of the chute.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

- **One funnel per layer**, in one of two sizes. Print the size that matches that layer's bins.
- The brackets screw into the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }})'s M3 heat inserts, so there is nothing to tap.
- The 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} they take come out of the core's set of 6 and are not extra, so they are on that page's parts list rather than this one.

{% include step.html n="1" title="Pick the funnel size for the layer" %}

The size is chosen per layer rather than once for the whole machine, and it sets that layer's bins with it:

- **Funnel (half size):** 12 bins on that layer, six Bin (half, left) and six Bin (half, right).
- **Funnel (third size):** 18 bins on that layer, six each of Bin (third, left), Bin (third, center) and Bin (third, right-back).

Decide before printing: the funnel and its bin set are a matched pair. A half-size funnel needs the six-and-six half bins, a third-size funnel needs the three-way third bins, and picking one without the other leaves you short on prints or with bins that don't fit under that funnel. The [parts calculator](https://parts-calculator.basically.website/) takes a size per layer and totals the print for whatever mix you pick.

{% include step.html n="2" title="Fit the funnel brackets to the chute core" %}

Every chute carries a Funnel bracket (left) and a Funnel bracket (right), one of each. They screw into the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }})'s M3 heat inserts, using screws from the chute's set.

Each bracket takes 2 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws, 4 for the pair. Why 12 mm and not 8 is on the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}) page, along with the rest of the split.

<div class="img-placeholder">Photo of both funnel brackets fitted to the chute core.</div>

{% include step.html n="3" title="Hang the funnel" %}

The funnel's connection to the brackets isn't documented yet. There's no confirmed fastener or clip method. If you get this far, please share how yours attaches so this step can be filled in.
