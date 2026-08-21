---
layout: default
title: Arranging C-Channels
type: how-to
section: hardware
slug: assembly-arranging-c-channels
kicker: Feeder — Arranging C-Channels
lede: How the four C-channels stand, at what heights, and what passes parts between them.
permalink: /hardware/assembly/feeder/arranging-c-channels/
author: barthel
warning: >-
  **Skeleton page.** Assembled from the parts registry in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=feeder) and the
  extrusion list on the bill of materials. No height, angle or fastener here has been checked
  against a machine, and the two starred questions below are the ones that make the feeder work.
  Fill it in as you build.
parts_needed:
  - part: leg
    qty: 9
  - part: foot
    qty: 9
  - part: leg-extension
    qty: 9
---

Four [C-channels]({{ '/hardware/assembly/feeder/c-channel/' | relative_url }}) are built the same way and then stood at different heights, so a part cascades from one to the next under gravity and arrives at the [interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}) singulated.

{% include fastener-legend.html %}

## The order parts travel

1. **C1**, the bulk channel, under the [bulk input]({{ '/hardware/assembly/feeder/bulk-input/' | relative_url }}). Highest.
2. **C2**, with a [light post]({{ '/hardware/assembly/feeder/light-post/' | relative_url }}) and an [overhead camera mount]({{ '/hardware/assembly/feeder/camera-mount/' | relative_url }}).
3. **C3**, the same again, and the last metering stage.
4. **The classification channel**, inside the [classification chamber]({{ '/hardware/assembly/feeder/classification-chamber/' | relative_url }}), which images the part before it drops into the chute.

[Output guides]({{ '/hardware/assembly/feeder/output-guides/' | relative_url }}) bridge the handovers between them.

## The stand

Each channel stands on its own printed legs: **3 legs, 3 feet and 3 leg extensions per channel**, 9 of each across the three feeder channels. The Leg is the 135 mm print; the extension raises it further, and the foot is what meets the bench.

- How the leg, extension and foot stack, and what fastens them to each other, is not recorded: <span class="fastener-todo">fastener not recorded</span>.
- How a leg attaches to the C-channel's stator or NEMA bracket is not recorded: <span class="fastener-todo">fastener not recorded</span>.
- Whether the classification channel stands on legs of its own, or is carried by the chamber and the interface, is not recorded either. The catalog gives 9 of each for the feeder and none for the classification channel, which suggests the latter.

## The framing

The bill of materials gives the feeder's 2020 cut list. No step uses it yet, so what each piece bolts to is an open question.

- **3 at 270 mm**, bulk bucket supports.
- **3 at 190 mm**, mid C-channel supports.
- **3 at 110 mm**, lower C-channel supports.
- **Camera support**, either 1 at 300 mm fixed, or 1 at 350 mm plus 1 at 200 mm for the adjustable version. How that relates to the rod-and-arm [camera mount]({{ '/hardware/assembly/feeder/camera-mount/' | relative_url }}), which hangs off the channels rather than off extrusion, is unclear and worth resolving on this page.

{% include step.html n="1" title="Stand each channel" %}

Fit legs, extensions and feet to each of the three feeder channels. Details unrecorded, see above.

<div class="img-placeholder">Image coming</div>

{% include step.html n="2" title="Set the heights and the spacing" %}

**★ The numbers this page most needs.** For each handover: the drop from one rotor to the next, the horizontal overlap between the channels, and how far around the circle the handover happens. Nothing about any of it is written down anywhere today.

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Fit the output guides" %}

See [output guides]({{ '/hardware/assembly/feeder/output-guides/' | relative_url }}).

{% include step.html n="4" title="Add the bulk input, light posts and camera arms" %}

[Bulk input]({{ '/hardware/assembly/feeder/bulk-input/' | relative_url }}) on C1, [light post]({{ '/hardware/assembly/feeder/light-post/' | relative_url }}) and [camera mount]({{ '/hardware/assembly/feeder/camera-mount/' | relative_url }}) on C2 and C3.

{% include step.html n="5" title="Hand over to the classification channel" %}

**★ The other open question.** How the classification channel sits relative to C3 and to the interface below it, and what carries it. Record it here.

{% include step.html n="6" title="Turn it all by hand" %}

Run parts through the whole cascade by hand, one channel at a time, before wiring the steppers. Anything that needs a nudge here will jam under power.
