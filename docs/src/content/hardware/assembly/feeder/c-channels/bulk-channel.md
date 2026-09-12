---
layout: default
title: Bulk channel (C1)
type: how-to
section: hardware
slug: assembly-bulk-channel
kicker: Feeder — Bulk channel
lede: The top channel, where unsorted parts go in. The faceted rotor, the Bulk cap and the bucket over it.
permalink: /hardware/assembly/feeder/c-channels/bulk-channel/
author: barthel
contributors: [spencer, brickcyclealice]
warning: >-
  **Steps 1 to 3 come from a build**, BrickCycleAlice's. **Steps 4 to 6 are an AI-generated
  first draft**, written from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=bulk-bucket), not from
  an actual build. The bulk bucket is not published yet, so those steps are mostly the shape of
  what is missing. Fill them in as you build.
parts_needed:
  - part: rotor-faceted
    qty: 1
  - part: output-gear
    qty: 1
  - part: brg-6806-2rs
    qty: 1
  - part: scr-m3-12-cs
    qty: 6
  - part: bulk-cap
    qty: 1
---

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/feeder/c-channels/channel-core/' | relative_url }}">channel core</a> before you start.</strong> This page turns one core into C1. It does not build the core.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-channel-core-cutout-full-538336057944.jpg" alt="A single C-channel core seen from above on a plain background: the stator ring with its exit opening, the three-armed NEMA bracket fastened across it, the raised hub at its centre and the stepper motor on the far side, with no rotor fitted">
    <figcaption>A channel core, no rotor in it yet. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

C1 is where unsorted parts go in. A bucket over the channel feeds them onto the rotor as it turns, and from here a part travels down to C2, C3 and the classification channel.

**One per machine**, the highest of the four. It takes the faceted rotor, like C2 and C3.

- **No camera lamp and no separate output guide.** Nothing reads vision off C1, and the Bulk cap has a guide built into it.
- The Bulk cap prints in the feeder colour.

{% include fastener-legend.html %}

{% include step.html n="1" title="Preparation" %}

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Output gear (130T):</strong> press the 6806-2RS bearing into it. No screw, no glue, no heat.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-output-gear-bearing-pressed-w1600-238c650067c4.jpg" alt="The 130-tooth output gear lying flat with a black-sealed 6806 bearing pressed into its six-spoke hub">
    <figcaption>The output gear with its bearing pressed home. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="2" title="Bolt the output gear to the rotor" %}

Bolt the Output gear (130T) to the underside of the Rotor (faceted) with 6 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws, one at the outer end of each spoke, flush in the countersinks. Any of the six rotations works. The gear only fits one way up.

**Use the 12 mm, not the 8 mm.** An M3 × 8 seated in the countersink never reaches the rotor at all.

The faceted rotor takes no Rotor cap. It is closed at the apex.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-output-gear-bolted-to-rotor-w1600-7ca0b30ba41a.jpg" alt="The grey 130-tooth output gear with a black-sealed 6806 bearing pressed into its centre, bolted onto a white rotor behind it, with a countersunk screw at the outer end of each of the six spokes">
  <figcaption>Output gear bolted to a rotor. Six screws, one per spoke. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="3" title="Drop the rotor into the core" %}

Lower the rotor, output gear and all, onto the raised hub in the middle of the NEMA bracket, so the 130T meshes with the idler.

Turn the stage by hand. It should run with no tight spot through a full revolution.

**On the machine this happens later**, once the channels are standing at their heights. See [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), step 8.

{% include step.html n="4" title="Fit the bulk cap" %}

Slide the Bulk cap onto the stator along its dovetail. No screws.

**Not recorded:** which way it faces relative to the handover to C2.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">&#9888;</span>
  <p>Use the current Bulk cap. The v1 dovetail needed too much force to slide on. If yours is a fight, check you have the latest file rather than forcing it.</p>
</div>

<div class="img-placeholder">Image coming</div>

{% include step.html n="5" title="Mount the bucket supports" %}

Three pieces of 2020 extrusion, cut to 270 mm, carry the bucket above the channel. They are on the bill of materials as bulk bucket supports.

**Not recorded:** where they land on the [C-channel stand]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), what fastens them at either end, and how high the bucket sits above the rotor.

<div class="img-placeholder">Image coming</div>

{% include step.html n="6" title="Fit the bucket" %}

Not documented, and the part is not published. Record the file, the fixings and the drop height here when it is.

<div class="img-placeholder">Image coming</div>

## The finished result

A channel core with the faceted rotor in it, the Bulk cap on the stator, and the bucket standing over it.

<div class="img-placeholder">Photo of a finished C1: pending from a build.</div>

Back to [C-channels]({{ '/hardware/assembly/feeder/c-channels/' | relative_url }}).
