---
layout: default
title: Servo mount
type: how-to
section: hardware
slug: assembly-servo-mount
kicker: MG995 servo — Servo mount
lede: The mount the servo bolts into.
permalink: /hardware/assembly/distribution/chute/mg995-servo/servo-mount/
author: spencer
contributors: [barthel]
---

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>AI-generated first draft.</strong> Written from the machine assembly tree in the <a href="https://parts-calculator.basically.website/assembly?focus=servo-bracket">parts calculator</a>, not from an actual build. No step here has been checked against a machine. Correct it as you build.</p>
</div>

The MG995 sits in a four-part printed bracket, and the whole bracket goes onto the chute core as one unit. Build it on the bench, then bolt it on.

**Parts, per chute:**

| Part | Qty |
|---|---|
| Servo bracket, housing | 1 |
| Servo bracket, lower arm | 1 |
| Servo bracket, side arm | 1 |
| Servo bracket, cover | 1 |
| MG995 servo | 1 |
| M3 × 12 mm countersunk | 4 |
| M3 × 8 mm countersunk | 2 |

{% include fastener-legend.html %}

{% include step.html n="1" title="Press the heat inserts into the housing" %}

The Servo bracket housing takes **6 × M3 heat inserts**. Press them in while the housing is loose. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}).

<div class="img-placeholder">Image coming</div>

{% include step.html n="2" title="Seat the servo in the housing" %}

Drop the MG995 into the housing and fasten it with 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws through the servo's own mounting ears.

Clock the horn before you commit to a position. The MG995 only rotates 180°, and the door has to reach both fully open and fully closed inside that range, see [how to install]({{ '/hardware/assembly/distribution/chute/mg995-servo/how-to-install/' | relative_url }}).

{% include step.html n="3" title="Add the arms and the cover" %}

Fit the lower arm and the side arm to the housing and fasten them with the 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws into the housing's inserts. Clip the cover on last.

{% include step.html n="4" title="Bolt the bracket to the chute core" %}

The finished bracket mounts to the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}) on **two** of the core's M3 inserts, as one unit. The servo output then couples to the door through the two-piece servo adapter (servo side and flap side), which is part of the [door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}).
