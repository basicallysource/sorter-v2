---
layout: default
title: Door module
type: landing
section: hardware
slug: assembly-door-module
kicker: Chute — Door module
lede: The per-layer door mechanism that releases parts into a bin.
permalink: /hardware/assembly/distribution/chute/door-module/
author: spencer
contributors: [barthel]
parts_needed:
  - part: servo-adapter-servo-side
    qty: 1
  - part: servo-adapter-flap-side
    qty: 1
  - part: hsi-m3s
    qty: 4
  - part: scr-m3-6-cs
    qty: 4
---

The door module is made up of:

1. **[MG995 servo]({{ '/hardware/assembly/distribution/chute/mg995-servo/' | relative_url }})** — the servo that drives the door, and how to mount and install it.
2. **[Funnel]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }})** — the funnel that guides parts through the door.
3. **[PCB]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }})** — the board that drives the servo.
4. **[Layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }})** — the connectors that chain layers together.

## Servo adapter

The servo output couples to the door through a **two-piece servo adapter**, servo side and flap side. The two halves share a bolt circle of four holes and bolt together through it.

{% include fastener-legend.html %}

{% include step.html n="1" title="Preparation" %}

Press the heat inserts in while both halves are still loose, before anything is bolted together. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Servo adapter:</strong> 4 × {% include fastener.html size="M3" variant="heat-insert" text="M3 short heat-set insert (ruthex RX-M3Sx4.0)" %} per the BOM. <strong>Check your own printed halves before you press any</strong>, and read the warning below.</p>
  </div>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>This joint is not confirmed against a built machine.</strong> The BOM lists 4 short M3 inserts (ruthex RX-M3Sx4.0) per adapter, but the adapter models published here have no pocket that clearly takes one: the flap side has four 4.0 mm bores through a 5.0 mm wall with a 90° countersink on the back face, and the servo side has four blind 2.8 mm holes, 4.0 mm deep, with solid material behind them. Read as printed, that is a countersunk screw self-tapping straight into plastic, with no insert anywhere, and on that reading an M3 × 6 mm screw only bites about 1 mm. Treat both the insert count and the screw length here as unverified until somebody checks a built adapter.</p>
</div>

{% include step.html n="2" title="Join the two halves" %}

Bolt the flap side to the servo side with 4 {% include fastener.html size="M3" variant="countersunk" length="6" %} screws through the shared bolt circle, heads into the countersinks on the flap side.
