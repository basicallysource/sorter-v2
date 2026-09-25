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
contributors: [alex, brickcyclealice, barthel]
last_verified: 2026-09-07
---

<figure class="figure-float-right">
  <a href="https://assets.basically.website/sorter-docs/assembly-chute-stack-in-frame-full-7d6494495a4b.png" target="_blank" rel="noopener">
    <img src="https://assets.basically.website/sorter-docs/assembly-chute-stack-in-frame-w1600-26cf1259d46f.jpg" alt="Render of four stacked chutes, each with its door module and funnel, shown solid against a ghosted outline of the frame and bins around them">
  </a>
  <figcaption><cite>Rendered from the CAD assembly, not from a build.</cite></figcaption>
</figure>

The chute is one per layer. Build the core first, since everything else bolts into its heat inserts.

The whole chute stack rotates as one unit, on the [top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }})'s Lazy Susan, driven by the stepper motor and gear train described there. The bins themselves don't move; each chute's door opens for a moment once it's rotated into position over the correct bin, dropping the part in. See [Door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}) and [Layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}) for how that opening is driven and timed.

<ol class="numbered-steps">
  <li><strong><a href="{{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}">Chute core</a></strong>. The printed body everything else mounts to, and the 18 heat inserts that hold it all together.</li>
  <li><strong><a href="{{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}">Door module</a></strong>. The door itself, the bearing assembly it swings on, the servo adapter, and the MG995 servo that drives it. Built as a unit, then bolted on.</li>
  <li><strong><a href="{{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}">Layer adapter board</a></strong>. The board that drives the servo.</li>
  <li><strong><a href="{{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }}">Funnel brackets</a></strong>. The two brackets that hang off the core, and the funnel that snaps into them. You choose one of two funnel sizes for each layer, which sets that layer's funnel and its bin set together, so make the choice before printing either.</li>
  <li><strong><a href="{{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}">Layer connectors</a></strong>. The pair that joins this layer's chute to the one below.</li>
</ol>

## Installing the chutes in the machine

**Do not add the chutes while you build the layers.** Build the whole frame first, then add the chutes afterward, one at a time, without their funnels.

<div class="clear-float"></div>

{% include step.html n="1" title="Build the whole frame first" %}

The layers and the top interface go together into a standing frame before any chute goes in, on [Stacking the layers]({{ '/hardware/assembly/distribution/stacking-the-layers/' | relative_url }}). Finish that first and come back here.

{% include step.html n="2" title="Add the chutes one at a time" %}

Once the frame is finished, add the chutes one at a time, in layer order. Each chute goes in as a complete unit, the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}) with its own parts already attached. The [layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}) join each chute to the one below it, so working through the layers in order matters more than which direction you start from.

Join each chute's 30 cm ribbon to the layer below as you go, at the same point the layer connectors do. Plug the end at the board in before you slot the chute into the frame, because that socket is hard to reach afterwards; see [Layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}) for which socket is which.

{% include step.html n="3" title="Fit the funnels last" %}

Once every chute is in the machine, hang each layer's funnel on the brackets already fitted to its core. It is the same snap fit described on [Funnel brackets]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }}), done in place instead of on the bench.

{% include step.html n="4" title="Bottom Lazy Susan, then the feeder" %}

The [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}) is the Lazy Susan the bottom of the chute stack sits on, so the chutes have to be in first. It is the last thing fitted in distribution. The [feeder]({{ '/hardware/assembly/feeder/' | relative_url }}) goes on after that.

## The finished result

<div class="img-placeholder">Photo of a standing frame with the top interface on and a chute in every layer, no bins in it, so the chute stack is visible.</div>
