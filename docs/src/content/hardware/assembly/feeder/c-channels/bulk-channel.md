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
  **Steps 1 to 3 come from a build**, BrickCycleAlice's, and are the same rotor unit every
  channel uses. **Steps 4 to 6 are an AI-generated first draft**, written from the machine
  assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=bulk-bucket) and the
  extrusion list on the bill of materials, not from an actual build. The bulk bucket itself is
  not published yet, so that part of the page is mostly the shape of what is missing. Fill it in
  as you build.
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
    <p><strong>Build a <a href="{{ '/hardware/assembly/feeder/c-channels/channel-core/' | relative_url }}">channel core</a> before you start.</strong> It's a required component of this page, not optional or covered here. This page turns one core into C1.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-c4-on-c3-guide-full-574058daee19.jpg" alt="A C-channel core: the stator ring with its stepper motor on the bracket underneath and an empty hub in the middle, standing on a printed layout guide">
    <figcaption>A channel core, no rotor in it yet. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

C1 is where unsorted parts go in: a bucket held above the channel feeds them down onto the rotor as it turns. Parts dropped here start the feeder cascade, leaving C1's rotor for C2, then C3, and finally the classification channel, each stage spacing them out further before classification.

**One per machine**, the highest of the four. It takes the faceted rotor, like C2 and C3.

- **No camera lamp and no separate output guide.** C1 is fed in bulk and nothing reads vision off it, and the Bulk cap carries a guide built into it, so there is no second one to fit.
- The Bulk cap prints in the feeder colour. The rotor and the output gear are ash grey and charcoal respectively, the same as every other channel.

{% include fastener-legend.html %}

{% include step.html n="1" title="Preparation" %}

**No heat inserts.** The rotor's six holes are Ø2.8 mm, thread-forming, and the output gear is Ø3.4 mm clearance throughout. Stop as soon as a screw seats.

Press the bearing into the output gear first, while the parts are loose and you can support them on the bench.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Output gear (130T):</strong> one 6806-2RS bearing, 30 mm bore. A press fit: no screws, no adhesive, no heat.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-output-gear-bearing-pressed-w1600-238c650067c4.jpg" alt="The 130-tooth output gear lying flat with a black-sealed 6806 bearing pressed into its six-spoke hub">
    <figcaption>The output gear with its bearing pressed home. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Bulk cap:</strong> no heat inserts, no screws recorded. It slides onto the C1 stator on a dovetail. Print it in the feeder colour.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Bulk bucket:</strong> not published. It is a separate print, roughly a full bed, and is not in the parts catalog, so there is no file to link and no quantity to give. Ask in the Discord server before printing a stand-in part; the bulk bucket isn't published yet, so there's no verified file to copy.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">&#9888;</span>
  <p>Use the current Bulk cap. The v2 revision (2026-08-18) opened up the dovetail clearance because v1 needed too much force to slide on. If yours is a fight, check the file first rather than forcing it.</p>
</div>

{% include step.html n="2" title="Bolt the output gear to the rotor" %}

Bolt the Output gear onto the underside of the Rotor (faceted) with 6 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws, one at the outer end of each spoke, seated flush in the countersinks. The six holes are 60° apart on a 90 mm bolt circle. The pattern is symmetric, so any of the six rotations works, but the gear can only be fitted right-side up.

**Use the 12 mm, not the 8 mm.** The gear is 8 mm thick at the bolt circle, and a countersunk screw's length is measured over its head, so an M3 × 8 seated flush in the countersink finishes level with the top of the gear and never enters the rotor at all. The 12 mm leaves 4 mm of thread in the rotor's 5 mm flange and stops short of breaking through the far side.

**The faceted rotor takes no cap.** It is solid at the apex; the Rotor cap belongs to the finned rotor on the classification channel.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-output-gear-bolted-to-rotor-w1600-7ca0b30ba41a.jpg" alt="The grey 130-tooth output gear with a black-sealed 6806 bearing pressed into its centre, bolted onto a white rotor behind it, with a countersunk screw at the outer end of each of the six spokes">
  <figcaption>Output gear, bearing pressed in, bolted to a rotor. Six screws, one per spoke. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="3" title="Drop the rotor into the core" %}

Lower the rotor, output gear and all, onto the raised hub in the middle of the NEMA bracket, so the 130T comes down into mesh with the idler.

Turn the stage by hand before wiring it. The train should run without a tight spot anywhere in a full revolution.

**On the machine this happens later**, once the channels are standing at their heights. See [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), step 8.

{% include step.html n="4" title="Fit the bulk cap" %}

Slide the Bulk cap onto the stator along its dovetail. No screws are recorded for this joint.

**Not recorded:** which way it faces relative to the handover to C2.

<div class="img-placeholder">Image coming</div>

{% include step.html n="5" title="Mount the bucket supports" %}

Three pieces of 2020 extrusion cut to 270 mm carry the bucket above the channel. They are on the bill of materials as bulk bucket supports.

**Not recorded:** where they land on the [C-channel stand]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), what fastens them at either end, and how high the bucket sits above the rotor.

<div class="img-placeholder">Image coming</div>

{% include step.html n="6" title="Fit the bucket" %}

Not documented, and the part is not published. Record the file, the fixings and the drop height here when it is.

<div class="img-placeholder">Image coming</div>

## The finished result

A channel core with the faceted rotor in it and the Bulk cap on the stator, with the bucket standing over it.

<div class="img-placeholder">Photo of a finished C1: pending from a build.</div>

Back to [C-channels]({{ '/hardware/assembly/feeder/c-channels/' | relative_url }}).
