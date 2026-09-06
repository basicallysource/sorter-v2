---
layout: default
title: Bottom two layers
type: how-to
section: hardware
slug: assembly-bottom-two-layers
kicker: Bin frame — Bottom two layers
lede: The paired base layers. Built together on the foot extensions the casters mount to.
permalink: /hardware/assembly/distribution/bin-frame/bottom-two-layers/
author: spencer
contributors: [brickcyclealice, christoph, daddyosbricksbill, dov2000]
warning: >-
  **AI-generated first draft.** Step 6 was written from a build by
  Daddy-O's Bricks - Bill; no other step here has been checked against a
  machine. Correct it as you build.
parts_needed:
  - part: ext-bracket-bottom-vertical
    qty: 6
  - part: ext-bracket-foot-cover
    qty: 6
  - part: ext-2020-d
    qty: 6
  - part: foot-connector-2020-m6
    qty: 6
  - part: caster-wheel-m6
    qty: 6
  - part: scr-m5-16-shcs
    qty: 48
tools_needed: [Hex key, Tape measure]
---

The bottom two layers are two ordinary bin layers built at the same time, because the vertical extrusion between them is one continuous piece per corner instead of one per layer. That piece is the machine's leg: the caster screws into the bottom of it, so running it up through the bottom layer and into the second gives the wheel something much stiffer to push against than a single layer's worth of extrusion would.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-bottom-two-layers-dov2000-three-quarter-w1600-18a2620a5963.jpg" alt="A finished pair of bottom bin-frame layers standing on six swivel casters, two hexagons of anodized 2020 extrusion tied together by black printed corner brackets, with spokes and crossbeams inside each ring">
  <figcaption>The two layers standing on their casters, which is what this page builds. The bottom interface is not fitted in this photo; its Lazy Susan extrusion mounts go under the bottom layer's spokes in step 6. <cite>Photo: Dov2000.</cite></figcaption>
</figure>

Everything else about these two layers is the same as any other. Build each one with the [regular layers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}) guide and come back here for the parts that differ, which are only the verticals, the corners at floor level, and the feet.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build two <a href="{{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}">hex frames</a> before you start</strong>, one for each layer. They're required components of this page, not covered here.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/hex-frame-finished-top-down-full-c6abfb4dad6e.jpg" alt="A finished hex frame from above, the alternating grey spoke and teal crossbeam pieces forming the inner ring inside the aluminum outer hexagon">
    <figcaption>A finished hex frame. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

