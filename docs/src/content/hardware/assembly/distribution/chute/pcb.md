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
last_verified: 2026-09-07
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

{% include step.html n="3" title="Connect the ribbon cable and the servo" %}

Do both now, while the chute is still on the bench. Once it is in the frame these three connectors are hard to reach.

The board has two identical 16-pin sockets. **`J3` is the ribbon coming in and `J4` is the ribbon going on down to the next layer.** Nothing but the designator printed on the board tells them apart.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>A board fed on <code>J4</code> gets no signal at all, and every layer below it moves the wrong flap.</p>
</div>

This layer's servo plugs into `J5`, the 3-pin header beside them: pin 1 signal, pin 2 servo power, pin 3 ground.

The ribbon that comes down from the control board to the top of the stack is [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 5.

Full harness routing is covered in the [harness drawings]({{ '/hardware/parts/harness-order/' | relative_url }}).
