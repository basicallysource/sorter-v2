---
layout: default
title: Bottom layer
type: how-to
section: hardware
slug: assembly-bottom-layer
kicker: Bin frame — Bottom layer
lede: The layer the machine stands on. A regular layer with foot extensions in place of piece C, and the casters under them.
permalink: /hardware/assembly/distribution/bin-frame/bottom-layer/
author: spencer
contributors: [brickcyclealice, christoph, daddyosbricksbill, dov2000]
og_image: https://assets.basically.website/sorter-docs/assembly-bottom-layer-corner-bracket-on-d-w1600-67bd9444f306.jpg
warning: >-
  **AI-generated first draft.** Written from the machine assembly tree in the
  [parts calculator](https://parts-calculator.basically.website/assembly?focus=bottom-layer),
  not from an actual build. The one-layer structure and the photographs of the
  finished result come from BrickCycleAlice's build, and how the bottom
  interface hangs under this layer was written from a build by Daddy-O's Bricks
  - Bill; the screw counts have not been checked off a machine. Correct it as
  you build.
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
    qty: 36
tools_needed: [Hex key, Tape measure]
---

The bottom layer is an ordinary bin layer that also carries the machine. Its vertical extrusion is one long piece per corner instead of a layer's worth: the caster screws into the bottom of it and the layer above lands on the top of it, so the wheel has something much stiffer to push against than a single layer's vertical would be.

**Build it after a [regular layer]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}), not before.** Everything here is a regular layer with three differences at floor level, so that page is the one that describes the layer and this one only covers what changes: piece D in place of piece C, an External bracket — foot cover in place of the cover and the External bracket — bottom vertical at the bottom of the corner, and the feet.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}">hex frame</a> before you start</strong>, and leave the six External bracket — covers off this one. It is a required component of this page, not covered here.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-hex-frame-finished-top-down-w1600-a62a42d595ca.jpg" alt="A finished hex frame from above: six B spokes and their printed crossbeams forming the inner ring inside the aluminum outer hexagon, with a printed corner bracket at each of the six vertices">
    <figcaption>A finished hex frame. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

The aluminum extrusion is cut to length; the [framing cut list](https://parts-calculator.basically.website/framing) has the exact dimensions for piece D.

{% include fastener-legend.html %}

{% include step.html n="1" title="Preparation" %}

No heat inserts on this assembly. Every printed part here takes a self-tapping {% include fastener.html size="M5" variant="socket-button" length="16" %} screw straight into the plastic.

Cut the extrusion first. This layer uses **6 × piece D (Foot extension), 231 mm**, and **no piece C**: D is what stands between this layer and the one above it, and it carries on down to the caster as well. Every layer above this one takes its own piece C, so an N-layer machine needs 6 × D and 6 × (N−1) × C. The [framing cut list](https://parts-calculator.basically.website/framing) has every length.

<div class="callout">
  <p>D is 1.5 × a single layer's vertical support, not 2 ×, so the bottom layer sits about half a layer's height off the floor.</p>
</div>

Here's where the {% include fastener.html size="M5" variant="socket-button" length="16" %} count in the parts list comes from (nobody has counted these off a built machine yet, and the hex frame's own outer-ring screws are on that page's own list, so they aren't counted again here):

- **12** clamping the External bracket — side onto piece D, 2 per corner (step 3 below)
- **12** through the External bracket — bottom vertical's outer holes onto the top of piece D, 2 per corner (step 5 below)
- **12** holding the External bracket — foot cover on, 2 per corner (step 2 below), the same 2 the bottom vertical it replaces would have taken

Two more things are not in that count and are on their own pages: the bin retainers in step 6, and the 12 screws that join the layer above to this one, which are on [Stacking the layers]({{ '/hardware/assembly/distribution/stacking-the-layers/' | relative_url }}).

{% include step.html n="2" title="Close off the corners at floor level" %}

The bottom layer does not get an External bracket — cover, and it does not get an External bracket — bottom vertical *below* its frame the way every other layer does. It gets an **External bracket — foot cover** instead, one per corner, which is the single printed part that replaces both of them. It is shorter than the pair it replaces, on purpose, so the extrusion stands out past it far enough for the foot connector in step 4.

**Fit it now, before any extrusion goes in.** It takes 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws through its outer holes into the External bracket — side, and it is awkward to fit once piece D is through the corner.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/img-4215-crop1-full-d1ae19d41e44.jpg" alt="Close-up of the foot cover bolted to the External bracket — side, with the two foot-cover screws and the extrusion mounting screws visible">
  <figcaption>The foot cover to External bracket connection, with the extrusion socket open at the top. <cite>Photo courtesy of BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="3" title="Run the foot extensions through the corners" %}

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-bottom-two-layers-c-and-d-extrusion-corner-full-58d89d80131f.jpg" alt="One corner of a built machine close up, with the C layer vertical support marked by an arrow between the two frames above and the longer D foot extension marked by an arrow running from the caster up past the bottom frame to the second">
  <figcaption>One corner of a standing machine, close up. D runs from the caster, past this layer's corner, up to the layer above; C is the ordinary vertical between the layers further up. <cite>Photo courtesy of Christoph in the basically Discord.</cite></figcaption>
