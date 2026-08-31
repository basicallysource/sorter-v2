---
layout: default
title: Arranging C-channels
type: how-to
section: hardware
slug: assembly-arranging-c-channels
kicker: Feeder — Arranging C-channels
lede: How the four C-channels stand, at what heights, and what passes parts between them.
permalink: /hardware/assembly/feeder/arranging-c-channels/
author: barthel
warning: >-
  **AI-generated first draft.** Written from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=feeder) and the
  extrusion list on the bill of materials, not from an actual build. No height, angle or fastener here
  has been checked against a machine, and the two starred steps are the ones that make the
  feeder work. Fill it in as you build.
parts_needed:
  - part: leg
    qty: 9
  - part: foot
    qty: 9
  - part: leg-extension
    qty: 9
---

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build all four <a href="{{ '/hardware/assembly/feeder/c-channel/' | relative_url }}">C-channels</a> before you start.</strong> They're required components of this page, not optional or covered here — this page arranges and heights four already-built channels, it doesn't build them. Three with the faceted rotor, one with the finned one.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-stator-and-rotor-fitted-w1600-60758bbee2d5.jpg" alt="A finished C-channel seen from above: the white finned classification rotor sitting inside the grey stator ring, with the stepper motor projecting from the right-hand side">
    <figcaption>A finished C-channel, from the C-channel page. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

Four [C-channels]({{ '/hardware/assembly/feeder/c-channel/' | relative_url }}) are built the same way and then stood at different heights, so a part cascades from one to the next under gravity and arrives at the [interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}) singulated.

The fasteners and quantities in the parts list come from the parts registry and are called out inline at each step.

{% include fastener-legend.html %}

Steps below refer to the channels by the names the software uses, in the order a part travels:

- **C1**, the bulk channel, under the [bulk input]({{ '/hardware/assembly/feeder/bulk-input/' | relative_url }}). Highest.
- **C2**, with a [light post]({{ '/hardware/assembly/feeder/light-post/' | relative_url }}) and an [overhead camera mount]({{ '/hardware/assembly/feeder/camera-mount/' | relative_url }}).
- **C3**, the same again, and the last metering stage.
- **The classification channel**, inside the [classification chamber]({{ '/hardware/assembly/feeder/classification-chamber/' | relative_url }}), which images the part before it drops into the chute.

{% include step.html n="1" title="Preparation" %}

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Legs, feet and leg extensions:</strong> 3 of each per channel, 9 of each across the three feeder channels. The Leg is the 135 mm print, the extension raises it further, and the foot is what meets the bench. No heat inserts recorded.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Feeder extrusion, from the bill of materials:</strong> 3 pieces of 2020 at 270 mm (bulk bucket supports), 3 at 190 mm (mid C-channel supports), 3 at 110 mm (lower C-channel supports), and the camera support, either 1 at 300 mm fixed or 1 at 350 mm plus 1 at 200 mm adjustable. No step records what any of them bolts to.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

{% include step.html n="2" title="Stand each channel" %}

Fit 3 legs, 3 extensions and 3 feet to each of the three feeder channels.

**Not recorded:** how the leg, extension and foot stack, what fastens them to each other, and how a leg attaches to the channel's stator or NEMA bracket. <span class="fastener-todo">fastener not recorded</span>

**Not recorded:** whether the classification channel stands on legs of its own or is carried by the chamber and the interface below it. The catalog gives 9 of each for the feeder and none for the classification channel, which suggests the latter.

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="★ Set the heights and the spacing (the numbers that make parts actually cascade)" %}

The numbers this page most needs, and none of them are written down anywhere today. For each handover, record:

- the drop from one rotor to the next,
- the horizontal overlap between the two channels,
- how far around the circle the handover happens.

<div class="img-placeholder">Image coming</div>

{% include step.html n="4" title="Fit the output guides" %}

One [output guide]({{ '/hardware/assembly/feeder/output-guides/' | relative_url }}) at each handover, C1 to C2 and C2 to C3.

<div class="img-placeholder">Image coming</div>

{% include step.html n="5" title="Add the bulk input, the light posts and the camera arms" %}

[Bulk input]({{ '/hardware/assembly/feeder/bulk-input/' | relative_url }}) on C1. A [light post]({{ '/hardware/assembly/feeder/light-post/' | relative_url }}) and an [overhead camera mount]({{ '/hardware/assembly/feeder/camera-mount/' | relative_url }}) on C2 and on C3.

<div class="img-placeholder">Image coming</div>

{% include step.html n="6" title="★ Hand over to the classification channel (the other unresolved joint)" %}

The other open question: how the classification channel sits relative to C3 and to the [top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}) below it, and what carries its weight.

<div class="img-placeholder">Image coming</div>

{% include step.html n="7" title="Turn it all by hand" %}

Run parts through the whole cascade by hand, one channel at a time, before wiring the steppers. Anything that needs a nudge here will jam under power. Wiring is on the [electronics]({{ '/hardware/electronics/' | relative_url }}) page.

<div class="img-placeholder">Image coming</div>
