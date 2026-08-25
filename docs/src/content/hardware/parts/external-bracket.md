---
layout: default
title: External bracket
type: reference
section: hardware
slug: part-external-bracket
kicker: Parts — External bracket
lede: The three-part bracket that mounts a distribution-frame vertical extrusion to the frame, and joins one layer to the next.
permalink: /hardware/parts/external-bracket/
author: christoph
contributors: [barthel, zed0, brickcyclealice]
---

Three printed parts — External bracket — side, External bracket — bottom vertical, and External bracket — cover — that bolt around a length of 2020 aluminum extrusion (piece C, the Layer vertical support). **6 per distribution frame (per layer).** The top interface uses only the side and cover from this set, no bottom vertical; see [top interface, step 13]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}#step-13).

{% include fastener-legend.html %}

- No heat inserts are used. Joining is **self-tap**: the {% include fastener.html size="M5" variant="socket-button" length="16" %} screws thread directly into the printed plastic.
- The most-used M5 in the machine — the same screw used on every external bracket, every bin bracket, every interface rib, and every lazy Susan extrusion mount.
- Matching parts from the same print run are embossed with a shared set code (e.g. **"b2"**) on both the side bracket and the bottom-vertical part. Keep marked pairs together so brackets don't get mixed across corners.

For how it actually goes together on the frame, see [regular layers, step 3]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}#step-3): the side and cover form a collar first, piece C slots through it, then the bottom vertical caps piece C from below.

## The layer joint, in section

<figure>
  <a href="https://assets.basically.website/sorter-docs/assembly-regular-layers-layer-joint-section-full-71e3c366f4e7.png" target="_blank" rel="noopener">
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-layer-joint-section-w1600-b40f8b102c10.jpg" alt="Vertical cross-section through one corner of two stacked layers, with the lower layer's extrusion and bottom-vertical tube in blue, the upper layer's bracket in purple, the two screw pairs dashed in red, and six numbered callouts">
  </a>
  <figcaption>One corner where any two layers meet, cut through the centre of the profile. Blue is the lower layer, purple the layer above. Click to enlarge. Drawn from the part geometry rather than from a build.</figcaption>
</figure>

A finished layer already carries everything that spans up to the next one: piece C standing out of its External bracket — side, and the External bracket — bottom vertical capping that extrusion. Joining two layers is therefore only the flange joint at each of the six corners, [regular layers step 5]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}#step-5).

<ol class="keyed-list">
  <li><strong>External bracket — side and cover</strong>, the 60.5 mm collar at each frame.</li>
  <li><strong>Piece C</strong>, 154 mm cut. It starts 3 mm above its own collar's underside and ends 3 mm below the flange face of the collar above, so it spans the whole 160 mm between one frame and the next.</li>
  <li><strong>External bracket — bottom vertical</strong>, 119.6 mm of tube. It sleeves the upper part of piece C, so the extrusion is not visible on an assembled machine, and its foot seats on the rim of its own layer's collar. That seat is what sets the 160 mm spacing between frames.</li>
  <li class="key-screw"><strong>The two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws that join the layers</strong>, up through the flange into the bracket above. The flange has a 5.6 mm clearance hole through 8 mm of plastic and the bracket above a 4.4 mm self-tapping hole 10 mm deep, so the screw is 8 mm of clearance and 8 mm of thread, and a longer one bottoms out before it clamps.</li>
  <li class="key-screw"><strong>The two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws that clamp the bracket onto the extrusion</strong>, self-tapping through the bracket wall. Piece C is held only here, in its own layer's bracket, and nothing screws into it from the layer above.</li>
  <li class="key-note"><strong>Where two pieces of C meet</strong>: they stop about 3 mm short of each other at the flange face and never touch.</li>
</ol>

Both screw pairs are drawn dashed because neither lies in the plane of the cut: the joining pair sits 20.6 mm either side of it, and the clamping pair comes in at 45° to it.
