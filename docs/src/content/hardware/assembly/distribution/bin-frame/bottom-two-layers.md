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
contributors: [brickcyclealice, christoph]
warning: >-
  **AI-generated first draft.** Written from the [framing cut
  list](https://parts-calculator.basically.website/framing), the machine assembly tree in the
  [parts calculator](https://parts-calculator.basically.website/assembly?focus=layer-frame) and
  photos of finished machines in the Discord, not from an actual build. No step here has been
  checked against a machine. The fastener counts are derived from Regular layers rather than
  measured, the tally under step 1 shows the arithmetic, and one count is genuinely unknown.
  Correct it as you build.
parts_needed:
  - part: ext-bracket-left
    qty: 12
  - part: ext-bracket-cover
    qty: 6
  - part: ext-bracket-bottom-vertical
    qty: 6
  - part: ext-bracket-foot-cover
    qty: 6
  - part: frame-90deg-bracket
    qty: 24
  - part: frame-crossbeam
    qty: 12
  - part: bin-retainer-left
    qty: 12
  - part: bin-retainer-right
    qty: 12
  - part: ext-2020-ag
    qty: 12
  - part: ext-2020-bh
    qty: 12
  - part: ext-2020-d
    qty: 6
  - part: foot-connector-2020-m6
    qty: 6
  - part: caster-wheel-m6
    qty: 6
  - part: scr-m5-16-shcs
    qty: 84
  - part: scr-m5-20-shcs
    qty: 24
  - part: scr-m5-12-shcs
    qty: 72
  - part: tnut-m5-2020
    qty: 72
---

The bottom two layers are two ordinary bin layers built at the same time, because the vertical extrusion between them is one continuous piece per corner instead of one per layer. That piece is the machine's leg: the caster screws into the bottom of it, so running it up through the bottom layer and into the second gives the wheel something much stiffer to push against than a single layer's worth of extrusion would.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-bottom-two-layers-frame-on-casters-w1600-6454aa70d746.jpg" alt="The bottom of a built machine: two bin-frame layers on six swivel casters, with the extrusion legs running up past the bottom frame into the second, and the start of a third layer's hexagon ring above them">
  <figcaption>The bottom two layers on their casters. The hexagon ring at the top is the next layer starting, not part of these two, so this is about two and a half layers of machine. Photo courtesy of Christoph in the basically Discord.</figcaption>
</figure>

Everything else about these two layers is the same as any other. Build each one with the [regular layers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}) guide and come back here for the parts that differ, which are only the verticals, the corners at floor level, and the feet.

The aluminum extrusion is cut to length; the [framing cut list](https://parts-calculator.basically.website/framing) has the exact dimensions for pieces A/G, B/H and D. The number of {% include fastener.html size="M5" variant="t-nut" text="M5 T-nuts" %} listed above is the minimum you'll need if you thread the printed parts directly wherever possible; this number increases if you use T-nuts throughout instead.

**Build the [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}) before you start.** It is step 1 of the bin frame and it mounts to this frame with three Lazy Susan extrusion mounts, each on an {% include fastener.html size="M5" variant="socket-button" length="16" %} screw into a {% include fastener.html size="M5" variant="t-nut" text="T-nut" %}. Getting T-nuts into an extrusion that already has both layers built around it is the kind of job you only do once.

{% include fastener-legend.html %}

{% include step.html n="1" title="Preparation" %}

No heat inserts on this assembly. Every printed part here takes a self-tapping {% include fastener.html size="M5" variant="socket-button" length="16" %} screw straight into the plastic, the same as [assembling external bracket]({{ '/hardware/helpers/external-bracket/' | relative_url }}).

Cut the extrusion first. These two layers use **6 × piece D (Foot extension), 231 mm**, and **no piece C at all** — D stands in for the C that each of these two layers would otherwise have. The [framing cut list](https://parts-calculator.basically.website/framing) has every length; at 1 or 2 layers, C is genuinely absent from that list rather than missing.

<div class="callout">
  <p>D is 1.5 × a single layer's vertical support, not 2 ×. It runs from the caster at the bottom, through the bottom layer's corner, up to the second layer's frame, so the bottom layer sits about half a layer's height off the floor. Spencer confirmed this is what the Brickworld machines were built to.</p>
</div>

Where the {% include fastener.html size="M5" variant="socket-button" length="16" %} count in the parts list comes from, since nobody has counted these off a built machine:

- **48** for the two hexagons and their spokes, which is [regular layers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}) steps 1 and 2 done twice
- **24** for the foot extensions, 4 per corner (step 3 below), two into each layer
- **12** for the second layer's External bracket — bottom verticals, 2 per corner (step 4 below)

The {% include fastener.html size="M5" variant="socket-button" length="12" %} count is the same arithmetic: **12** per layer holding the Frame 90° brackets and **24** per layer for the bin retainers, so **72** across both.

The bottom layer's External bracket - foot cover is the one that is not accounted for: whether it takes the 2 screws the bottom vertical it replaces would have, or clips on like a cover, is not recorded anywhere. <span class="fastener-todo">fastener not recorded</span>

{% include step.html n="2" title="Build two layer frames" %}

Work through [regular layers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}) steps 1 and 2 twice, once per layer: the hexagon of six A/G extrusions in six External bracket — sides, then the six B/H spokes on their Frame 90° brackets with a Frame crossbeam each side.

