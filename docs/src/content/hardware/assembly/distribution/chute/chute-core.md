---
layout: default
title: Chute core
type: how-to
section: hardware
slug: assembly-chute-core
kicker: Chute — Chute core
lede: The chute assembly. Build one per layer.
permalink: /hardware/assembly/distribution/chute/chute-core/
author: spencer
contributors: [barthel]
---

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>AI-generated first draft.</strong> Written from the machine assembly tree in the <a href="https://parts-calculator.basically.website/assembly?focus=chute">parts calculator</a>, not from an actual build. No step here has been checked against a machine. Correct it as you build.</p>
</div>

The chute is what steers a part into the right bin. Build one per layer, plus two for the [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}).

One chute is the chute core plus four things that bolt onto it:

| Sub-assembly | Qty | Covered on |
|---|---|---|
| Chute core | 1 | this page |
| Door module | 1 | [Door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}) |
| Funnel bracket (left) and (right) | 1 each | [Funnel]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }}) |
| Layer connector A and B | 1 each | [Layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}) |
| Layer adapter board | 1 | [PCB]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}) |

{% include fastener-legend.html %}

{% include step.html n="1" title="Press the heat inserts into the chute core" %}

The chute core takes **18 × M3 heat inserts**, and every screw that lands on the chute core threads into one of them. Press them all in while the core is still bare. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

The 18 split up as: 2 for the servo bracket arms, 4 for the layer adapter board, and the rest for the funnel brackets, the bearing assembly and the layer connectors.

<div class="img-placeholder">Image coming</div>

{% include step.html n="2" title="Fit the funnel brackets" %}

Fit the Funnel bracket (left) and the Funnel bracket (right) to the chute core. Together with the door module and the layer connectors these use the chute's 6 {% include fastener.html size="M3" variant="countersunk" length="12" %} and 8 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws, all into the core's inserts.

Which screw goes in which hole is not recorded yet: <span class="fastener-todo">fastener not recorded</span>.

{% include step.html n="3" title="Fit the door module" %}

Build the [door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}) as a unit (door, bearing assembly, servo adapter, servo in its bracket) and bolt it to the chute core. The servo bracket lands on **two** of the core's M3 inserts.

{% include step.html n="4" title="Fit the layer connectors and the PCB" %}

Attach Layer connector A and Layer connector B, then the [layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}) on its four PCB inserts.

The chute is now complete. Repeat for every layer.
