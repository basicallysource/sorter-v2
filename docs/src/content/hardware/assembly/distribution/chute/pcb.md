---
layout: default
title: Layer adapter board
type: how-to
section: hardware
slug: assembly-pcb
kicker: Chute — Layer adapter board
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
  - part: scr-m3-6-bhcs
    qty: 4
---

Each layer carries one basically Layer Adapter Board, the in-house board that breaks out the control board's ribbon connectors for that distribution layer and drives the layer's servo. One per layer.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

- The 4 M3 inserts the board sits on are part of the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }})'s 18, not extra ones.
- The board is the only thing on the chute that uses a {% include fastener.html size="M3" variant="socket-button" length="6" %} screw.

{% include step.html n="1" title="Preparation" %}

Nothing to press in here. The four inserts the board sits on are pressed into the chute core along with the rest of its 18, before the chute is assembled. See [Chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}) for where they are, and [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

{% include step.html n="2" title="Screw the board onto the chute core" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Static caution: this is a bare board. Touch a grounded metal surface before handling it, and handle it by its edges, avoiding the connectors and components.</p>
</div>

Seat it over the four inserts and fasten it with 4 {% include fastener.html size="M3" variant="socket-button" length="6" %} screws. Do not overtighten, the board is standing on printed plastic, not a metal standoff.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/chute-core-inserts-v3-rear-full-ad4c2cc7869c.png" alt="Close render of the rear end of the chute core with the four heat inserts the layer adapter board screws into circled in red">
  <figcaption>The four inserts the board sits on, all on the panel at the top end of the chute core's rear face. <cite>Render: Balloon.</cite></figcaption>
</figure>

<div class="img-placeholder">Photo of the layer adapter board seated on its four inserts and screwed to the chute core.</div>

{% include step.html n="3" title="Connect the ribbon cable" %}

Plug the ribbon cable into the board's connector before you install the chute into the frame if the harness is easier to reach on the bench beforehand. Full harness routing is covered under [electronics]({{ '/hardware/electronics/' | relative_url }}) and in the [WireViz drawings]({{ '/hardware/electronics/wireviz/' | relative_url }}).