**Stop before that guide's step 3 (Install the verticals).** The verticals are the part that differs here, and they are step 3 below.

If you are using slide-in T-nuts, put them in as that guide says. The ends of the extrusion are no more accessible on these two layers than on any other.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Put the <a href="{{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}">bottom interface</a>'s three T-nuts into this frame now, while the extrusion is still open. Three Lazy Susan extrusion mounts each take one {% include fastener.html size="M5" variant="socket-button" length="16" %} into a {% include fastener.html size="M5" variant="t-nut" text="T-nut" %}, and once both layers are built around the extrusion a slide-in T-nut has nowhere to go in.</p>
</div>

{% include step.html n="3" title="Run the foot extensions through both layers" %}

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-bottom-two-layers-c-and-d-extrusion-w1600-71a8f20c58c5.jpg" alt="The bottom corner of a built machine, with the C layer vertical support marked between the second and third frames and the longer D foot extension marked running from the caster up past the bottom frame to the second">
  <figcaption>C between the layers above; D from the caster, past the bottom layer's corner, to the second layer. Photo courtesy of Christoph in the basically Discord.</figcaption>
</figure>

<figure class="figure-float-right">
  <a href="https://assets.basically.website/sorter-docs/assembly-bottom-two-layers-foot-corner-section-full-6ec3353ee6cf.png" target="_blank" rel="noopener">
    <img src="https://assets.basically.website/sorter-docs/assembly-bottom-two-layers-foot-corner-section-full-6ec3353ee6cf.png" alt="Vertical cross-section through one corner at the bottom of the machine, showing piece D running through the bottom layer's bracket and up into the second layer, the foot cover around it, and the exposed end below">
  </a>
  <figcaption>One corner at floor level, cut through the centre of the profile. The bottom layer is blue, the second layer's collar purple. The numbers match the list below. Click to enlarge. Drawn from the part geometry rather than from a build.</figcaption>
</figure>

The corner itself is the same as on any layer. Only the vertical changes: one piece D takes the place of the C that each of these two layers would otherwise have, and it stands proud at the bottom instead of being capped.

On each of the six corners, working on the second layer first:

<ol class="numbered-steps">
  <li>Slot an External bracket — cover onto the second layer's External bracket — side, before the extrusion goes in. It is awkward to fit afterwards.</li>
  <li>Slide a piece D down through the second layer's bracket and on down through the matching corner of the bottom layer, so one piece passes through both.</li>
  <li>Secure it at the second layer with 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws tapped through the holes near the bottom of the External bracket — side, bracing against the extrusion.</li>
  <li>Secure it again at the bottom layer's External bracket — side the same way, 2 more {% include fastener.html size="M5" variant="socket-button" length="16" %} screws.</li>
