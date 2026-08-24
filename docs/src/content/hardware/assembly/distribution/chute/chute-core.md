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
  - part: funnel-bracket-left
    qty: 1
  - part: funnel-bracket-right
    qty: 1
  - part: layer-connector-1
    qty: 1
  - part: layer-connector-2
    qty: 1
  - part: layer-adapter-board-basically
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
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="URL_REAR" alt="Close render of the rear end of the chute core at a slight angle, with the four heat-insert pockets on the rear panel circled in red">
    <figcaption>Rear face: 4 pockets, seen close in.</figcaption>
  </figure>
</div>

Every one of the 18 is the same pocket, Ø4.2 mm and blind, 5.7 mm deep, so there is nothing to tell apart while you press them in. They sit on three faces of the core, **8 + 6 + 4**. Each view below is rendered from the chute core STL, turned about 18° off the face so the pockets shade as holes rather than disappearing into the plate, and circles only the pockets that are actually visible in that view.

<div class="img-row">
  <figure>
    <img src="URL_SIDE8" alt="Render of one long side of the chute core at a slight angle, with eight heat-insert pockets circled in red">
    <figcaption><strong>One long side, 8 pockets.</strong> The round cut-out near the end is the giveaway: this side has two pockets together beside it, and one more on its own in the middle of the face.</figcaption>
  </figure>
</div>

<div class="img-row">
  <figure>
    <img src="URL_SIDE6" alt="Render of the other long side of the chute core at a slight angle, with six heat-insert pockets circled in red">
    <figcaption><strong>The other long side, 6 pockets.</strong> The same face mirrored, without those two: one pocket either side of the round cut-out, and nothing in the middle.</figcaption>
  </figure>
</div>

{% include step.html n="2" title="Fit the funnel brackets" %}

Fit the Funnel bracket (left) and the Funnel bracket (right) to the chute core. Together with the door module and the layer connectors these use the chute's 6 {% include fastener.html size="M3" variant="countersunk" length="12" %} and 8 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws, all into the core's inserts.

The split across those 14, worked out from the STLs by comparing each mating part's wall thickness at its screw hole against the core's blind 5.70 mm insert pockets:

- **Funnel brackets:** 4 × {% include fastener.html size="M3" variant="countersunk" length="12" %} (8.16 mm wall, so an 8 mm screw would not reach the insert at all)
- **Bearing covers:** 4 × {% include fastener.html size="M3" variant="countersunk" length="8" %} (5.00 mm wall, 2 per cover)
- **[Layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}):** 4 × {% include fastener.html size="M3" variant="countersunk" length="8" %} (3.78 mm strap, 2 per connector)
- **Servo bracket arms:** the remaining 2 × {% include fastener.html size="M3" variant="countersunk" length="12" %}. No published part sits on those two inserts, so this one is by elimination rather than measured.

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Fit the door module" %}

Build the [door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}) as a unit (door, bearing assembly, servo adapter, servo in its bracket) and bolt it to the chute core. The servo bracket lands on **two** of the core's M3 inserts.

{% include step.html n="4" title="Fit the layer connectors and the PCB" %}

Attach Layer connector A and Layer connector B, then the [layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}) on its four PCB inserts.

The chute is now complete. Repeat for every layer.
