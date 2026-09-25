---
layout: default
title: Feeder channels (C2 and C3)
type: how-to
section: hardware
slug: assembly-feeder-channels
kicker: Feeder — Feeder channels
lede: The two metering stages between the bulk channel and classification, with a faceted rotor and an output guide each.
permalink: /hardware/assembly/feeder/c-channels/feeder-channels/
author: barthel
contributors: [spencer, brickcyclealice, danny, reveryx, daddyosbricksbill]
og_image: https://assets.basically.website/sorter-docs/assembly-c-channel-finished-stage-w1600-9bd3719c4180.jpg
warning: >-
  **Steps 1 to 3 come from a build**, BrickCycleAlice's. **Step 4 is not verified.**
tools_needed: ["Hex key, 2 mm"]
parts_needed:
  - part: rotor-faceted
    qty: 1
  - part: output-gear
    qty: 1
  - part: brg-6806-2rs
    qty: 1
  - part: scr-m3-12-cs
    qty: 6
  - part: output-guide
    qty: 1
---

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/feeder/c-channels/channel-core/' | relative_url }}">channel core</a> before you start.</strong> This page turns one core into C2 or C3. It does not build the core.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-channel-core-finished-top-w1600-4713962f4dfd.jpg" alt="A finished channel core from directly above: the stator ring open at one side, the three-armed NEMA bracket fastened across it with the raised hub at its centre, the gear train at the ring's edge and the stepper motor standing outside the wall with its lead, and no rotor in the hub">
    <figcaption>A channel core, no rotor in it yet. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

C2 and C3 are the two metering stages. Each takes a part from the channel above, spaces it out further by rotation, and pushes it off its exit to the next channel down.

**The parts list above is one channel's worth. Build two**, one for C2 and one for C3. They are the same build. Only the height differs, and that is set on [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}).

- **The faceted rotor**, the same one C1 takes. It takes no Rotor cap.
- **One output guide each**, two in the machine. The guide belongs to the channel it is mounted on, not to the gap between two.
- **A camera lamp hangs over each of these two**, but not here: it goes on at [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), with the channel standing.

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

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-feeder-channel-rotor-and-stepper-full-89ba6b47c8ca.jpg" alt="A feeder channel seen from above on a plain background: the faceted rotor sitting down in the stator ring, with the stepper motor standing out from under the ring at one side, and nothing mounted on the channel">
  <figcaption>The rotor down in the core. Nothing else is on the channel at this stage. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="4" title="Fit the output guide" %}

The guide is a wall at the channel's exit. Without it, a part that does not drop off rides round the rotor again.

Push the guide onto the drive at the exit, so it stands across the opening in the stator wall. It is held by the fit alone: no screws, nothing to tighten.

<div class="img-placeholder">Image coming</div>

## The finished result

A channel core with the faceted rotor in it and an output guide at the exit. Build two, then stand them at their heights on [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), where the camera lamps go on.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-finished-stage-w1600-9bd3719c4180.jpg" alt="A C-channel from above on a plain surface: the faceted rotor sitting down in the stator ring, with the stepper motor and its lead standing off one side">
  <figcaption>A finished feeder channel, rotor in and stepper on the outside. The output guide is not in this shot. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

Back to [C-channels]({{ '/hardware/assembly/feeder/c-channels/' | relative_url }}).
