---
layout: default
title: Classification channel (C4)
type: how-to
section: hardware
slug: assembly-classification-channel
kicker: Feeder — Classification channel
lede: The lowest channel, where the part is imaged. The finned rotor, its cap, and a camera lamp carrying the 4K module.
permalink: /hardware/assembly/feeder/c-channels/classification-channel/
author: spencer
contributors: [barthel, brickcyclealice, danny]
og_image: https://assets.basically.website/sorter-docs/assembly-c-channel-finished-stage-w1600-9bd3719c4180.jpg
warning: >-
  **Steps 1 to 4 come from a build**, BrickCycleAlice's, and are the same rotor unit every
  channel uses, with the finned rotor and its cap. **Step 5 is not verified**: the lamp's
  dovetail onto the NEMA bracket has been described by a builder but not dimensioned or
  photographed. Correct it as you build.
parts_needed:
  - part: rotor-finned
    qty: 1
  - part: output-gear
    qty: 1
  - part: brg-6806-2rs
    qty: 1
  - part: rotor-cap
    qty: 1
  - part: scr-m3-12-cs
    qty: 6
---

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/feeder/c-channels/channel-core/' | relative_url }}">channel core</a> before you start.</strong> It's a required component of this page, not optional or covered here. This page turns one core into the classification channel.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-channel-core-single-top-full-6dbc4b7bb3a0.jpg" alt="A single C-channel core seen from above: the stator ring with its exit opening, the three-armed NEMA bracket fastened across it, the raised hub at its centre and the stepper motor on the far side, with no rotor fitted">
    <figcaption>A channel core, no rotor in it yet. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}">camera lamp</a> before you start.</strong> Also a required component, and this one carries the <strong>IMX415 4K module</strong> rather than the OV9732 that C2 and C3 use. Its parts and screws are on that page, not in the list above.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-on-channel-w1600-8d957377d671.jpg" alt="A camera lamp on the machine: a grey disc-shaped lamp on an angled arm hanging over the open top of a C-channel, the white reflector lit inside it, with the black bulk bucket behind">
    <figcaption>A camera lamp over a channel. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

The classification channel is the last stage before the part drops into the chute, and the one the machine actually looks at: the camera over it is what Brickognize is fed. It is the lowest of the four and sits flat on the top plate, with no support structure of its own.

**One per machine.** The drive under it is the same core as the other three; what makes it the classification channel is the rotor, the cap in the top of it and the camera on the lamp.

- **The finned rotor, not the faceted one.** The fins keep a piece moving smoothly across the stage, which is what imaging wants; the faceted cone's job on C1 to C3 is grip for singulation. It prints ash grey like the rest of the channel.
- **The Rotor cap goes on this channel only.** The finned rotor has an open 25 mm bore through its centre and the cap plugs it. The faceted rotor is solid at the apex and takes none.
- **No output guide.** The guide and the standard finned rotor cannot both be on this channel: the fins reach about 19 mm further out than the faceted cone over the same band of height, so a fin sweeps through where the guide's inner face sits for roughly a third of every revolution. No clocking fixes that, because a rotor covers every azimuth. The guides are C2's and C3's.

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
    <p><strong>Rotor cap:</strong> a friction fit into the finned rotor's open bore. No screw, no insert.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

{% include step.html n="2" title="Bolt the output gear to the rotor" %}

Bolt the Output gear onto the underside of the Rotor (finned) with 6 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws, one at the outer end of each spoke, seated flush in the countersinks. The six holes are 60° apart on a 90 mm bolt circle. The pattern is symmetric, so any of the six rotations works, but the gear can only be fitted right-side up. It is the same joint as on the faceted rotor.

**Use the 12 mm, not the 8 mm.** The gear is 8 mm thick at the bolt circle, and a countersunk screw's length is measured over its head, so an M3 × 8 seated flush in the countersink finishes level with the top of the gear and never enters the rotor at all. The 12 mm leaves 4 mm of thread in the rotor's 5 mm flange and stops short of breaking through the far side.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-output-gear-bolted-to-rotor-w1600-7ca0b30ba41a.jpg" alt="The grey 130-tooth output gear with a black-sealed 6806 bearing pressed into its centre, bolted onto a white rotor behind it, with a countersunk screw at the outer end of each of the six spokes">
  <figcaption>Output gear, bearing pressed in, bolted to a rotor. Six screws, one per spoke. This one is a faceted rotor; the joint is identical on the finned one. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="3" title="Cap the rotor" %}

Press the Rotor cap into the open bore at the top of the finned rotor, spigot first from above, until its flange sits down on the apex. It is a friction fit and takes no screw.

{% include step.html n="4" title="Drop the rotor into the core" %}

Lower the rotor, output gear and all, onto the raised hub in the middle of the NEMA bracket, so the 130T comes down into mesh with the idler.

Turn the stage by hand before wiring it. The train should run without a tight spot anywhere in a full revolution.

**On the machine this happens later**, once the channels are standing at their heights. The classification channel goes in first of the four, before the three above it. See [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), steps 6 and 8.

{% include step.html n="5" title="Hang the camera lamp" %}

The lamp's arm mount hangs off a dovetail on the bottom of the channel's NEMA bracket. There is no screw in that joint. See [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}), step 7, for the joint itself.

**This lamp carries the IMX415**, the 4K module, where C2's and C3's carry the OV9732. Everything else about the lamp is identical.

**Do this with the channel standing where it belongs**, not on the bench: height and overhang both change what the camera sees, and [camera calibration]({{ '/sorter/camera-calibration/' | relative_url }}) afterwards is software, not a way to fix a lamp in the wrong place.

## The finished result

A channel core with the finned rotor capped and dropped in, and a camera lamp on an arm over the top.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-finished-stage-w1600-9bd3719c4180.jpg" alt="A finished channel: the finned rotor sitting down in the grey stator ring with the stepper motor and its lead standing off one side">
  <figcaption>The finned rotor down in the stator, stepper on the outside. The lamp goes on once the channel is standing. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

The earlier way of imaging this channel, a white dome with the camera and LEDs in an insert, is retired: see [classification chamber]({{ '/hardware/assembly/feeder/classification-chamber/' | relative_url }}) if your machine is already built that way.

Back to [C-channels]({{ '/hardware/assembly/feeder/c-channels/' | relative_url }}).
