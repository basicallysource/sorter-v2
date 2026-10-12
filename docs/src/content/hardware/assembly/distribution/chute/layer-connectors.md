---
layout: default
title: Layer connectors
type: how-to
section: hardware
slug: assembly-layer-connectors
kicker: Chute — Layer connectors
lede: The connectors that chain layers together.
permalink: /hardware/assembly/distribution/chute/layer-connectors/
og_image: https://assets.basically.website/sorter-docs/chute-v3-connectors-seated-full-49e25b8766d3.png
author: spencer
contributors: [barthel, zed0]
tools_needed: ["Hex key, 2 mm"]
parts_needed:
  - part: layer-connector-1
    qty: 1
  - part: layer-connector-2
    qty: 1
  - part: scr-m3-8-cs
    qty: 4
warning: >-
  **AI-generated first draft.** Written from the 3D parts of the inverted chute, not from an actual
  build. The connectors do the same job as before on a new core, and the steps are carried over from
  the earlier build without being checked against the new parts.
---

The layer connectors are a pair of printed parts, Layer connector A and Layer connector B, that tie one layer's chute to the next one in the stack so parts pass from chute to chute without a gap.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

- **How many:** 1 of each per distribution layer, plus 1 of each for the [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}). For an N-layer machine, that's N + 1 pairs total. **The [top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}) carries none of its own**: it lands on the pair already standing on the topmost chute.
- **Screws:** 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} per connector, 4 for the pair, in the list above. They go into the inserts of the parts at each end of the joint, not into anything on this page.
- Both connectors go into M3 heat inserts: one screw into the part they are mounted on, one into the part that slots on above.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}">chute core</a> before you start.</strong> Press all its heat inserts in first.</p>
    <p>Which wall is which: the <strong>opening side</strong> has the big opening, the <strong>rear</strong> is opposite it, and of the two long walls the <strong>servo side</strong> is the one with nine inserts and the <strong>plain side</strong> the one with six.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-core-with-inserts-opening-side-full-1961b4bfcb14.png" alt="Render of the finished chute core, an upright box open at the top with an opening in one side and brass heat inserts in its walls">
    <figcaption>The prepared chute core, with its heat inserts in. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

{% include step.html n="1" title="Fit the connectors to the chute core" %}

Both connectors fasten to the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}), into its M3 heat inserts. Each long wall of the core has two of them on raised pads, one near the top and one near the bottom.

**Fit one pair to the top of each chute core, and one pair to the top of the bottom interface.** Nothing goes on the underside of anything. As the tower goes up, the part above slots down onto the pair already standing on the part below, and the part above takes the pair's upper holes in its own lower inserts.

Each connector has 2 holes in its strap, one at each end, and takes 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws. **Only the lower one goes in now**, into the core's upper insert on that wall; the upper hole stays empty until the part above slots on and is screwed down into it. Don't fully tighten either: step 2 covers checking the alignment first.

The strap is countersunk on its outer face, so the head sits flush. Use the 8 mm, not the 12 mm.

**Fit each connector with its flat face, the one with the two countersunk holes, facing out, away from the core.** The other side is open, with a wall along each long edge, and faces the core and fits over the raised pad the insert sits on. The two connectors are mirror images, one for each long wall: if one will not sit flat over its pad, swap them.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-connector-pockets-plus-y-full-3ac83c9fbb57.png" alt="Render of the servo side wall of the chute core with two inserts ringed in red, one near the top of the wall and one near the bottom, each on a raised pad">
    <figcaption>The servo side wall. The upper ring takes this chute's connector; the lower ring is for the connector standing on the chute below. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-connector-pockets-minus-y-full-133b717364e2.png" alt="Render of the plain side wall of the chute core with two inserts ringed in red, one near the top of the wall and one near the bottom">
    <figcaption>The plain side wall, the same two inserts. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

{% include step.html n="2" title="Check the alignment with the next chute" %}

Build the layers up first. When the next chute is on, check that each connector lies flat against both cores, with no visible gap or twist between its strap and the wall, before tightening either screw. Nothing here is adjustable once the tower is stacked.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-two-layers-joined-zoom-full-246efab909cb.png" alt="Close render of the joint between two stacked chute cores, a yellow layer connector with its flat face outward fixed across the joint on the servo side wall">
  <figcaption>Two chutes joined: the connector is screwed to the lower core's top insert and to the upper core's bottom insert. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

## The finished result

One connector near the top of each long wall, each held by its lower screw, each upper hole left empty for the part that slots on above.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-connectors-seated-full-49e25b8766d3.png" alt="Render of a chute core with a yellow layer connector standing on each long wall near the top, the upper hole of each free for the chute above">
  <figcaption>The pair on a chute core. The lower screw holds each one; the empty hole above it is what the part above screws down into. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

The [Chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}) page carries the other three sub-assemblies that go on the same core, and is where you should return once you're done here.
