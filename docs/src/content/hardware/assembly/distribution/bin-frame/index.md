---
layout: default
title: Bin frame
type: landing
section: hardware
slug: assembly-bin-frame
kicker: Distribution — Bin frame
lede: The layers of bins, each built flat and on its own. Layer count is N (however many bin layers your machine has, not the total number of bins); build in this order.
permalink: /hardware/assembly/distribution/bin-frame/
author: spencer
---

The bin frame is the stack of hexagonal layers that makes up the body of the machine: each layer carries one chute-and-bin pair that catches pieces routed to it as they come down from distribution above. The bottom interface hangs underneath the bottom layer, and the stack is capped by [Top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}).

Every bin layer is the same layer. The lowest one differs only at floor level, where a longer extrusion carries on down to a caster instead of stopping, so an N-layer machine is **N−1 regular layers and 1 bottom layer**. Each is built flat, on its own, and they are joined into the tower afterwards on [Stacking the layers]({{ '/hardware/assembly/distribution/stacking-the-layers/' | relative_url }}).

<ol class="numbered-steps">
  <li><strong><a href="{{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}">Build the hex frame</a></strong>. The shared hexagonal ring. Build N+1 of these first: one per planned layer, plus one for the top interface. The bottom interface does not need one.</li>
  <li><strong><a href="{{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}">Regular layers</a></strong>. Build N−1 of these, one per bin layer except the lowest.</li>
  <li><strong><a href="{{ '/hardware/assembly/distribution/bin-frame/bottom-layer/' | relative_url }}">Bottom layer</a></strong>. The remaining layer, on the foot extensions the casters mount to. Build one.</li>
  <li><strong><a href="{{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}">Bottom interface</a></strong>. The Lazy Susan stage. It bolts up under the bottom layer's spokes once the machine is standing, which is why it comes last rather than first.</li>
  <li><strong><a href="{{ '/hardware/assembly/distribution/bin-frame/bin-retainers/' | relative_url }}">Bin retainers</a></strong>. The same twelve rails on every bin layer. Steps 2 and 3 both send you here, once per layer.</li>
  <li><strong><a href="{{ '/hardware/assembly/distribution/top-interface/' | relative_url }}">Top interface</a></strong>. Outside this section, but takes one of the hex frames from step 1 and caps the stack.</li>
</ol>

Once every layer is built, <a href="{{ '/hardware/assembly/distribution/stacking-the-layers/' | relative_url }}">Stacking the layers</a> joins them into the tower.
