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
og_image: https://assets.basically.website/sorter-docs/classification-channel-finished-capped-rotor-w1600-c4033d1a23b0.jpg
contributors: [barthel, brickcyclealice, danny, jensr80, daddyosbricksbill]
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
  - part: colour-strip-clip
    qty: 1
    optional: true
    note: For step 5.
  - part: colour-strip-studs
    qty: 1
    optional: true
    note: For step 5.
  - part: lego-tile-1x1
    qty: 8
    optional: true
    note: For step 5. One of each colour.
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
- **The colour strip is optional.** Eight LEGO tiles on the stator wall for colour calibration, in step 5.
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

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Colour strip (optional, for step 5):</strong> hold the Colour strip clip with its slot opening downwards. Lay the stud bar's thin lip along the top of the clip and press its hooked edge down over the clip's sloped outer face. The studs face the same side as the clip's short lip.</p>
    <p>Then press one 1 x 1 tile onto each stud, in this order from one end: Black, Dark Bluish Gray, Light Bluish Gray, White, Blue, Green, Yellow, Red. Use real LEGO tiles. The green is Green (BrickLink 6), not Bright Green.</p>
  </div>
  <div class="prep-item-figure prep-item-figure-split">
    <figure>
      <a href="https://assets.basically.website/sorter-docs/colour-strip-bar-and-clip-apart-png-full-fd14fac7d8d1.png" target="_blank" rel="noopener"><img class="doc-figure" src="https://assets.basically.website/sorter-docs/colour-strip-bar-and-clip-apart-png-full-fd14fac7d8d1.png" alt="The stud bar held above the clip, with an arrow showing it going down onto the clip"></a>
      <figcaption>The stud bar above the clip. <cite>Rendered from the part geometry, not from a build.</cite></figcaption>
    </figure>
    <figure>
      <a href="https://assets.basically.website/sorter-docs/colour-strip-bar-on-clip-png-full-3eae494f4983.png" target="_blank" rel="noopener"><img class="doc-figure" src="https://assets.basically.website/sorter-docs/colour-strip-bar-on-clip-png-full-3eae494f4983.png" alt="The stud bar on the clip: its thin lip along the top of the clip and its hooked edge over the clip's outer face"></a>
      <figcaption>The stud bar on the clip. <cite>Rendered from the part geometry, not from a build.</cite></figcaption>
    </figure>
    <figure>
      <a href="https://assets.basically.website/sorter-docs/colour-strip-tiles-camera-view-png-full-46eb0ae4de03.png" target="_blank" rel="noopener"><img class="doc-figure" src="https://assets.basically.website/sorter-docs/colour-strip-tiles-camera-view-png-full-46eb0ae4de03.png" alt="The clip and stud bar with the eight tiles on the studs, labelled from left to right: Red, Yellow, Green, Blue, White, Light Bluish Gray, Dark Bluish Gray and Black, each with its BrickLink colour number"></a>
      <figcaption>The tiles on the studs, Red at one end and Black at the other. Click to enlarge. <cite>Rendered from the part geometry, not from a build.</cite></figcaption>
    </figure>
  </div>
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

{% include step.html n="5" title="Fit the colour strip (optional)" %}

The colour strip puts eight tiles of known colours in the camera's view, for colour calibration. Skip this step if you are not fitting it. It only helps if the sorter uploads samples, so turn on sample capture in the Data section of the sorter's settings.

<ol class="numbered-steps">
  <li>Take the clip with the stud bar and tiles from the preparation step, slot opening downwards, and press it over the top of the stator wall with the short lip inside the channel. The tiles stand just above the rim, facing into the channel.</li>
  <li>Slide it along the wall until the Black end is about 45 to 50 mm before the exit opening, on the side the rotor brings the parts from. Red is the end furthest from the exit.</li>
</ol>

<figure class="single-figure">
  <a href="https://assets.basically.website/sorter-docs/colour-strip-on-stator-wall-from-inside-png-full-40333c4f233c.png" target="_blank" rel="noopener"><img class="doc-figure" src="https://assets.basically.website/sorter-docs/colour-strip-on-stator-wall-from-inside-png-full-40333c4f233c.png" alt="Render looking out at the stator wall from inside the channel: the clip sits over the top of the wall and the stud bar is hooked onto it, with the eight coloured tiles standing just above the rim and facing into the channel"></a>
  <figcaption>The strip on the wall, seen from inside the channel: Red on the left, Black on the right, nearest the exit. Click to enlarge. <cite>Rendered from the part geometry, not from a build.</cite></figcaption>
</figure>

<figure class="single-figure">
  <a href="https://assets.basically.website/sorter-docs/colour-strip-position-on-c4-png-full-beb53d39a4fc.png" target="_blank" rel="noopener"><img class="doc-figure" src="https://assets.basically.website/sorter-docs/colour-strip-position-on-c4-png-w1600-bff441066942.jpg" alt="Three panels. Left, a classification camera view with the colour strip at the edge of the frame, the exit opening and the drop zone marked. Middle, a top-down drawing of the channel in the same orientation, with the strip on the rim just before the exit opening, Black end nearest the opening. Right, a section through the stator wall with the clip's slot over the top of the wall and the stud bar hooked onto the clip"></a>
  <figcaption>Where the strip goes, and how the clip and the stud bar sit on the wall. Click to enlarge. <cite>Camera view: Spencer. Drawing and section from the part geometry.</cite></figcaption>
</figure>

## The finished result

A channel core with the finned rotor capped and dropped in. It goes onto the machine first of the four, before the three above it, and its camera lamp hangs on there too: see [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}).

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/classification-channel-finished-capped-rotor-w1600-c4033d1a23b0.jpg" alt="A finished classification channel on a wooden bench: the white finned rotor sitting down in the black stator ring with a small grey cap at its centre, the stepper motor at the left and the orange output gear showing at the gap in the ring">
  <figcaption>A finished classification channel, the capped rotor down in the core. <cite>Photo: JensR80.</cite></figcaption>
</figure>

The photo shows a white rotor and a black stator. Print both ash grey: the camera looks straight at them, white throws its exposure and white balance off, and black pieces disappear against black.

Back to [C-channels]({{ '/hardware/assembly/feeder/c-channels/' | relative_url }}).
