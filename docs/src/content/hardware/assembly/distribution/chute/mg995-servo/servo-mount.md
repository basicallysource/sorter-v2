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
warning: >-
  **AI-generated first draft.** Written from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=servo-bracket), not
  from an actual build. No step here has been checked against a machine. Correct it as you
  build.
parts_needed:
  - part: servo-bracket-housing
    qty: 1
  - part: servo-bracket-lower-arm
    qty: 1
  - part: servo-bracket-side-arm
    qty: 1
  - part: servo-bracket-cover
    qty: 1
  - part: servo-mg995
    qty: 1
  - part: hsi-m3
    qty: 6
  - part: scr-m3-12-cs
    qty: 4
  - part: scr-m3-8-cs
    qty: 2
---

The MG995 sits in a four-part printed bracket, and the whole bracket goes onto the chute core as one unit. Build it on the bench, then bolt it on.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

- **One per chute**, so one per layer.
- Everything on this page threads into the housing's own inserts or the servo's mounting ears. The two screws that hold the finished bracket to the chute core come out of the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }})'s set, not this one.
- The cover clips on and takes no screws.

{% include step.html n="1" title="Preparation" %}

Press the inserts into the housing while it is still bare. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Servo bracket (housing):</strong> 6 × M3</p>
  </div>
  <div class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </div>
</div>

{% include step.html n="2" title="Seat the servo in the housing" %}

Drop the MG995 into the housing and fasten it with 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws through the servo's own mounting ears.

Clock the horn before you commit to a position. The MG995 only rotates 180°, and the door has to reach both fully open and fully closed inside that range, see [how to install]({{ '/hardware/assembly/distribution/chute/mg995-servo/how-to-install/' | relative_url }}).

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Add the arms and the cover" %}

Fit the lower arm and the side arm to the housing and fasten them with the 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws into the housing's inserts. Clip the cover on last.

{% include step.html n="4" title="Bolt the bracket to the chute core" %}

The finished bracket mounts to the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}) on **two** of the core's M3 inserts, as one unit. The servo output then couples to the door through the two-piece servo adapter (servo side and flap side), which is part of the [door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}).
