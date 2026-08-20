---
layout: default
title: PCB
type: how-to
section: hardware
slug: assembly-pcb
kicker: Chute — PCB
lede: The board that drives the servo.
permalink: /hardware/assembly/distribution/chute/pcb/
author: spencer
contributors: [barthel]
---

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>AI-generated first draft.</strong> Written from the machine assembly tree in the <a href="https://parts-calculator.basically.website/assembly?focus=chute-pcb">parts calculator</a>, not from an actual build. No step here has been checked against a machine. Correct it as you build.</p>
</div>

Each layer carries one **basically Layer Adapter Board**, the in-house board that breaks out the control board's ribbon connectors for that distribution layer and drives the layer's servo. One per layer.

{% include fastener-legend.html %}

{% include step.html n="1" title="Screw the board onto the chute core" %}

The board mounts on **four M3 inserts** in the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}), which are part of the core's 18. Press those inserts in before the chute is assembled.

Seat the board over the four inserts and fasten it with 4 {% include fastener.html size="M3" variant="button" length="6" %} screws. Do not overtighten, the board is standing on printed plastic.

<div class="img-placeholder">Image coming</div>

{% include step.html n="2" title="Connect the ribbon cable" %}

The board takes the ribbon connection that chains this layer to the control board. How the layers chain is covered under [electronics]({{ '/hardware/electronics/' | relative_url }}) and in the [WireViz drawings]({{ '/hardware/electronics/wireviz/' | relative_url }}).
