---
layout: default
title: Bottom two layers
type: how-to
section: hardware
slug: assembly-bottom-two-layers
kicker: Bin frame — Bottom two layers
lede: The paired base layers. Built together on the foot extensions the casters mount to.
permalink: /hardware/assembly/distribution/bin-frame/bottom-two-layers/
author: spencer
contributors: [brickcyclealice, christoph]
warning: >-
  **First draft, not built from.** Written from the framing cut list, the parts
  catalog and photos of finished machines in the Discord, not from an actual
  build. The fastener counts are two regular layers' worth with the substitutions
  below applied; nobody has checked them against a machine. Correct it as you build.
parts_needed:
  - part: ext-bracket-left
    qty: 12
  - part: ext-bracket-cover
    qty: 6
  - part: ext-bracket-bottom-vertical
    qty: 6
  - part: ext-bracket-foot-cover
    qty: 6
  - part: frame-90deg-bracket
    qty: 24
  - part: frame-crossbeam
    qty: 12
  - part: bin-retainer-left
    qty: 12
  - part: bin-retainer-right
    qty: 12
  - part: ext-2020-ag
    qty: 12
  - part: ext-2020-bh
    qty: 12
  - part: ext-2020-d
    qty: 6
  - part: foot-connector-2020-m6
    qty: 6
  - part: caster-wheel-m6
    qty: 6
  - part: scr-m5-16-shcs
    qty: 72
  - part: scr-m5-20-shcs
    qty: 24
  - part: scr-m5-12-shcs
    qty: 24
  - part: tnut-m5-2020
    qty: 72
---

The bottom two layers are two ordinary bin layers built at the same time, because the vertical extrusion between them is one continuous piece per corner instead of one per layer. That piece is the machine's leg: the caster screws into the bottom of it, so running it up through the bottom layer and into the second gives the wheel something much stiffer to push against than a single layer's worth of extrusion would.

<figure>
  <img class="doc-figure" src="https://img.basically.website/web/assembly/bottom-two-layers/frame-on-casters.e335e00b93578e94.jpg" alt="The bottom of a built machine: two bin-frame layers on six swivel casters, with the extrusion legs running up past the bottom frame into the second">
  <figcaption>The bottom two layers standing on their casters, before the rest of the tower goes on. Photo courtesy of Christoph in the basically Discord.</figcaption>
</figure>

Everything else about these two layers is the same as any other. Build each one with the [regular layers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}) guide and come back here for the parts that differ, which are only the verticals, the corners at floor level, and the feet.

**Build the [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}) before you start.** It is step 1 of the bin frame and it mounts to this frame with three Lazy Susan extrusion mounts, each on an {% include fastener.html size="M5" variant="socket-button" length="16" %} screw into a {% include fastener.html size="M5" variant="t-nut" text="T-nut" %}. Getting T-nuts into an extrusion that already has both layers built around it is the kind of job you only do once.

{% include fastener-legend.html %}

{% include step.html n="1" title="Preparation" %}

No heat inserts on this assembly. Every printed part here takes a self-tapping {% include fastener.html size="M5" variant="socket-button" length="16" %} screw straight into the plastic, the same as the [external bracket]({{ '/hardware/assembly/distribution/external-bracket/' | relative_url }}).

Cut the extrusion first. These two layers use **6 × piece D (Foot extension), 231 mm**, and **no piece C at all** — D stands in for the C that each of these two layers would otherwise have. The [framing cut list](https://parts-calculator.basically.website/framing) has every length; at 1 or 2 layers, C is genuinely absent from that list rather than missing.

<div class="callout">
  <p>D is 1.5 × a single layer's vertical support, not 2 ×. It runs from the caster at the bottom, through the bottom layer's corner, up to the second layer's frame, so the bottom layer sits about half a layer's height off the floor. Spencer confirmed this is what the Brickworld machines were built to.</p>
</div>

{% include step.html n="2" title="Build two layer frames" %}

Work through [regular layers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}) steps 1 and 2 twice, once per layer: the hexagon of six A/G extrusions in six External bracket — sides, then the six B/H spokes on their Frame 90° brackets with a Frame crossbeam each side.

**Stop before that guide's step 3 (Install the verticals).** The verticals are the part that differs here, and they are step 3 below.

If you are using slide-in T-nuts, put them in as that guide says. The ends of the extrusion are no more accessible on these two layers than on any other.

{% include step.html n="3" title="Run the foot extensions through both layers" %}

<figure>
  <img class="doc-figure" src="https://img.basically.website/web/assembly/bottom-two-layers/c-and-d-extrusion.5346ddfabd8d9e45.jpg" alt="The bottom corner of a built machine, with the C layer vertical support marked between the second and third frames and the longer D foot extension marked running from the caster up past the bottom frame to the second">
  <figcaption>C between the layers above; D from the caster, past the bottom layer's corner, to the second layer. Photo courtesy of Christoph in the basically Discord.</figcaption>
</figure>

On each of the six corners, working on the second layer first:

1. Slot an External bracket — cover onto the second layer's External bracket — side, before the extrusion goes in. It is awkward to fit afterwards.
2. Slide a piece D down through the second layer's bracket and on down through the matching corner of the bottom layer, so one piece passes through both.
3. Secure it at the second layer with 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws tapped through the holes near the bottom of the External bracket — side, bracing against the extrusion.
4. Secure it again at the bottom layer's External bracket — side the same way, 2 more {% include fastener.html size="M5" variant="socket-button" length="16" %} screws.

The two layers are now one rigid unit and their spacing is set by the bracket positions, not by anything you have to measure.

{% include step.html n="4" title="Close off the corners at floor level" %}

The bottom layer does not get an External bracket — bottom vertical or an External bracket — cover. It gets an **External bracket - foot cover** instead, one per corner, which is the single printed part that replaces both of them and closes the corner around the extrusion where it continues down to the caster.

The second layer's corners are ordinary: an External bracket — bottom vertical slid onto piece D with its angles aligned at the bottom, 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws through its outer holes.

{% include step.html n="5" title="Fit the feet" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Fit all six casters before the machine gets any taller. A bin tower on five feet is not something you want to discover at four layers.</p>
</div>

Bolt a **2020 M6 foot connector** into the open bottom end of each piece D. The connector is an aluminum bracket made for the end of 2020 extrusion and comes with its own bolts and nuts.

Screw a **swivel stem caster (M6 × 15 mm)** into the connector's M6 thread. The casters have brakes; leave them on while you build.

{% include step.html n="6" title="Add the bin retainers" %}

Both layers take bin retainers, exactly as in [regular layers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}) step 4: on each side of each hexagon, a Bin retainer (left) and a Bin retainer (right) on the front face of the A/G extrusion, 4 {% include fastener.html size="M5" variant="socket-button" length="12" %} screws into T-nuts.

## What comes next

- Each of these two layers takes a [chute]({{ '/hardware/assembly/distribution/chute/' | relative_url }}), the same as any other layer.
- Above them, build N−2 [regular layers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}) for an N-layer machine.
- The [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}) mounts to this frame on its three extrusion mounts.