</figure>

The corner itself is the same as on any layer. Only the vertical changes: piece D takes the place of piece C, and it stands proud at the bottom instead of being capped.

On each of the six corners:

<ol class="numbered-steps">
  <li>Partially thread the 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws that clamp the collar onto the extrusion, at the holes near the bottom of the External bracket — side, so they are started but not yet tight.</li>
  <li>Slide a piece D down through the corner, from above, until it stands out below the foot cover.</li>
  <li>Measure from the bottom before tightening anything, to check how far the exposed end will stand proud once the corner is clamped.</li>
  <li>Tighten the 2 collar screws, bracing against the extrusion.</li>
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

Let the bottom end of piece D stand proud of the corner rather than sitting flush with it: the foot connector bolts into that exposed end, and the External bracket — foot cover is deliberately shorter than an ordinary cover so the extrusion pops out far enough to take it.

<figure class="figure-float-right">
  <a href="https://assets.basically.website/sorter-docs/assembly-bottom-two-layers-foot-corner-section-full-6ec3353ee6cf.png" target="_blank" rel="noopener">
    <img src="https://assets.basically.website/sorter-docs/assembly-bottom-two-layers-foot-corner-section-full-6ec3353ee6cf.png" alt="Vertical cross-section through one corner at the bottom of the machine, showing piece D running through the bottom layer's bracket and up into the layer above, the foot cover around it, and the exposed end below">
  </a>
  <figcaption>One corner at floor level, cut through the centre of the profile. The bottom layer is blue, the collar of the layer above purple. The numbers match the list below. Click to enlarge. <cite>Drawn from the part geometry rather than from a build, by Balloon.</cite></figcaption>
</figure>

The numbers on the drawing:

<ol class="keyed-list">
  <li><strong>External bracket — side</strong>, the same collar as on any layer, at this layer's frame.</li>
  <li><strong>External bracket — foot cover</strong> in place of the bottom vertical and cover. It closes the corner off but is far shorter, so the extrusion can leave the bottom of it.</li>
  <li><strong>Piece D</strong>, 231 mm cut. It runs from below this layer, through its collar, and up to 3 mm below the flange face of the collar above, so it spans the whole gap to the next layer as well as reaching the floor.</li>
  <li class="key-screw"><strong>Two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws</strong> clamp this layer's collar onto piece D, and two more clamp the External bracket — bottom vertical onto it in step 5. Same screws, same holes as on a regular layer.</li>
  <li class="key-note"><strong>The exposed end of piece D</strong>, which takes the 2020 M6 foot connector and the caster. On the lengths as drawn it stands about 54 mm below the foot cover, but how far it should protrude is not recorded anywhere, so hold a foot connector against the end before you tighten the corner screws.</li>
  <li><strong>The collar of the layer above</strong>, sitting on the External bracket — bottom vertical fitted in step 5. From here up, every joint is the ordinary layer joint described on <a href="{{ '/hardware/assembly/distribution/stacking-the-layers/' | relative_url }}">Stacking the layers</a>.</li>
</ol>

<div class="clear-float"></div>