The aluminum extrusion is cut to length; the [framing cut list](https://parts-calculator.basically.website/framing) has the exact dimensions for piece D.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build the <a href="{{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}">bottom interface</a> before you start.</strong> It has no frame of its own: its three Lazy Susan extrusion mounts bolt up under the bottom layer's spokes, which is step 6 below. Get its 6 T-nuts into 3 of that layer's B/H spokes while you are building the frame, before the ring closes.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-bottom-two-layers-lazy-susan-extrusion-mount-full-0b3eab019aee.jpg" alt="A printed Lazy Susan extrusion mount on a bench: a grey wedge with a triangular window through its web, a rounded boss on top, and two counterbored slots along its bottom face">
    <figcaption>A Lazy Susan extrusion mount. Three of them bolt up into the bottom layer's spokes in step 6, one per spoke on 3 of the 6. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include fastener-legend.html %}

{% include step.html n="1" title="Preparation" %}

No heat inserts on this assembly. Every printed part here takes a self-tapping {% include fastener.html size="M5" variant="socket-button" length="16" %} screw straight into the plastic.

Cut the extrusion first. These two layers use **6 × piece D (Foot extension), 231 mm**, and **no piece C at all** — D stands in for the C that each of these two layers would otherwise have. The [framing cut list](https://parts-calculator.basically.website/framing) has every length; at 1 or 2 layers, C is genuinely absent from that list rather than missing.

<div class="callout">
  <p>D is 1.5 × a single layer's vertical support, not 2 ×, so the bottom layer sits about half a layer's height off the floor.</p>
</div>

Here's where the {% include fastener.html size="M5" variant="socket-button" length="16" %} count in the parts list comes from (nobody has counted these off a built machine yet, and the two hex frames' own outer-ring screws are on that page's own list, so they aren't counted again here):

- **24** for the foot extensions, 4 per corner (step 2 below), two into each layer
- **12** for the second layer's External bracket — bottom verticals, 2 per corner (step 3 below)
- **12** for the bottom layer's External bracket — foot covers, 2 per corner (step 3 below), the same as the bottom vertical it replaces

The bin retainers in step 5 are not in that count: they and their fasteners are listed on their own page.

You should already have two [hex frames]({{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}) built, one for each layer. The verticals are the part that differs here, and they are step 2 below.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>Get the bottom interface's 6 T-nuts into the bottom layer's spokes before the ring closes.</strong> Two each into 3 of the 6 B/H spokes, alternating around the ring. <a href="{{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}#step-4">Bottom interface, step 4</a> bolts its Lazy Susan extrusion mounts up into them from underneath, so they go in this frame's extrusion, not a frame of its own. Roll-in T-nuts can go in later; slide-in ones cannot, see <a href="{{ '/hardware/helpers/t-nuts/' | relative_url }}">Fitting T-nuts</a>.</p>
</div>

{% include step.html n="2" title="Run the foot extensions through both layers" %}

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-bottom-two-layers-c-and-d-extrusion-corner-full-58d89d80131f.jpg" alt="One corner of a built machine close up, with the C layer vertical support marked by an arrow between the two frames above and the longer D foot extension marked by an arrow running from the caster up past the bottom frame to the second">
  <figcaption>One corner, close up. C between the layers above; D from the caster, past the bottom layer's corner, to the second layer. <cite>Photo courtesy of Christoph in the basically Discord.</cite></figcaption>
</figure>

The corner itself is the same as on any layer. Only the vertical changes: one piece D takes the place of the C that each of these two layers would otherwise have, and it stands proud at the bottom instead of being capped.

On each of the six corners, working on the second layer first:

<ol class="numbered-steps">
  <li>The second layer's External bracket — cover is already on, fitted with its <a href="{{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}#step-9">hex frame</a>, and it takes no screws. Slot an External bracket — foot cover onto the bottom layer's External bracket — side now, before either extrusion goes in: it does take 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws, and it is awkward to fit afterwards.</li>
  <li>Partially thread the 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws that will clamp each collar onto piece D, at both the second layer's bracket and the bottom layer's, so they are started but not yet tight.</li>
  <li>Slide a piece D down through the second layer's bracket and on down through the matching corner of the bottom layer, so one piece passes through both.</li>
  <li>Measure from the bottom before tightening anything, to check how far the exposed end will stand proud once the corner is clamped.</li>
  <li>Tighten the collar screws at the second layer, bracing against the extrusion, then the same 2 screws at the bottom layer.</li>
</ol>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/img-4207-full-ccd9635abfe0.jpg" alt="Piece D held against the bracket with a tape measure alongside, measuring from the bottom before the collar screws are tightened">
    <figcaption>Measuring piece D from the bottom before the collar screws are tightened down. <span class="photo-credit">Photo courtesy of BrickCycleAlice.</span></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/img-4208-full-a6f410b71459.jpg" alt="Driving one of the collar screws home with a hex key once piece D is positioned">
    <figcaption>Tightening the collar screw once piece D is positioned. <span class="photo-credit">Photo courtesy of BrickCycleAlice.</span></figcaption>
  </figure>
</div>

Let the bottom end of piece D stand proud of the bottom layer's corner rather than sitting flush with it: the foot connector bolts into that exposed end, and the External bracket — foot cover in step 3 is deliberately shorter than an ordinary cover so the extrusion pops out far enough to take it.

<figure class="figure-float-right">
  <a href="https://assets.basically.website/sorter-docs/assembly-bottom-two-layers-foot-corner-section-full-6ec3353ee6cf.png" target="_blank" rel="noopener">
    <img src="https://assets.basically.website/sorter-docs/assembly-bottom-two-layers-foot-corner-section-full-6ec3353ee6cf.png" alt="Vertical cross-section through one corner at the bottom of the machine, showing piece D running through the bottom layer's bracket and up into the second layer, the foot cover around it, and the exposed end below">
  </a>
  <figcaption>One corner at floor level, cut through the centre of the profile. The bottom layer is blue, the second layer's collar purple. The numbers match the list below. Click to enlarge. Drawn from the part geometry rather than from a build.</figcaption>
</figure>

The numbers on the drawing:

<ol class="keyed-list">
  <li><strong>External bracket — side</strong>, the same collar as on any layer, at the bottom layer's frame.</li>
  <li><strong>External bracket — foot cover</strong> in place of the bottom vertical and cover. It closes the corner off but is far shorter, so the extrusion can leave the bottom of it.</li>
  <li><strong>Piece D</strong>, 231 mm cut. It runs from below the bottom layer, through that layer's collar, and up to 3 mm below the flange face of the second layer's collar, replacing a piece C in each of the two layers.</li>
  <li class="key-screw"><strong>Two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws per collar</strong> clamp the bracket onto piece D, at the bottom layer and again at the second layer. Same screws, same holes as on a regular layer.</li>
  <li class="key-note"><strong>The exposed end of piece D</strong>, which takes the 2020 M6 foot connector and the caster. On the lengths as drawn it stands about 54 mm below the foot cover, but how far it should protrude is not recorded anywhere, so hold a foot connector against the end before you tighten the corner screws.</li>
  <li><strong>The second layer's collar</strong>, with its External bracket — bottom vertical below it. From here up, every joint is the ordinary layer joint described in <a href="{{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}#step-3">regular layers, step 3</a>.</li>
</ol>

The two layers are now one rigid unit and their spacing is set by the bracket positions, not by anything you have to measure.

{% include step.html n="3" title="Close off the corners at floor level" %}

The bottom layer does not get an External bracket — bottom vertical or an External bracket — cover. It gets an **External bracket — foot cover** instead, one per corner, which is the single printed part that replaces both of them. It is shorter than the pair it replaces, on purpose, so the extrusion stands out past it far enough for the foot connector in step 4.

The foot cover fastens the same way the bottom vertical it replaces would: 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws through its outer holes into the External bracket — side. Mount it before the extrusion goes in, at the point in step 2 where the corner is still open.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/img-4215-crop1-full-d1ae19d41e44.jpg" alt="Close-up of the foot cover bolted to the External bracket — side, with the two foot-cover screws and the extrusion mounting screws visible">
  <figcaption>The foot cover to External bracket connection, with the extrusion socket open at the top. <cite>Photo courtesy of BrickCycleAlice.</cite></figcaption>
</figure>

The second layer's corners are ordinary, exactly as in [regular layers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}) step 1: an External bracket — bottom vertical slid onto piece D with its angles aligned at the bottom, 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws through its outer holes.

{% include step.html n="4" title="Fit the feet" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Fit all six casters before the machine gets any taller. A bin tower on five feet is not something you want to discover at four layers.</p>
</div>

Bolt a **2020 M6 foot connector** into the open bottom end of each piece D. The connector is an aluminum bracket made for the end of 2020 extrusion and comes with its own bolts and nuts.

Screw a **swivel stem caster (M6 × 15 mm)** into the connector's M6 thread. The casters have brakes; leave them on while you build.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-bottom-two-layers-dov2000-three-quarter-w1600-18a2620a5963.jpg" alt="A pair of bottom bin-frame layers standing on six swivel casters, two hexagons of anodized 2020 extrusion tied together by black printed corner brackets, with the middle of the bottom layer still open">
  <figcaption>All six casters on, one under each corner. Nothing is fitted under the bottom layer here: the bottom interface's Lazy Susan extrusion mounts come later, in step 6. <cite>Photo: Dov2000.</cite></figcaption>
</figure>

{% include step.html n="5" title="Add the bin retainers" %}

Both layers take a full set of retainers, so do **[Bin retainers]({{ '/hardware/assembly/distribution/bin-frame/bin-retainers/' | relative_url }}) twice**, once for each hexagon. That page's parts list is per layer; double every quantity on it here.

{% include step.html n="6" title="Attach the bottom interface" %}

The [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}) hangs underneath the **bottom layer's** frame. It does not share piece D's legs and it does not get a hex frame of its own.

Working from under the bottom layer, bolt each of its three Lazy Susan extrusion mount pairs up into the underside of a B/H spoke, on 3 of the 6 spokes alternating around the ring, 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws per mount into the T-nuts you put in earlier. Those 6 screws are on the bottom interface's own parts list, not this page's, so they aren't in the count above. The bearing then sits on the three mounts, and the chute mount faces up into the machine.

<div class="callout">
  <p>The height that comes out of this is right when a <a href="{{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}">chute core</a> with a funnel on it, fitted onto the chute mount, puts the funnel level with the bin entrances.</p>
</div>

<div class="img-placeholder">Image coming</div>

## The finished result

Both hexagons closed, six casters on, and the two layers held together as one unit by the foot extensions running through them.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-bottom-two-layers-dov2000-top-down-w1600-f1adb1d66dac.jpg" alt="The finished bottom two layers seen from directly above, the second layer's hexagon sitting over the bottom layer's, with the spokes and crossbeams of both rings visible inside them">
  <figcaption>The same pair from above. The second layer's ring sits over the bottom layer's, and the spokes and crossbeams of both are visible through the middle. <cite>Photo: Dov2000.</cite></figcaption>
</figure>

## What comes next

These two layers are the bottom of the bin frame, not a finished assembly on their own. What follows is fastening the rest of the frame onto them, in this order:

<ol class="numbered-steps">
  <li><strong>Stack the remaining layers on top.</strong> Build N−2 <a href="{{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}">regular layers</a> for an N-layer machine and join each one down onto the layer below it. <a href="{{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}#step-3">Regular layers, step 3</a> is that joint, and it is the same joint every time, including where the first regular layer lands on the second of these two.</li>
  <li><strong>Cap the stack with the <a href="{{ '/hardware/assembly/distribution/top-interface/' | relative_url }}">top interface</a></strong>, which takes one of the hex frames you built at the start. <a href="{{ '/hardware/assembly/distribution/top-interface/' | relative_url }}#step-14">Top interface, step 14</a> is how it lands on the top layer.</li>
  <li><strong>Hang a <a href="{{ '/hardware/assembly/distribution/chute/' | relative_url }}">chute</a> in every layer</strong>, these two included.</li>
</ol>

The [Bin frame]({{ '/hardware/assembly/distribution/bin-frame/' | relative_url }}) page carries that order for the whole stack, and is the place to go back to when you have finished here.
