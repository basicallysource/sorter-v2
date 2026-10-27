---
layout: default
title: Chute core
type: how-to
section: hardware
slug: assembly-chute-core
kicker: Chute — Chute core
lede: The printed core of the chute, with its heat inserts. Build one per layer.
permalink: /hardware/assembly/distribution/chute/chute-core/
author: spencer
contributors: [barthel, zed0]
og_image: https://assets.basically.website/sorter-docs/chute-v3-core-with-inserts-opening-side-full-1961b4bfcb14.png
tools_needed: [Soldering iron or heat-set insert press]
parts_needed:
  - part: chute-core
    qty: 1
  - part: hsi-m3
    qty: 21
warning: >-
  **AI-generated first draft.** Written from the 3D parts of the inverted chute, not from an actual
  build. The insert positions are read off the core itself.
---

The chute is what steers a part into the right bin. Build one per layer, N for an N-layer machine. The [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}) doesn't add any extra chutes of its own, it's a mounting stage the bottommost chute sits on, bridged to it by a [layer connector]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}).

The core is an upright box, open at the top, with a large opening in one side. The opening is where the door lets a part out; the funnel hangs off it. In this page that is the **opening side**. The side opposite it is the **rear**. Of the two long walls, the **servo side** is the one that takes the servo bracket and has nine inserts, and the **plain side** is the one with six.

The heat inserts are in the parts list above. The screws that hold the sub-assemblies on are on their own pages, listed where they are driven.

{% include step.html n="1" title="Preparation" %}

Press all the heat inserts into the chute core before anything is mounted on it. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

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
  <div class="prep-item-figure prep-item-figure-split">
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-core-pockets-plus-y-full-7570976946a6.png" alt="Render of the servo side wall of the chute core with nine pockets ringed in red and lettered: two A beside the bracket pad in the middle, two B near the round bearing notch, two C on the connector pads, two D on a small pad and one D low on the wall">
      <figcaption>The servo side: 9. A, B, C and D. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-core-pockets-minus-y-full-e874612f7034.png" alt="Render of the plain side wall of the chute core with six pockets ringed in red and lettered: two A, two B and two C">
      <figcaption>The plain side: 6. A, B and C, in the same places as on the other wall, without the three D pockets. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-core-pockets-rear-full-1ca6422e7957.png" alt="Render of the rear wall of the chute core with four pockets ringed in red, each lettered F, in a square">
      <figcaption>The rear: the last 4, the F pockets, in a square on the wall. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-core-pockets-race-face-full-325406e2ba66.png" alt="Render of the opening side of the chute core seen through the top, with two pockets ringed in red and lettered E on the low wall under the opening">
      <figcaption>The opening side: 2, the E pockets, on the low wall under the opening. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
    </figure>
  </div>
</div>

## The finished result

The chute core is finished when all 21 heat inserts are pressed in. Nothing is bolted to it on this page; the parts that go on it are built on their own pages, and each of those starts from this finished core.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-core-with-inserts-servo-side-full-f298d942db50.png" alt="Render of the servo side wall of the chute core with brass heat inserts pressed into all nine pockets on it">
    <figcaption>The servo side: 9 inserts in. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-core-with-inserts-plain-side-full-a78d9ea26a29.png" alt="Render of the plain side wall of the chute core with brass heat inserts pressed into all six pockets on it">
    <figcaption>The plain side: 6 inserts in. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-core-with-inserts-rear-full-4810c88f889e.png" alt="Render of the rear wall of the chute core with a brass heat insert in each of the four pockets in a square">
    <figcaption>The rear: 4 inserts in. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-core-with-inserts-opening-side-full-1961b4bfcb14.png" alt="Render of the opening side of the chute core seen from above, with a brass heat insert in each of the two pockets on the low wall under the opening">
    <figcaption>The opening side: 2 inserts in. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

What goes on the core, one page each:

- **[Door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }})**: the B, D and E inserts
- **[Layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }})**: the F inserts
- **[Funnel brackets]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }})**: the A inserts
- **[Layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }})**: the C inserts

The [Chute]({{ '/hardware/assembly/distribution/chute/' | relative_url }}) page contains the instructions for the whole chute, and is where you should return once you're done here.
