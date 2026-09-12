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
og_image: https://assets.basically.website/sorter-docs/classification-channel-finned-rotor-render-full-af779c513f96.png
contributors: [barthel, brickcyclealice, danny]
warning: >-
  **Steps 1 to 4 come from a build**, BrickCycleAlice's. **Step 5 is not verified**: the lamp's
  dovetail onto the NEMA bracket has been described by a builder but not photographed. Correct
  it as you build.
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
    <p><strong>Build a <a href="{{ '/hardware/assembly/feeder/c-channels/channel-core/' | relative_url }}">channel core</a> before you start.</strong> This page turns one core into the classification channel. It does not build the core.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-channel-core-cutout-full-538336057944.jpg" alt="A single C-channel core seen from above on a plain background: the stator ring with its exit opening, the three-armed NEMA bracket fastened across it, the raised hub at its centre and the stepper motor on the far side, with no rotor fitted">
    <figcaption>A channel core, no rotor in it yet. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}">camera lamp</a> before you start.</strong> This one carries the <strong>IMX415 4K module</strong>, not the OV9732 that C2 and C3 use. Its parts and screws are on that page.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-on-channel-w1600-8d957377d671.jpg" alt="A camera lamp on the machine: a grey disc-shaped lamp on an angled arm hanging over the open top of a C-channel, the white reflector lit inside it, with the black bulk bucket behind">
    <figcaption>A camera lamp over a channel. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

The classification channel is the last stage before a part drops into the chute, and the one the machine identifies the part on. It is the lowest of the four and sits flat on the top plate, with no support structure under it.

**One per machine.** The drive is the same core as the other three. The rotor, its cap and the camera are what make it the classification channel.

- **The finned rotor, not the faceted one.** The fins carry a part smoothly across the stage, which is what the camera needs.
- **The Rotor cap goes on this channel only.** It plugs the open bore through the middle of the finned rotor.
- **No output guide.** A fin would sweep straight through where the guide sits. The two guides belong to C2 and C3.

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

The Output gear (130T) bolts to the open side of the Rotor (finned).

<ol class="numbered-steps">
  <li>Turn the rotor so its open side faces up.</li>
  <li>Put the gear on it and line up the six holes. If it does not sit flat, turn it over.</li>
  <li>Drive one {% include fastener.html size="M3" variant="countersunk" length="12" %} screw at the outer end of each of the gear's six spokes, until the head is flush in the countersink.</li>
</ol>

It does not matter which way round you turn the gear. The six holes are the same all the way round.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-output-gear-bolted-to-rotor-w1600-7ca0b30ba41a.jpg" alt="The grey 130-tooth output gear with a black-sealed 6806 bearing pressed into its centre, bolted onto a white rotor behind it, with a countersunk screw at the outer end of each of the six spokes">
  <figcaption>Output gear bolted to a rotor. The joint is the same on the finned rotor. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="3" title="Cap the rotor" %}

Press the Rotor cap into the open hole at the top of the rotor, spigot first from above. Push it until its flange sits flat on the rotor. No screw.

{% include step.html n="4" title="Drop the rotor into the core" %}

Lower the rotor onto the raised hub in the middle of the NEMA bracket. The output gear meshes with the idler as it goes down.

Turn the rotor by hand. It should go all the way round without a tight spot.

**On the machine this happens later.** The classification channel goes in first of the four, before the three above it. See [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), steps 6 and 8.

{% include step.html n="5" title="Hang the camera lamp" %}

The lamp's arm mount hangs on a dovetail under the channel's NEMA bracket. There is no screw in that joint. The joint itself is step 7 of the [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}) page.

**Do this with the channel standing where it belongs**, not on the bench. Its height and overhang change what the camera sees.

## The finished result

A channel core with the finned rotor capped and dropped in, and a camera lamp over the top.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/classification-channel-finned-rotor-render-full-af779c513f96.png" alt="Render of the classification channel from above: the finned rotor sitting down in the stator ring, its six fins running from the centre out to the rim, with the NEMA bracket showing at one side">
  <figcaption>The finned rotor down in the stator, and the fins that tell this channel apart from the other three. The Rotor cap and the camera lamp are not shown. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

Machines built before 2026-09-02 image this channel with a white dome instead: see [classification chamber]({{ '/hardware/assembly/feeder/classification-chamber/' | relative_url }}).

Back to [C-channels]({{ '/hardware/assembly/feeder/c-channels/' | relative_url }}).
