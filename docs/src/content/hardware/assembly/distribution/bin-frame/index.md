---
layout: default
title: Bin frame
type: landing
section: hardware
slug: assembly-bin-frame
kicker: Distribution — Bin frame
lede: The stacked layers of bins. Layer count is N (however many bin layers your machine has, not the total number of bins); build in this order.
permalink: /hardware/assembly/distribution/bin-frame/
author: spencer
---

The bin frame is the stack of hexagonal layers that makes up the body of the machine: each layer carries one chute-and-bin pair that catches pieces routed to it as they come down from distribution above. The stack sits on the bottom interface, which the pieces feed from below, and is capped by [Top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}). Build order runs bottom-up, since each layer's vertical extrusion locates and is fastened to the one below it.

1. **[Build the hex frame]({{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }})** — the shared hexagonal ring. Build N+1 of these first: one per planned layer, plus one each for the bottom and top interface.
2. **[Bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }})** — the base the frame builds up from.
3. **[Bottom two layers]({{ '/hardware/assembly/distribution/bin-frame/bottom-two-layers/' | relative_url }})** — the paired base layers on the long vertical extrusions.
4. **[Regular layers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }})** — build N−2 of these, one per remaining layer.
5. **[Top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }})** — outside this section, but takes one of the hex frames from step 1 and caps the stack.
