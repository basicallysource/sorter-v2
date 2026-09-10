---
layout: default
title: Chute core
type: how-to
section: hardware
slug: assembly-chute-core
kicker: Chute — Chute core
lede: The chute assembly. Build one per layer.
permalink: /hardware/assembly/distribution/chute/chute-core/
author: spencer
contributors: [barthel]
og_image: https://assets.basically.website/sorter-docs/assembly-chute-core-built-w1600-6d9c4c0c0ac6.jpg
last_verified: 2026-09-07
parts_needed:
  - part: chute-core
    qty: 1
  - part: hsi-m3
    qty: 18
---

The chute is what steers a part into the right bin. Build one per layer, N for an N-layer machine. The [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}) doesn't add any extra chutes of its own, it's a mounting stage the bottommost chute sits on, bridged to it by a [layer connector]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}).

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-chute-core-built-w1600-6d9c4c0c0ac6.jpg" alt="A built chute core standing on the bench: the printed core with the door module and its bearing covers on one side, the MG995 servo in its bracket above, and the funnel brackets projecting from the left">
  <figcaption>What this page builds towards: a core with its sub-assemblies on it. The door module, its servo bracket, the funnel brackets and the layer connectors are all fitted here. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

The heat inserts are in the parts list above. The screws that hold the four sub-assemblies on are on their own pages, listed where they are driven.

{% include fastener-legend.html %}

One chute is the chute core plus four things that bolt onto it:

- **Door module**, one per chute: the door, the bearing assembly, the servo adapter and the servo in its bracket, built as a unit. See [Door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}).
- **Layer adapter board**, one per chute. See [Layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}).
- **Funnel bracket (left)** and **Funnel bracket (right)**, one of each. See [Funnel brackets]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }}).
- **Layer connector A** and **Layer connector B**, one of each. See [Layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}).

Every screw that fastens one of them to the core lands in one of the core's own M3 heat inserts. Nothing on the chute taps into bare plastic.

{% include step.html n="1" title="Preparation" %}

Press the heat inserts into the chute core before you mount anything else onto it. Once the door module and the funnel brackets are on, several of the insert positions are hard to reach with an iron. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Chute core:</strong> 18 × M3, which is every insert on this page: 6 for the door module (4 for its two bearing covers, 2 for the servo bracket arms), 4 for the layer connectors, 4 for the layer adapter board, and 4 for the funnel brackets. This is separate from the bearing assembly's own 10 inserts, which live in the bearing race and holders themselves.</p>
    <p>All 18 are the same pocket, Ø4.2 mm and blind, 5.7 mm deep, split <strong>8 + 6 + 4</strong> across three faces. The photos below are of a printed core with the inserts already pressed in, one face at a time, so what you are counting is brass rather than empty pockets.</p>
  </div>
  <div class="prep-item-figure prep-item-figure-split">
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-chute-core-inserts-side-8-w1600-9c2931ac6bab.jpg" alt="One long side of a printed chute core, brass heat inserts pressed into all eight pockets on that face">
      <figcaption>One long side: 8. Two of them sit together beside the cut-out at the top, one more is on its own in the small square pocket in the middle of the face. <cite>Photo: BrickCycleAlice.</cite></figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-chute-core-inserts-side-6-w1600-0d620740ad93.jpg" alt="The other long side of the same chute core, with brass heat inserts in its six pockets and the two round tube openings across the middle of the face">
      <figcaption>The other long side: 6. The same face mirrored, without the square-pocket insert or the second one beside the cut-out. <cite>Photo: BrickCycleAlice.</cite></figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-chute-core-inserts-rear-w1600-1e4ceeaf46ea.jpg" alt="The rear panel of the chute core seen from above, four brass heat inserts in a square, with the curved channel of the core beside it">
      <figcaption>Rear face: the last 4, in a square on the panel at the top end. <cite>Photo: BrickCycleAlice.</cite></figcaption>
    </figure>
  </div>
</div>

{% include step.html n="2" title="Bolt the four sub-assemblies on" %}

Fit them in this order, each on its own page, and each with its own screws in its own parts list:

- **[Door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }})**, bolted on as a unit
- **[Layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }})**
- **[Funnel brackets]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }})**, left and right
- **[Layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }})** A and B

Every insert you pressed in at step 1 takes a screw from one of those four pages. That is why the inserts are listed here and the screws are not.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-chute-core-built-w1600-6d9c4c0c0ac6.jpg" alt="A built chute core standing on the bench: the printed core with the door module and its bearing covers on one side, the MG995 servo in its bracket above, and the funnel brackets projecting from the left">
  <figcaption>A core with the door module, its servo bracket, the funnel brackets and the layer connectors on, the connectors being the small blocks along the top. The layer adapter board is the only one of the four not in this shot. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

The chute is complete when all four are on. Repeat for every layer.
