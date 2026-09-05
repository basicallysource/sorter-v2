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
warning: >-
  **AI-generated first draft.** Written from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=chute), not from an
  actual build. No step here has been checked against a machine. Correct it as you build.
parts_needed:
  - part: chute-core
    qty: 1
  - part: hsi-m3
    qty: 18
---

The chute is what steers a part into the right bin. Build one per layer, N for an N-layer machine. The [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}) doesn't add any extra chutes of its own, it's a mounting stage the bottommost chute sits on, bridged to it by a [layer connector]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}).

The heat inserts are in the parts list above. The screws that hold the four sub-assemblies on are on their own pages, listed where they are driven.

{% include fastener-legend.html %}

One chute is the chute core plus four things that bolt onto it:

- **Door module**, one per chute: the door, the bearing assembly, the servo adapter and the servo in its bracket, built as a unit. See [Door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}).
- **Funnel bracket (left)** and **Funnel bracket (right)**, one of each. See [Funnel]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }}).
- **Layer connector A** and **Layer connector B**, one of each. See [Layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}).
- **Layer adapter board**, one per chute. See [Layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}).

Every screw that fastens one of them to the core lands in one of the core's own M3 heat inserts. Nothing on the chute taps into bare plastic.

{% include step.html n="1" title="Preparation" %}

Press the heat inserts into the chute core before you mount anything else onto it. Once the funnel brackets and the door module are on, several of the insert positions are hard to reach with an iron. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Chute core:</strong> 18 × M3, which is every insert on this page: 4 for the funnel brackets, 6 for the door module (4 for its two bearing covers, 2 for the servo bracket arms), 4 for the layer connectors, and 4 for the layer adapter board. This is separate from the bearing assembly's own 10 inserts, which live in the bearing race and holders themselves.</p>
    <p>All 18 are the same pocket, Ø4.2 mm and blind, 5.7 mm deep, split <strong>8 + 6 + 4</strong> across three faces. The views are rendered from the chute core STL, turned slightly off each face so the pockets shade as holes, and circle only the pockets visible in that view.</p>
  </div>
  <div class="prep-item-figure prep-item-figure-split">
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/chute-core-inserts-v3-side-8-full-9f0f3b659b63.png" alt="Render of one long side of the chute core at a slight angle, with eight heat-insert pockets circled in red">
      <figcaption>One long side: 8. The round cut-out near the end is the giveaway, this side has two pockets together beside it and one on its own in the middle of the face. <cite>Render: Balloon.</cite></figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/chute-core-inserts-v3-side-6-full-c4074e29338f.png" alt="Render of the other long side of the chute core at a slight angle, with six heat-insert pockets circled in red">
      <figcaption>The other long side: 6. The same face mirrored, without those two. <cite>Render: Balloon.</cite></figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/chute-core-inserts-v3-rear-full-ad4c2cc7869c.png" alt="Close render of the rear end of the chute core at a slight angle, with the four heat-insert pockets on the rear panel circled in red">
      <figcaption>Rear face: the last 4, all on the panel at the top end. Shown closer in than the other two. <cite>Render: Balloon.</cite></figcaption>
    </figure>
  </div>
</div>

{% include step.html n="2" title="Bolt the four sub-assemblies on" %}

Fit them in this order, each on its own page, and each with its own screws in its own parts list:

- **[Funnel brackets]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }})**, left and right
- **[Door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }})**, bolted on as a unit
- **[Layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }})** A and B
- **[Layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }})**

Every insert you pressed in at step 1 takes a screw from one of those four pages. That is why the inserts are listed here and the screws are not.

<div class="img-placeholder">Photo of a finished chute core with all four sub-assemblies bolted on: funnel brackets, door module, layer connectors and layer adapter board.</div>

The chute is complete when all four are on. Repeat for every layer.