</ol>

Let the bottom end of piece D stand proud of the bottom layer's corner rather than sitting flush with it: the foot connector bolts into that exposed end, and the External bracket - foot cover in step 4 is deliberately shorter than an ordinary cover so the extrusion pops out far enough to take it.

The numbers on the drawing:

<ol class="keyed-list">
  <li><strong>External bracket — side</strong>, the same collar as on any layer, at the bottom layer's frame.</li>
  <li><strong>External bracket - foot cover</strong> in place of the bottom vertical and cover. It closes the corner off but is far shorter, so the extrusion can leave the bottom of it.</li>
  <li><strong>Piece D</strong>, 231 mm cut. It runs from below the bottom layer, through that layer's collar, and up to 3 mm below the flange face of the second layer's collar, replacing a piece C in each of the two layers.</li>
  <li class="key-screw"><strong>Two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws per collar</strong> clamp the bracket onto piece D, at the bottom layer and again at the second layer. Same screws, same holes as on a regular layer.</li>
  <li class="key-note"><strong>The exposed end of piece D</strong>, which takes the 2020 M6 foot connector and the caster. On the lengths as drawn it stands about 54 mm below the foot cover, but how far it should protrude is not recorded anywhere, so hold a foot connector against the end before you tighten the corner screws.</li>
  <li><strong>The second layer's collar</strong>, with its External bracket — bottom vertical below it. From here up, every joint is the ordinary layer joint described in <a href="{{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}#step-5">regular layers, step 5</a>.</li>
</ol>

Measured off the parts: the foot cover has no fastener holes of any kind, neither the vertical pair the bottom vertical's flange carries nor the self-tapping pair the brackets use, so it appears to go on as a cover rather than being screwed. <span class="fastener-todo">fastener not recorded</span>

The two layers are now one rigid unit and their spacing is set by the bracket positions, not by anything you have to measure.

{% include step.html n="4" title="Close off the corners at floor level" %}

The bottom layer does not get an External bracket — bottom vertical or an External bracket — cover. It gets an **External bracket - foot cover** instead, one per corner, which is the single printed part that replaces both of them. It is shorter than the pair it replaces, on purpose, so the extrusion stands out past it far enough for the foot connector in step 5.

How the foot cover fastens is not recorded: the bottom vertical it replaces takes 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws through its outer holes, and the cover it replaces clips on and takes none. <span class="fastener-todo">fastener not recorded</span>

The second layer's corners are ordinary, exactly as in [regular layers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}) step 3: an External bracket — bottom vertical slid onto piece D with its angles aligned at the bottom, 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws through its outer holes.

{% include step.html n="5" title="Fit the feet" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Fit all six casters before the machine gets any taller. A bin tower on five feet is not something you want to discover at four layers.</p>
</div>

Bolt a **2020 M6 foot connector** into the open bottom end of each piece D. The connector is an aluminum bracket made for the end of 2020 extrusion and comes with its own bolts and nuts.

Screw a **swivel stem caster (M6 × 15 mm)** into the connector's M6 thread. The casters have brakes; leave them on while you build.

{% include step.html n="6" title="Add the bin retainers" %}

Both layers take bin retainers, exactly as in [regular layers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}) step 4: on each side of each hexagon, a Bin retainer (left) and a Bin retainer (right) on the front face of the A/G extrusion, 4 {% include fastener.html size="M5" variant="socket-button" length="12" %} screws into T-nuts.

## What comes next

- Each of these two layers takes a [chute]({{ '/hardware/assembly/distribution/chute/' | relative_url }}), the same as any other layer.
- Above them, build N−2 [regular layers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}) for an N-layer machine.
- The [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}) mounts to this frame on its three extrusion mounts.
