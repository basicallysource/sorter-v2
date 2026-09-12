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

- **No camera lamp and no output guide.** The machine does not look at C1, and the Bulk cap has a guide built into it.
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

The Output gear (130T) bolts to the open side of the Rotor (faceted).

<ol class="numbered-steps">
  <li>Turn the rotor so its open side faces up.</li>
  <li>Put the gear on it and line up the six holes. If it does not sit flat, turn it over.</li>
  <li>Drive one {% include fastener.html size="M3" variant="countersunk" length="12" %} screw at the outer end of each of the gear's six spokes, until the head is flush in the countersink.</li>
</ol>

It does not matter which way round you turn the gear. The six holes are the same all the way round.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-output-gear-bolted-to-rotor-w1600-7ca0b30ba41a.jpg" alt="The grey 130-tooth output gear with a black-sealed 6806 bearing pressed into its centre, bolted onto a white rotor behind it, with a countersunk screw at the outer end of each of the six spokes">
  <figcaption>Output gear bolted to a rotor. Six screws, one per spoke. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="3" title="Drop the rotor into the core" %}

Lower the rotor onto the raised hub in the middle of the NEMA bracket. The output gear meshes with the idler as it goes down.

Turn the rotor by hand. It should go all the way round without a tight spot.

**On the machine this happens later**, once the channels are standing at their heights. See [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), step 8.

{% include step.html n="4" title="Fit the bulk cap" %}

Slide the Bulk cap down onto the dovetail on the outside of the stator wall. No screws.

**Not recorded:** which way it faces relative to the handover to C2.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">&#9888;</span>
  <p>Use the current Bulk cap. The v1 dovetail needed too much force to slide on. If yours is a fight, check you have the latest file rather than forcing it.</p>
</div>

<div class="img-placeholder">Image coming</div>

{% include step.html n="5" title="Mount the bucket supports" %}

Three pieces of 2020 aluminium extrusion, each cut to 270 mm, hold the bucket above the channel. They are on the bill of materials as bulk bucket supports.

**Not recorded:** where they land on the [C-channel stand]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), what fastens them at either end, and how high the bucket sits above the rotor.

<div class="img-placeholder">Image coming</div>

{% include step.html n="6" title="Fit the bucket" %}

Not documented, and the part is not published. Record the file, the fixings and the drop height here when it is.

<div class="img-placeholder">Image coming</div>

## The finished result

A channel core with the faceted rotor in it, the Bulk cap on the stator, and the bucket standing over it.

<div class="img-placeholder">Photo of a finished C1: pending from a build.</div>

Back to [C-channels]({{ '/hardware/assembly/feeder/c-channels/' | relative_url }}).
