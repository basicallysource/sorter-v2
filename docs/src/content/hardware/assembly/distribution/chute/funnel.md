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
---

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>AI-generated first draft.</strong> Written from the machine assembly tree and parts registry in the <a href="https://parts-calculator.basically.website/assembly?focus=chute">parts calculator</a>, not from an actual build. No step here has been checked against a machine. Correct it as you build.</p>
</div>

The funnel catches what the door releases and guides it into the bin below. It hangs off two printed brackets that are part of the chute.

{% include step.html n="1" title="Pick the funnel size for the layer" %}

**One funnel per layer**, and the size is chosen per layer rather than once for the whole machine. The choice also sets that layer's bins:

| Funnel | Bins on that layer |
|---|---|
| Funnel (half size) | 12, six Bin (half, left) and six Bin (half, right) |
| Funnel (third size) | 18, six each of Bin (third, left), (center) and (right-back) |

Decide before printing, since it changes both the funnel and the bin set. The [parts calculator](https://parts-calculator.basically.website/) takes a size per layer and totals the print for whatever mix you pick.

{% include step.html n="2" title="Fit the funnel brackets to the chute core" %}

Every chute carries a **Funnel bracket (left)** and a **Funnel bracket (right)**, one of each. They screw into the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }})'s M3 heat inserts, using screws from the chute's set of 6 {% include fastener.html size="M3" variant="countersunk" length="12" %} and 8 {% include fastener.html size="M3" variant="countersunk" length="8" %}.

Which of those go into the funnel brackets is not recorded yet: <span class="fastener-todo">fastener not recorded</span>.

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Hang the funnel" %}

How the funnel itself attaches to the brackets is not recorded yet.
