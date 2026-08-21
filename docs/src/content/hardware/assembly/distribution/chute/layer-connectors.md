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
warning: >-
  **AI-generated first draft.** Written from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=layer-connector), not
  from an actual build. No step here has been checked against a machine. Correct it as you
  build.
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

- **How many:** 1 of each per distribution layer, plus 1 of each for the [top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}) and 1 of each for the [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}).
- **Screws:** 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} per connector, 4 for the pair. They come out of the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }})'s set of 8, they are not extra.
- Both connectors go into the chute core's M3 heat inserts.

{% include step.html n="1" title="Fit the connectors to the chute core" %}

Both connectors fasten to the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}), into its M3 heat inserts.

Each connector takes 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws through the flat strap between its two end blocks.

**Why 8 mm and not 12.** Measured off the published STLs. The strap is **3.78 mm** thick at the screw: 1.91 mm of Ø3.40 mm clearance bore, then a 90° countersink opening out to Ø7.15 mm on the outer face. Every M3 pocket in the chute core is a **blind Ø4.20 × 5.70 mm** hole for a {% include fastener.html size="M3" variant="heat-insert" %} and has solid plastic behind it, no relief hole. So an 8 mm screw reaches 4.22 mm into the insert and stops 1.5 mm short of the bottom, while a 12 mm screw would need 8.22 mm of depth and would bottom out before the head ever seated.

<div class="img-placeholder">Image coming</div>

{% include step.html n="2" title="Check the alignment against the layer below" %}

Build the layers up first and check that A on one layer lines up with B on the layer below before tightening. Nothing here is adjustable once the tower is stacked.
