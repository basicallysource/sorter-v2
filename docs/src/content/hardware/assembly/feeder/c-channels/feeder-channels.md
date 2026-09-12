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
  **Steps 1 to 3 come from a build**, BrickCycleAlice's, and are the same rotor unit every
  channel uses. **Step 4 is not verified**: the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=channel-two) records that
  the output guide is held by friction, but not where on the drive it seats, at what angle, or
  how far it projects. Fill that in as you build.
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
    <p><strong>Build a <a href="{{ '/hardware/assembly/feeder/c-channels/channel-core/' | relative_url }}">channel core</a> before you start.</strong> It's a required component of this page, not optional or covered here. This page turns one core into C2 or C3.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-c4-on-c3-guide-full-574058daee19.jpg" alt="A C-channel drive with no rotor in it: the stator ring with its stepper motor on the bracket underneath, slid onto a printed layout guide, with other stands lying around it">
    <figcaption>A channel core, no rotor in it yet. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}">camera lamp</a> before you start.</strong> Also a required component, one per channel, carrying the OV9732 camera. Its parts and screws are on that page, not in the list above.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-on-channel-w1600-8d957377d671.jpg" alt="A camera lamp on the machine: a grey disc-shaped lamp on an angled arm hanging over the open top of a C-channel, the white reflector lit inside it, with the black bulk bucket behind">
    <figcaption>A camera lamp over a channel. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

C2 and C3 are the two metering stages. Each takes a part from the channel above, spaces it out further by rotation, and pushes it off its exit to the next one down. Both are imaged: the software's crop zones are the second channel, the third channel and the classification channel.

**The parts list above is one channel's worth. Build two**, one for C2 and one for C3. They are the same build, and the only thing that differs between them is how high they stand, which is the support leg under each and is set on [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}).

- **The faceted rotor**, the same one C1 takes. It is solid at the apex, so no Rotor cap.
- **One output guide each.** There are two in the machine, one on C2 and one on C3. A guide belongs to the channel it is mounted on rather than to the gap between two, so the count is not one per handover.
- **One camera lamp each**, with the OV9732. The classification channel's carries the 4K module instead.

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
    <p><strong>Short and Angled Output Guide:</strong> no heat inserts recorded and no fasteners of its own. Prints ash grey.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

{% include step.html n="2" title="Bolt the output gear to the rotor" %}

Bolt the Output gear onto the underside of the Rotor (faceted) with 6 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws, one at the outer end of each spoke, seated flush in the countersinks. The six holes are 60° apart on a 90 mm bolt circle. The pattern is symmetric, so any of the six rotations works, but the gear can only be fitted right-side up.

**Use the 12 mm, not the 8 mm.** The gear is 8 mm thick at the bolt circle, and a countersunk screw's length is measured over its head, so an M3 × 8 seated flush in the countersink finishes level with the top of the gear and never enters the rotor at all. The 12 mm leaves 4 mm of thread in the rotor's 5 mm flange and stops short of breaking through the far side.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-output-gear-bolted-to-rotor-w1600-7ca0b30ba41a.jpg" alt="The grey 130-tooth output gear with a black-sealed 6806 bearing pressed into its centre, bolted onto a white rotor behind it, with a countersunk screw at the outer end of each of the six spokes">
  <figcaption>Output gear, bearing pressed in, bolted to a rotor. Six screws, one per spoke. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="3" title="Drop the rotor into the core" %}

Lower the rotor, output gear and all, onto the raised hub in the middle of the NEMA bracket, so the 130T comes down into mesh with the idler.

Turn the stage by hand before wiring it. The train should run without a tight spot anywhere in a full revolution.

**On the machine this happens later**, once the channels are standing at their heights. See [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), step 8.

{% include step.html n="4" title="Fit the output guide" %}

The guide is a wall on the channel's exit. Without one, a piece that does not drop off at the exit carries on round the rotor instead, so the guide forces it off.

It pushes onto the drive and is held by the fit alone: no screws, no inserts, nothing to tighten. Fit it once the channel is at its final height, not on the bench.

**Not recorded:** where on the drive it seats, at what angle, and how far it projects over the exit.

<div class="img-placeholder">Image coming</div>

Turn both channels by hand with a few parts on the upstream rotor and watch the transfer before wiring anything. A part should leave one rotor and land on the next without being carried back around. Write down here what gap and angle worked.

{% include step.html n="5" title="Hang the camera lamp" %}

The lamp's arm mount hangs off a dovetail on the bottom of the channel's NEMA bracket. There is no screw in that joint. See [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}), step 7, for the joint itself.

**Do this with the channel standing where it belongs**, not on the bench: height and overhang both change what the camera sees, and [camera calibration]({{ '/sorter/camera-calibration/' | relative_url }}) afterwards is software, not a way to fix a lamp in the wrong place.

## The finished result

A channel core with the faceted rotor in it, an output guide on the exit, and a camera lamp on an arm over the top.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-mounted-wide-w1600-247fb837f4f8.jpg" alt="A wider view of a camera lamp on the machine, showing the full length of the arm from the lamp down to the C-channel, with a bracket screwed along the joint and the LED leads cable-tied along the arm">
  <figcaption>A feeder channel with its lamp on, the arm running down to the drive. <cite>Photo: Spencer.</cite></figcaption>
</figure>

Back to [C-channels]({{ '/hardware/assembly/feeder/c-channels/' | relative_url }}).
