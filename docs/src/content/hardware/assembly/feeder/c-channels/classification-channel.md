---
layout: default
title: Classification channel (C4)
type: how-to
section: hardware
slug: assembly-classification-channel
kicker: Feeder — Classification channel
lede: The lowest channel, where the part is imaged. The finned rotor and its cap.
permalink: /hardware/assembly/feeder/c-channels/classification-channel/
author: spencer
og_image: https://assets.basically.website/sorter-docs/render-classification-channel-with-lamp-full-34ceed40a766.png
contributors: [barthel, brickcyclealice, danny, daddyosbricksbill]
last_verified: 2026-09-25
tools_needed: ["Hex key, 2 mm"]
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
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-channel-core-finished-top-w1600-4713962f4dfd.jpg" alt="A finished channel core from directly above: the stator ring open at one side, the three-armed NEMA bracket fastened across it with the raised hub at its centre, the gear train at the ring's edge and the stepper motor standing outside the wall with its lead, and no rotor in the hub">
    <figcaption>A channel core, no rotor in it yet. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

The classification channel is the last stage before a part drops into the chute, and the one the machine identifies the part on. It is the lowest of the four and sits flat on the top plate, with no support structure under it.

**One per machine.** The drive is the same core as the other three. The rotor and its cap are what make it the classification channel.

- **The finned rotor, not the faceted one.** The fins carry a part smoothly across the stage, which is what the camera needs.
- **The Rotor cap goes on this channel only.** It plugs the open bore through the middle of the finned rotor.
- **No output guide.** A fin would sweep straight through where the guide sits. The two guides belong to C2 and C3.
- **The camera lamp hangs on later**, at [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), with the channel standing.

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

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/render-classification-channel-rotor-capped-full-90f84be1a1c9.png" alt="Render of the classification channel from above: the finned rotor sitting down in the stator ring with its fins running out to the rim, the rotor cap seated as a round disc in the middle of it, and the gear train and bracket outside the ring">
  <figcaption>The finned rotor down in the core, capped. <cite>Rendered from the part geometry, not from a build.</cite></figcaption>
</figure>

## The finished result

A channel core with the finned rotor capped and dropped in. It goes onto the machine first of the four, before the three above it: see [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), step 5, and its camera lamp hangs on there too.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/render-classification-channel-with-lamp-full-34ceed40a766.png" alt="Render of the finished classification channel: the capped finned rotor in the stator, and the camera lamp centred directly over the rotor on its angled arm, which runs down the outside of the channel wall to a dovetail">
  <figcaption>The classification channel with its lamp over it. The stepper and the 4K camera board are bought parts with no model, so they are not in the render. <cite>Rendered from the part geometry, not from a build.</cite></figcaption>
</figure>

Back to [C-channels]({{ '/hardware/assembly/feeder/c-channels/' | relative_url }}).
