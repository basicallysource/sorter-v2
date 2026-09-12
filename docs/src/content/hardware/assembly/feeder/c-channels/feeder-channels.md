---
layout: default
title: Feeder channels (C2 and C3)
type: how-to
section: hardware
slug: assembly-feeder-channels
kicker: Feeder — Feeder channels
lede: The two metering stages between the bulk channel and classification, with a faceted rotor, an output guide and a camera lamp each.
permalink: /hardware/assembly/feeder/c-channels/feeder-channels/
author: barthel
contributors: [spencer, brickcyclealice, danny, reveryx]
og_image: https://assets.basically.website/sorter-docs/camera-lamp-mounted-wide-w1600-247fb837f4f8.jpg
warning: >-
  **Steps 1 to 3 come from a build**, BrickCycleAlice's. **Step 4 is not verified**: the output
  guide is held by friction, but where it seats, at what angle and how far it projects are not
  recorded anywhere. Fill that in as you build.
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
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-channel-core-cutout-full-538336057944.jpg" alt="A single C-channel core seen from above on a plain background: the stator ring with its exit opening, the three-armed NEMA bracket fastened across it, the raised hub at its centre and the stepper motor on the far side, with no rotor fitted">
    <figcaption>A channel core, no rotor in it yet. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}">camera lamp</a> before you start.</strong> One per channel, carrying the OV9732 camera. Its parts and screws are on that page.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-on-channel-w1600-8d957377d671.jpg" alt="A camera lamp on the machine: a grey disc-shaped lamp on an angled arm hanging over the open top of a C-channel, the white reflector lit inside it, with the black bulk bucket behind">
    <figcaption>A camera lamp over a channel. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

C2 and C3 are the two metering stages. Each takes a part from the channel above, spaces it out further by rotation, and pushes it off its exit to the next channel down. The camera over each one is what the software reads.

**The parts list above is one channel's worth. Build two**, one for C2 and one for C3. They are the same build. Only the height differs, and that is set on [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}).

- **The faceted rotor**, the same one C1 takes. It takes no Rotor cap.
- **One output guide each**, two in the machine. The guide belongs to the channel it is mounted on, not to the gap between two.
- **One camera lamp each**, with the OV9732.

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

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-output-gear-bolted-to-rotor-w1600-7ca0b30ba41a.jpg" alt="The grey 130-tooth output gear with a black-sealed 6806 bearing pressed into its centre, bolted onto a white rotor behind it, with a countersunk screw at the outer end of each of the six spokes">
  <figcaption>Output gear bolted to a rotor. Six screws, one per spoke. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="3" title="Drop the rotor into the core" %}

Lower the rotor, output gear and all, onto the raised hub in the middle of the NEMA bracket, so the 130T meshes with the idler.

Turn the stage by hand. It should run with no tight spot through a full revolution.

**On the machine this happens later**, once the channels are standing at their heights. See [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), step 8.

{% include step.html n="4" title="Fit the output guide" %}

The guide is a wall on the channel's exit. Without it a part that does not drop off rides round the rotor again.

Push it onto the drive. It is held by the fit alone: no screws, nothing to tighten. Fit it once the channel is at its final height.

**Not recorded:** where on the drive it seats, at what angle, and how far it projects over the exit.

<div class="img-placeholder">Image coming</div>

Turn both channels by hand with a few parts on the upstream rotor. A part should leave one rotor and land on the next without being carried back around.

{% include step.html n="5" title="Hang the camera lamp" %}

The lamp's arm mount hangs off a dovetail under the channel's NEMA bracket. There is no screw in that joint. See [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}), step 7.

**Do this with the channel standing where it belongs.** Height and overhang change what the camera sees.

## The finished result

A channel core with the faceted rotor in it, an output guide on the exit, and a camera lamp over the top.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-mounted-wide-w1600-247fb837f4f8.jpg" alt="A wider view of a camera lamp on the machine, showing the full length of the arm from the lamp down to the C-channel, with a bracket screwed along the joint and the LED leads cable-tied along the arm">
  <figcaption>A feeder channel with its lamp on, the arm running down to the drive. <cite>Photo: Spencer.</cite></figcaption>
</figure>

Back to [C-channels]({{ '/hardware/assembly/feeder/c-channels/' | relative_url }}).
