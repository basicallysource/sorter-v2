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
---

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>AI-generated first draft.</strong> Written from the machine assembly tree in the <a href="https://parts-calculator.basically.website/assembly?focus=layer-connector">parts calculator</a>, not from an actual build. No step here has been checked against a machine. Correct it as you build.</p>
</div>

The layer connectors are a pair of printed parts, **Layer connector A** and **Layer connector B**, that join one layer's chute to the next one down so parts pass from chute to chute without a gap.

**How many:** 1 of each per distribution layer, plus 1 of each for the [top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}) and 1 of each for the [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}).

{% include fastener-legend.html %}

{% include step.html n="1" title="Fit the connectors to the chute core" %}

Both connectors fasten to the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}), into its M3 heat inserts, using screws from the chute's own set of 6 {% include fastener.html size="M3" variant="countersunk" length="12" %} and 8 {% include fastener.html size="M3" variant="countersunk" length="8" %}.

The split between the two lengths is not recorded yet: <span class="fastener-todo">fastener not recorded</span>.

<div class="img-placeholder">Image coming</div>

{% include step.html n="2" title="Check the alignment against the layer below" %}

Build the layers up first and check that A on one layer lines up with B on the layer below before tightening. Nothing here is adjustable once the tower is stacked.
