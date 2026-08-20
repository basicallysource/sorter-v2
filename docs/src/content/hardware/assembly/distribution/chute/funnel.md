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
    qty: 1
  - part: funnel-third
    qty: 1
  - part: funnel-bracket-left
    qty: 1
  - part: funnel-bracket-right
    qty: 1
  - part: scr-m3-12-cs
    qty: 6
  - part: scr-m3-8-cs
    qty: 8
---

The funnel catches what the door releases and guides it into the bin below. It hangs off two printed brackets that are part of the chute.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

- **One funnel per layer**, in one of two sizes. Print the size that matches that layer's bins.
- The 6 {% include fastener.html size="M3" variant="countersunk" length="12" %} and 8 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws in the list are the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }})'s whole set, shared between the funnel brackets, the door module and the layer connectors. Only some of them land here.
- The brackets screw into the chute core's M3 heat inserts, so there is nothing to tap.

{% include step.html n="1" title="Pick the funnel size for the layer" %}

The size is chosen per layer rather than once for the whole machine, and it sets that layer's bins with it:

- **Funnel (half size):** 12 bins on that layer, six Bin (half, left) and six Bin (half, right).
- **Funnel (third size):** 18 bins on that layer, six each of Bin (third, left), Bin (third, center) and Bin (third, right-back).

Decide before printing, since it changes both the funnel and the bin set. The [parts calculator](https://parts-calculator.basically.website/) takes a size per layer and totals the print for whatever mix you pick.

{% include step.html n="2" title="Fit the funnel brackets to the chute core" %}

Every chute carries a Funnel bracket (left) and a Funnel bracket (right), one of each. They screw into the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }})'s M3 heat inserts, using screws from the chute's set.

Which of those go into the funnel brackets is not recorded yet: <span class="fastener-todo">fastener not recorded</span>.

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Hang the funnel" %}

How the funnel itself attaches to the brackets is not recorded yet.
