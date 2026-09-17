---
layout: default
title: Layer connectors
type: how-to
section: hardware
slug: assembly-layer-connectors
kicker: Chute — Layer connectors
lede: The connectors that chain layers together.
permalink: /hardware/assembly/distribution/chute/layer-connectors/
author: spencer
contributors: [barthel]
last_verified: 2026-09-07
parts_needed:
  - part: layer-connector-1
    qty: 1
  - part: layer-connector-2
    qty: 1
  - part: scr-m3-8-cs
    qty: 4
---

The layer connectors are a pair of printed parts, Layer connector A and Layer connector B, that join one layer's chute to the next one down so parts pass from chute to chute without a gap.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

- **How many:** 1 of each per distribution layer, plus 1 of each for the [top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}) and 1 of each for the [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}). For an N-layer machine, that's N + 2 pairs total.
- **Screws:** 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} per connector, 4 for the pair, in the list above. They go into the core's inserts rather than into anything on this page.
- Both connectors go into the chute core's M3 heat inserts.

{% include step.html n="1" title="Fit the connectors to the chute core" %}

Both connectors fasten to the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}), into its M3 heat inserts.

**Fit one pair to the top of each chute core, and one pair to the top of the bottom interface.** Nothing goes on the underside of anything. As the tower goes up, the part above slots down onto the pair already standing on the part below.

Each connector has 2 holes in its strap, one at each end, and takes 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws. **Only the lower one goes in now**, into the core's own insert; the upper hole stays empty until the part above slots on and is screwed down into it. Don't fully tighten either: step 2 covers checking the alignment first.

The strap is countersunk 90° on its outer face, so the head sits flush. It is 3.78 mm thick, so an 8 mm screw reaches 4.22 mm into the core's blind 5.70 mm insert and stops 1.5 mm short of the bottom, while a 12 mm one would bottom out before the head seated.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-core-layer-connectors-full-2092b04f9864.png" alt="Render of one long side of the chute core with the two heat inserts a layer connector screws into circled in red">
  <figcaption>The two inserts one layer connector screws into, one near each end of a long side of the chute core. The other long side carries the mirror pair for the second connector. <cite>Render: Balloon.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-layer-connector-on-chute-core-top-w1600-5d5d958ba719.jpg" alt="A light grey layer connector standing proud of the top edge of a chute core, screwed to the core through the lower of its two countersunk holes with the upper hole empty, other sub-assemblies on the core around it">
  <figcaption>A connector standing on the top of a chute core. The lower screw holds it to the core; the empty hole above it is what the part above screws down into. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="2" title="Check the alignment against the layer below" %}

Build the layers up first and check that A on one layer sits flush against B on the layer below, with no visible gap or twist between the two straps, before tightening either one down. Nothing here is adjustable once the tower is stacked.
