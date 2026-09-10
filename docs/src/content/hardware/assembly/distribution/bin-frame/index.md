---
layout: default
title: Bin frame
type: landing
section: hardware
slug: assembly-bin-frame
kicker: Distribution — Bin frame
lede: The layers of bins, each built flat and on its own. Layer count is N (however many bin layers your machine has, not the total number of bins); build in this order.
permalink: /hardware/assembly/distribution/bin-frame/
og_image: https://assets.basically.website/sorter-docs/assembly-hex-frame-finished-top-down-w1600-a62a42d595ca.jpg
author: spencer
---

The bin frame is the stack of hexagonal layers that makes up the body of the machine: each layer carries one chute-and-bin pair that catches pieces routed to it as they come down from distribution above. The bottom interface hangs underneath the bottom layer, and the stack is capped by [Top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}).

Every bin layer is the same layer. The lowest one differs only at floor level, where a longer extrusion carries on down to a caster instead of stopping, so an N-layer machine is **N−1 regular layers and 1 bottom layer**. Each is built flat, on its own, and they are joined into the tower afterwards on [Stacking the layers]({{ '/hardware/assembly/distribution/stacking-the-layers/' | relative_url }}).

<ol class="numbered-steps">
  <li><strong><a href="{{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}">Build the hex frame</a></strong>. The shared hexagonal ring. Build N+1 of these first: one per planned layer, plus one for the top interface. The bottom interface does not need one.</li>
  <li><strong><a href="{{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}">Regular layers</a></strong>. Build N−1 of these, one per bin layer except the lowest.</li>
  <li><strong><a href="{{ '/hardware/assembly/distribution/bin-frame/bottom-layer/' | relative_url }}">Bottom layer</a></strong>. The remaining layer, on the foot extensions the casters mount to. Build one.</li>
  <li><strong><a href="{{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}">Bottom interface</a></strong>. The Lazy Susan stage. Build it whenever you like, but it goes on <strong>after the chutes are in</strong>, because its bearing carries the bottom of the chute stack.</li>
  <li><strong><a href="{{ '/hardware/assembly/distribution/bin-frame/bin-retainers/' | relative_url }}">Bin retainers</a></strong>. The same twelve rails on every bin layer. One pass per bin layer, the bottom one included.</li>
  <li><strong><a href="{{ '/hardware/assembly/distribution/top-interface/' | relative_url }}">Top interface</a></strong>. Outside this section, but takes one of the hex frames from step 1 and caps the stack.</li>
</ol>

Once every layer is built, [Stacking the layers]({{ '/hardware/assembly/distribution/stacking-the-layers/' | relative_url }}) joins them into the tower.

## The finished result

Each page ends in one of these.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-hex-frame-finished-top-down-w1600-a62a42d595ca.jpg" alt="A finished hex frame from above: six spokes and their printed crossbeams forming the inner ring inside the aluminum outer hexagon, with a printed corner bracket at each of the six vertices">
    <figcaption><a href="{{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}">Hex frame</a>. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-finished-square-full-779529c4b5f5.png" alt="A finished regular layer from above: the hexagon of extrusion with its spokes and crossbeams, and a vertical support capped by an External bracket — bottom vertical standing at each of the six corners">
    <figcaption><a href="{{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}">Regular layer</a>. <cite>Photo: zed0.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-bottom-layer-corner-bracket-on-d-w1600-67bd9444f306.jpg" alt="One corner of the bottom layer seen close up from above: the External bracket — bottom vertical standing on the collar with the end of piece D recessed in its square socket, the foot cover below the frame, and the caster under that">
    <figcaption><a href="{{ '/hardware/assembly/distribution/bin-frame/bottom-layer/' | relative_url }}">Bottom layer</a>, one corner. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-parts/bottom-interface-step4-hex-frame-overview-full-bab24577ff64.jpg" alt="Top-down view of the assembled hexagonal layer frame with three Lazy Susan extrusion mounts fitted at alternating spokes">
    <figcaption><a href="{{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}">Bottom interface</a>. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-bin-retainers-installed-w1600-31bf32089e71.png" alt="Bin retainers fastened to the outer faces of the hexagon frame, a pair either side of the joint between two A extrusions">
    <figcaption><a href="{{ '/hardware/assembly/distribution/bin-frame/bin-retainers/' | relative_url }}">Bin retainers</a>. <cite>Photo: zed0.</cite></figcaption>
  </figure>
</div>
