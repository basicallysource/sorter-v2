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
---

The door module is made up of:

1. **[MG995 servo]({{ '/hardware/assembly/distribution/chute/mg995-servo/' | relative_url }})** — the servo that drives the door, and how to mount and install it.
2. **[Funnel]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }})** — the funnel that guides parts through the door.
3. **[PCB]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }})** — the board that drives the servo.
4. **[Layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }})** — the connectors that chain layers together.

## Servo adapter

The servo output couples to the door through a **two-piece servo adapter**, servo side and flap side, listed above. The two halves bolt together with 4 countersunk M3 screws on a bolt circle they share.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>Do not press heat inserts into the adapter without checking your own parts first.</strong> The BOM lists 4 short M3 inserts (ruthex RX-M3Sx4.0) per adapter, but the adapter models published here do not have a pocket for one: the flap side has four 4.0 mm bores through a 5.0 mm wall with a 90° countersink on the back face, and the servo side has four blind 2.8 mm holes, 4.0 mm deep, with solid material behind them. That is a self-tapping joint, screw straight into plastic. Until somebody confirms it against a built adapter, treat the insert count in the parts calculator as unverified.</p>
</div>