{% include step.html n="4" title="Fit the feet" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Fit all six casters before the machine gets any taller. A bin tower on five feet is not something you want to discover at four layers.</p>
</div>

Bolt a **2020 M6 foot connector** into the open bottom end of each piece D. The connector is an aluminum bracket made for the end of 2020 extrusion and comes with its own bolts and nuts.

Screw a **swivel stem caster (M6 × 15 mm)** into the connector's M6 thread. The casters have brakes; leave them on while you build.

{% include step.html n="5" title="Cap each extrusion with the bottom vertical bracket" %}

This is the step that turns the bottom layer into an ordinary layer as far as everything above it is concerned. Slide an **External bracket — bottom vertical** onto the length of piece D standing above the frame, ensuring its angles align at the bottom, and secure it with 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws through its outer holes. It is the same part, fitted the same way, as on a regular layer.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-bottom-layer-corner-bracket-on-d-w1600-67bd9444f306.jpg" alt="One corner of the bottom layer seen close up from above: the External bracket — bottom vertical standing on the collar with the end of piece D recessed in its square socket, the foot cover below the frame, and the caster under that">
  <figcaption>One finished corner, from the collar up to the socket the next layer lands on and down to the caster. The end of piece D sits a few millimetres below the top face of the bracket, which is what it should look like. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

Matching parts from the same print run are embossed with a shared set code (e.g. **"b2"**) on both the External bracket — side and the External bracket — bottom vertical. Keep marked pairs together so brackets don't get mixed across corners.

{% include step.html n="6" title="Add the bin retainers" %}

This layer takes a full set, the same twelve every bin layer gets: **[Bin retainers]({{ '/hardware/assembly/distribution/bin-frame/bin-retainers/' | relative_url }})**, including the T-nuts they fasten into. Do it now, while the layer is still something you can turn around.

## The finished result

One hexagon closed, six casters on, and every corner ending in a bottom vertical bracket ready for the next layer.

<div class="img-placeholder">Image coming: the whole layer on its casters, with the bin retainers on and nothing yet fitted under the spokes</div>

## What comes next

The bottom layer is the base of the bin frame, not a finished assembly on its own. What follows is:

<ol class="numbered-steps">
  <li><strong>Stack the rest of the frame onto it.</strong> Build N−1 <a href="{{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}">regular layers</a> for an N-layer machine, then join them, the chutes and the top interface into the tower on <a href="{{ '/hardware/assembly/distribution/stacking-the-layers/' | relative_url }}">Stacking the layers</a>.</li>
  <li><strong>Sling the <a href="{{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}">bottom interface</a> underneath</strong>, bolted up into 3 of this layer's 6 B spokes. It is built and fitted on its own page: three Lazy Susan extrusion mount pairs bolt up into 3 of the 6 spokes, alternating around the ring, and the bearing sits on them. Its screws and T-nuts are on that page's parts list, not this one's, which is why they are not in the count above.</li>
</ol>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-lazy-susan-extrusion-mount-three-views-w1600-581de80090b8.jpg" alt="Three views of the same printed part on a white background: the Lazy Susan extrusion mount with its hold in place bolted under it, a grey wedge with a triangular window through its web and counterbored slots along its bottom face">
  <figcaption>A Lazy Susan extrusion mount with its hold in place, from three angles. Three of these pairs go under this layer. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-bottom-two-layers-ls-mount-on-spoke-w1600-f2dd3fc8fe63.jpg" alt="Close-up of a Lazy Susan extrusion mount bolted onto a B spoke, the printed wedge with its triangular window sitting against the spoke's extrusion at a hex frame corner">
    <figcaption>One mount bolted onto a B spoke. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-bottom-two-layers-ls-mounts-three-on-ring-w1600-2d730f64193b.jpg" alt="A hex frame seen from above with three Lazy Susan extrusion mounts fitted, one on each of three spokes spaced alternately around the ring">
    <figcaption>All three on, alternating around the ring so they land on 3 of the 6 spokes. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="callout">
  <p>The height that comes out of this is right when a <a href="{{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}">chute core</a> with a funnel on it, fitted onto the chute mount, puts the funnel level with the bin entrances.</p>
</div>

The [Bin frame]({{ '/hardware/assembly/distribution/bin-frame/' | relative_url }}) page carries the order for the whole stack, and is the place to go back to when you have finished here.
