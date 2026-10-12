---
layout: default
title: Chute
type: landing
section: hardware
slug: assembly-chute
kicker: Distribution — Chute
lede: The rotating chute that aims parts at the correct bin.
permalink: /hardware/assembly/distribution/chute/
author: spencer
contributors: [alex, brickcyclealice, barthel, zed0]
og_image: https://assets.basically.website/sorter-docs/chute-v3-stack-of-four-cad-full-fd5936d88689.png
warning: >-
  **AI-generated first draft.** Written from the 3D parts of the inverted chute, not from an actual
  build, so nobody has built this chute from these pages yet. Every picture here is a render.
---

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-assembled-window-full-e2ca74bfad03.png" alt="Render of one assembled chute seen from the opening side: the grey core standing upright, the yellow layer connectors on its walls near the top, the green funnel brackets running down to a tan funnel, and the door module low on the core">
    <figcaption>One finished chute with the third-size funnel, seen from the opening side. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-assembled-servo-side-full-49d037fa1511.png" alt="Render of the same assembled chute seen from the servo side: the MG995 in its blue bracket on the side of the core next to the bearing cover, the green funnel bracket above it running to the tan funnel, and the yellow layer connectors on the core">
    <figcaption>The same chute from the servo side. The servo itself has no model, so its bracket shows empty. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

The chute is one per layer. Build the core first, since everything else bolts into its heat inserts.

The whole chute stack rotates as one unit, on the [top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }})'s Lazy Susan, driven by the stepper motor and gear train described there. The bins themselves don't move. Each chute has a flat door that hinges along the bottom edge of an opening in the side of its core, with the bearing race as the sill under it. Once the stack has rotated a chute's opening over the correct bin, the door lets the part out and the funnel guides it down. See [Door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}) and [Layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}) for how that opening is driven and timed.

Build the chute in this order. Each page after the first starts from the finished core.

<ol class="numbered-steps">
  <li><strong><a href="{{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}">Chute core</a></strong>. The printed body everything else mounts to, and the 21 heat inserts that hold it all together.</li>
  <li><strong><a href="{{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}">Door module</a></strong>. The door, the bearing assembly it swings on (the race, two holders, two covers and two bearings), the servo adapter, and the MG995 servo that drives it in its bracket. Built as a unit, then bolted on.</li>
  <li><strong><a href="{{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}">Layer adapter board</a></strong>. The board that drives the servo.</li>
  <li><strong><a href="{{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }}">Funnel brackets</a></strong>. The two brackets that bolt to the sides of the core, and the funnel that slides into them. You choose one of two funnel sizes for each layer, which sets that layer's funnel and its bin set together, so make the choice before printing either.</li>
  <li><strong><a href="{{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}">Layer connectors</a></strong>. The pair that ties this layer's chute to its neighbour in the stack.</li>
</ol>

## Installing the chutes in the machine

**Do not add the chutes while you build the layers.** Build the whole frame first, then add the chutes afterward, one at a time, without their funnels.

<div class="clear-float"></div>

{% include step.html n="1" title="Build the whole frame first" %}

The layers and the top interface go together into a standing frame before any chute goes in, on [Stacking the layers]({{ '/hardware/assembly/distribution/stacking-the-layers/' | relative_url }}). Finish that first and come back here.

{% include step.html n="2" title="Add the chutes one at a time" %}

Once the frame is finished, add the chutes one at a time, in layer order. Each chute goes in as a complete unit, the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}) with its own parts already attached. The [layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}) tie each chute to the one next to it in the stack, so working through the layers in order matters more than which direction you start from.

Each chute's 300 mm (12 in) ribbon (`RIB2`) is joined to the chute below at the same time, so do it as each one goes in. Its other end is already in the board, plugged in on the bench because that socket is hard to reach afterwards; see [Layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}) for which socket is which.

{% include step.html n="3" title="Fit the funnels last" %}

Once every chute is in the machine, fit each layer's funnel to the brackets already on its core. It is the same slide-in joint described on [Funnel brackets]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }}), done in place instead of on the bench.

{% include step.html n="4" title="Bottom Lazy Susan, then the feeder" %}

The [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}) is the Lazy Susan the bottom of the chute stack sits on, so the chutes have to be in first. It is the last thing fitted in distribution. The [feeder]({{ '/hardware/assembly/feeder/' | relative_url }}) goes on after that.

## The finished result

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-stack-of-four-cad-full-fd5936d88689.png" alt="Side view of four chutes stacked in the CAD assembly: the layer adapter boards on the left with their black ribbon cables looping from one board to the next, the door module with its round bearing cover and the dark funnel brackets in the middle of each layer, and a funnel running down and out to the right from each">
  <figcaption>Four chutes stacked, from the CAD assembly: the layer adapter boards and their ribbon loops on the left, the door modules and funnel brackets in the middle, a funnel to the right of each layer. <cite>Rendered from the part geometry, not from a build. Render: zed0.</cite></figcaption>
</figure>

The chute is finished when every part above is on the core, as in the pictures at the top of the page. Repeat for every layer.
