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
  - part: scr-m3-12-cs
    qty: 6
  - part: scr-m3-8-cs
    qty: 8
---

The chute is what steers a part into the right bin. Build one per layer, plus two for the [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}).

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

One chute is the chute core plus four things that bolt onto it:

- **Door module**, one per chute: the door, the bearing assembly, the servo adapter and the servo in its bracket, built as a unit. See [Door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}).
- **Funnel bracket (left)** and **Funnel bracket (right)**, one of each. See [Funnel]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }}).
- **Layer connector A** and **Layer connector B**, one of each. See [Layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}).
- **Layer adapter board**, one per chute. See [PCB]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}).

Every screw on this page lands in one of the chute core's own M3 heat inserts. Nothing here taps into bare plastic.

{% include step.html n="1" title="Preparation" %}

Press the heat inserts into the chute core before anything is mounted to it. Once the funnel brackets and the door module are on, several of the insert positions are hard to reach with an iron. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Chute core:</strong> 18 × M3, which is every insert on this page. 2 for the servo bracket arms, 4 for the layer adapter board, and the rest for the funnel brackets, the bearing assembly and the layer connectors.</p>
    <p>All 18 are the same pocket, Ø4.2 mm and blind, 5.7 mm deep, split <strong>8 + 6 + 4</strong> across three faces. The views are rendered from the chute core STL, turned slightly off each face so the pockets shade as holes, and circle only the pockets visible in that view.</p>
  </div>
  <div class="prep-item-figure prep-item-figure-split">
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/chute-core-inserts-v3-side-8-full-9f0f3b659b63.png" alt="Render of one long side of the chute core at a slight angle, with eight heat-insert pockets circled in red">
      <figcaption>One long side: 8. The round cut-out near the end is the giveaway, this side has two pockets together beside it and one on its own in the middle of the face.</figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/chute-core-inserts-v3-side-6-full-c4074e29338f.png" alt="Render of the other long side of the chute core at a slight angle, with six heat-insert pockets circled in red">
      <figcaption>The other long side: 6. The same face mirrored, without those two.</figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/chute-core-inserts-v3-rear-full-ad4c2cc7869c.png" alt="Close render of the rear end of the chute core at a slight angle, with the four heat-insert pockets on the rear panel circled in red">
      <figcaption>Rear face: the last 4, all on the panel at the top end. Shown closer in than the other two.</figcaption>
    </figure>
  </div>
</div>

{% include step.html n="2" title="Bolt the four sub-assemblies on" %}

Fit them in this order: the funnel brackets, the door module, the layer connectors, then the layer adapter board. Each has its own page for the procedure. What follows is the one thing those pages do not repeat, which screw goes into which insert, worked out from the STLs by comparing each mating part's wall thickness at its screw hole against the core's blind 5.70 mm pockets.

- **[Funnel brackets]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }})**, left and right: 4 × {% include fastener.html size="M3" variant="countersunk" length="12" %}, 2 per bracket. The bracket is 8.16 mm thick at the screw, so a 12 mm screw reaches 3.84 mm into the insert and an 8 mm one would not reach it at all.
- **[Door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }})**, bolted on as a unit: 4 × {% include fastener.html size="M3" variant="countersunk" length="8" %} through the two bearing covers, 2 per cover into 5.00 mm of wall, plus 2 × {% include fastener.html size="M3" variant="countersunk" length="12" %} for the servo bracket arms.
- **[Layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }})** A and B: 4 × {% include fastener.html size="M3" variant="countersunk" length="8" %}, 2 per connector. The strap is 3.78 mm thick, so an 8 mm screw reaches 4.22 mm in and stops 1.5 mm short of the pocket bottom, while a 12 mm screw would bottom out before the head seated.
- **[Layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }})**: 4 × {% include fastener.html size="M3" variant="button" length="6" %} on the four inserts in the rear face, the only button heads on the chute. They are in that page's parts list, not this one.

That accounts for all 14 countersunk screws in the list above, 6 twelves and 8 eights. The servo-bracket row is the only one nothing published confirms: no STL sits on those two inserts, so 12 mm is by elimination from the other three rather than measured.

<div class="img-placeholder">Image coming</div>

The chute is complete when all four are on. Repeat for every layer.
