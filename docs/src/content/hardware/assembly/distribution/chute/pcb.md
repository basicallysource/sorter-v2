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
warning: >-
  **AI-generated first draft.** Written from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=chute-pcb), not from
  an actual build. No step here has been checked against a machine. Correct it as you build.
parts_needed:
  - part: layer-adapter-board-basically
    qty: 1
  - part: hsi-m3
    qty: 4
  - part: scr-m3-6-bhcs
    qty: 4
---

Each layer carries one basically Layer Adapter Board, the in-house board that breaks out the control board's ribbon connectors for that distribution layer and drives the layer's servo. One per layer.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

- The 4 M3 inserts the board sits on are part of the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }})'s 18, not extra ones.
- The board is the only thing on the chute that uses a {% include fastener.html size="M3" variant="button" length="6" %} screw.

{% include step.html n="1" title="Preparation" %}

Press the chute core's inserts before the chute is assembled, the four PCB inserts among them. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

{% include step.html n="2" title="Screw the board onto the chute core" %}

Seat the board over the four inserts and fasten it with 4 {% include fastener.html size="M3" variant="button" length="6" %} screws. Do not overtighten, the board is standing on printed plastic.

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Connect the ribbon cable" %}

The board takes the ribbon connection that chains this layer to the control board. How the layers chain is covered under [electronics]({{ '/hardware/electronics/' | relative_url }}) and in the [WireViz drawings]({{ '/hardware/electronics/wireviz/' | relative_url }}).
