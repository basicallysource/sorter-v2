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
contributors: [barthel, zed0]
og_image: https://assets.basically.website/sorter-docs/chute-v3-assembled-window-full-405b3627325a.png
tools_needed: [Soldering iron or heat-set insert press]
parts_needed:
  - part: chute-core
    qty: 1
  - part: hsi-m3
    qty: 21
warning: >-
  **AI-generated first draft.** Written from the 3D parts of the inverted chute, not from an actual
  build. The insert count and positions on this page are counted off the chute core's own geometry:
  21 pockets, three more than the earlier core, so the parts calculator's count of 18 is out of date
  until the catalog follows. The order of the steps is not checked against a machine.
---

The chute is what steers a part into the right bin. Build one per layer, N for an N-layer machine. The [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}) doesn't add any extra chutes of its own, it's a mounting stage the bottommost chute sits on, bridged to it by a [layer connector]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}).

The core is an upright box, open at the top, with a large opening in one side. The opening is where the door lets a part out; the funnel hangs off it. In this page that is the **opening side**. The side opposite it is the **rear**, and the two long walls are the **servo side** and the **plain side**, after what bolts to them.

The heat inserts are in the parts list above. The screws that hold the sub-assemblies on are on their own pages, listed where they are driven.

{% include fastener-legend.html %}

One chute is the chute core plus four things that bolt onto it:

- **Door module**, one per chute: the door, the bearing assembly, the servo adapter and the servo in its bracket, built as a unit. See [Door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}).
- **Layer adapter board**, one per chute. See [Layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}).
- **Funnel bracket (left)** and **Funnel bracket (right)**, one of each, and the funnel they carry. See [Funnel brackets]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }}).
- **Layer connector A** and **Layer connector B**, one of each. See [Layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}).

{% include step.html n="1" title="Preparation" %}

Press the heat inserts into the chute core before you mount anything else onto it. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Chute core:</strong> 21 × M3, which is every insert on this page. They are all the same insert, in six groups on four faces. Each ringed pocket in the renders below has a letter, and the letters mean the same in every picture:</p>
    <ul>
      <li><strong>A, 4 inserts</strong>: the funnel brackets, two on each long wall.</li>
      <li><strong>B, 4 inserts</strong>: the two bearing covers, two on each long wall.</li>
      <li><strong>C, 4 inserts</strong>: the layer connectors, two on each long wall.</li>
      <li><strong>D, 3 inserts</strong>: the servo bracket, all on the servo side: two for the side arm, one for the lower arm.</li>
      <li><strong>E, 2 inserts</strong>: the bearing race, low on the opening side.</li>
      <li><strong>F, 4 inserts</strong>: the layer adapter board, in a square on the rear.</li>
    </ul>
    <p>The servo side takes 9 (A, B, C and D), the plain side 6 (A, B and C), the rear 4 and the opening side 2. This is separate from the bearing assembly's own 10 inserts and the servo bracket's 6, which live in those parts.</p>
  </div>
</div>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-core-pockets-plus-y-full-659b8037b993.png" alt="Render of the servo side wall of the chute core with nine pockets ringed in red and lettered: two A beside the bracket pad in the middle, two B near the round bearing notch, two C on the connector pads, two D on a small pad and one D low on the wall">
    <figcaption>The servo side: 9. A, B, C and D. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-core-pockets-minus-y-full-f530a6859a83.png" alt="Render of the plain side wall of the chute core with six pockets ringed in red and lettered: two A, two B and two C">
    <figcaption>The plain side: 6. A, B and C, in the same places as on the other wall, without the three D pockets. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-core-pockets-rear-full-02f30fdb074c.png" alt="Render of the rear wall of the chute core with four pockets ringed in red, each lettered F, in a square">
    <figcaption>The rear: the last 4, the F pockets, in a square on the wall. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-core-pockets-race-face-full-8229aefed6ad.png" alt="Render of the opening side of the chute core seen through the top, with two pockets ringed in red and lettered E on the low wall under the opening">
    <figcaption>The opening side: 2, the E pockets, on the low wall under the opening. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

{% include step.html n="2" title="Bolt the four sub-assemblies on" %}

Fit them in this order, each on its own page, and each with its own screws in its own parts list:

- **[Door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }})**, bolted on as a unit
- **[Layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }})**
- **[Funnel brackets]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }})**, left and right
- **[Layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }})** A and B

Every insert you pressed in at step 1 takes a screw from one of those four pages. That is why the inserts are listed here and the screws are not.

## The finished result

The chute is complete when all four are on. Repeat for every layer.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-assembled-window-full-405b3627325a.png" alt="Render of a finished chute seen from the opening side: the grey core upright, the door module low on it with its round bearing cover, the green funnel bracket running down to the tan funnel, and the yellow layer connectors on top">
  <figcaption>A core with the door module, the funnel brackets and funnel and the layer connectors on. The layer adapter board is not modelled and is not in this picture. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

The [Chute]({{ '/hardware/assembly/distribution/chute/' | relative_url }}) page contains the instructions for the whole chute, and is where you should return once you're done here.
