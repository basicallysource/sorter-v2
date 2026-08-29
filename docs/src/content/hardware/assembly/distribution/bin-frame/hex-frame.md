---
layout: default
title: Build the hex frame
type: how-to
section: hardware
slug: assembly-hex-frame
kicker: Bin frame — Build the hex frame
lede: The hexagonal aluminum-and-bracket ring shared by every layer. Build one per planned layer, plus one for the bottom interface and one for the top interface.
permalink: /hardware/assembly/distribution/bin-frame/hex-frame/
author: barthel
contributors: [brickcyclealice, zed0]
warning: >-
  **Reorganized from a Discord build walkthrough, not yet reviewed by a
  builder.** This page has not been checked step-by-step against a build.
  Correct it as you go.
parts_needed:
  - part: ext-2020-ag
    qty: 6
  - part: ext-bracket-left
    qty: 6
  - part: ext-2020-bh
    qty: 6
  - part: frame-crossbeam
    qty: 6
  - part: frame-90deg-bracket
    qty: 12
  - part: scr-m5-16-shcs
    qty: 8
  - part: tnut-m5-2020
    qty: 24
---

This guide builds one hexagonal frame: the outer ring of A/G extrusion and External bracket — side, with the six B/H spokes and Frame crossbeams held inside it by the Frame 90° brackets. No fasteners are used from step 2 onward — the spokes, crossbeams and brackets are a friction-and-slide fit, no screws or T-nuts.

An N-layer machine needs **N + 1 of these**: one per planned layer, plus one for the [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}) and one for the [top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}).

The aluminum extrusion is cut to length; the [framing cut list](https://parts-calculator.basically.website/framing) has the exact dimensions. Each frame uses 6 A/G (320mm) and 6 B/H (158mm). The 24 T-nuts in the list above aren't used by anything in this guide — they're pre-installed in step 1 while the extrusion ends are still accessible, for the bin retainers a later page attaches to the outer ring.

{% include fastener-legend.html %}

{% include step.html n="1" title="Assemble the outer ring" %}

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-frame-corner-joint-w1600-a47ad55fb797.png" alt="Two A/G aluminum extrusions meeting at an External bracket — side, forming one corner of the hexagon">
    <figcaption><cite>Photo: zed0.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-regular-layers-frame-corner-joint-angled-w1600-6265c41bbf5f.png" alt="Angled view of the same corner joint, showing the fasteners along the extrusion">
    <figcaption><cite>Photo: zed0.</cite></figcaption>
  </figure>
</div>

Slide piece A/G (Outer horizontal / Horizontal interface frame, 320mm) of aluminum extrusion into an External bracket — side. Use an {% include fastener.html size="M5" variant="socket-button" length="16" %} screw to tap directly through the outer of the two adjacent holes on the External bracket — side, bracing it against the extrusion. If you would rather not tap and brace, place T-nuts in the extrusion and use the inner holes to fasten into them instead.

If you are using slide-in T-nuts rather than drop-in or roll-in T-nuts, insert 4 into the outermost section of the extrusion before connecting the next External bracket — side, as this is the last time the ends of the extrusion are accessible.

<figure class="video-figure">
  <div class="video-embed video-embed-wide">
    <iframe
      src="https://www.youtube.com/embed/LWruBv-fMz4"
      title="Assembling the frame brackets"
      allow="encrypted-media; picture-in-picture; web-share"
      allowfullscreen
      loading="lazy"></iframe>
  </div>
  <figcaption><cite>Video: zed0.</cite></figcaption>
</figure>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Only the 4 outer T-nuts per extrusion are needed, for the bin retainers added on a later page. The video also shows 2 inner T-nuts partway along the extrusion — skip those, they're no longer necessary.</p>
</div>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-regular-layers-extrusion-tnut-holes-w1600-b5863688aeea.png" alt="Side view of an A/G extrusion showing the row of holes where T-nuts sit and the screws pass through">
  <figcaption><cite>Photo: zed0.</cite></figcaption>
</figure>

Repeat these steps to make two semi-circles of three sections of A/G extrusion (320mm) and three External bracket — sides, then slot the two half-hexagons together into a full hexagon and secure it with 2 more {% include fastener.html size="M5" variant="socket-button" length="16" %} screws. Joining in this manner, rather than working your way around the hexagon, prevents having to force the brackets into awkward angles.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-regular-layers-two-half-hexagons-full-5e7c0f80f57f.png" alt="Two three-section half-hexagons laid out before being joined into a full hexagon">
  <figcaption><cite>Photo: zed0.</cite></figcaption>
</figure>

Set the ring aside; it goes on last, in step 5.

{% include step.html n="2" title="Slide a spoke and crossbeam together" %}

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/hex-frame-spoke-crossbeam-slide-full-dbf46c1f9948.jpg" alt="A grey B/H spoke and a teal Frame crossbeam slid together over a length of aluminum extrusion, the crossbeam upside down">
  <figcaption><cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

This part of the build has no hardware at all — every joint from here is a slide-in fit. It's a little fiddly, and a second pair of hands helps, but it's doable solo. Until the whole hexagon of spokes is closed the parts can feel loose and want to fall out with a small bump; once it's all together it's stable.

Slide a B/H spoke (158mm) and a Frame crossbeam together. For easy assembly, start with the crossbeam **upside down**.

{% include step.html n="3" title="Continue around the hexagon" %}

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/hex-frame-ring-nearly-closed-full-e0399f3e9cf2.jpg" alt="Five spoke-and-crossbeam joints forming most of a hexagon, one B/H spoke and its extrusion still sitting loose at the open side">
    <figcaption><cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

Repeat step 2 around the hexagon until you have used **6 Frame crossbeams and 5 B/H spokes (158mm)**. Deliberately hold the 6th spoke back — it closes the loop later, in step 7.

{% include step.html n="4" title="Fit 10 of the 12 Frame 90° brackets" %}

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/hex-frame-brackets-ten-on-full-377acf718d17.jpg" alt="The near-complete spoke ring with a Frame 90 degree bracket pair at five of the six spoke junctions, two spare brackets and the loose spoke sitting at the open sixth junction"><figcaption><cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/hex-frame-bracket-seating-closeup-full-ebd9a6cd0532.jpg" alt="Close-up of a Frame 90 degree bracket's short leg seated on the spoke extrusion and its long leg reaching out toward where the outer ring will sit">
    <figcaption><cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

At each of the 5 closed spoke junctions, slide a pair of Frame 90° brackets on: the **short leg onto the spoke**, the **long leg facing outward**. Use 10 brackets for now — hold the last 2 back for the 6th junction, closed in step 7.

{% include step.html n="5" title="Fit the outer ring" %}

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/hex-frame-outer-ring-dropped-on-full-acf8eb045b56.jpg" alt="The outer aluminum hexagon ring from step 1 dropped over the spoke assembly, mostly seated with one corner still proud">
    <figcaption><cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/hex-frame-bracket-leg-in-extrusion-closeup-full-7f60da969225.jpg" alt="Close-up of a Frame 90 degree bracket's long leg slotted into the T-slot channel of the A/G extrusion">
    <figcaption><cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

Grab the outer hexagon ring you set aside in step 1 and place it over the top of the spoke assembly. Wiggle it and apply outward pressure until all 10 long legs of the Frame 90° brackets are slotted into the T-slot channel of the A/G extrusion (320mm) — this is a slide fit, not a screw.

{% include step.html n="6" title="Flip the frame" %}

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/hex-frame-flipped-full-c10c5444b41b.jpg" alt="The assembled frame flipped over, held together with outward pressure on the brackets">
  <figcaption><cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

While holding the brackets in the ring, flip the whole assembly over — outward pressure on the brackets helps keep everything seated as you do. This is not just a change of viewing angle: the spoke assembly flips relative to the outer ring. Once flipped, the frame is the right way up for the finished build. (It's flipped again later, when it's actually attached to the machine — not relevant at this stage.)

{% include step.html n="7" title="Close the ring" %}

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/hex-frame-closing-final-joint-full-0ca2fb7b60c0.jpg" alt="Close-up of the final spoke joint closing, with the last two Frame 90 degree brackets going onto the corner">
  <figcaption><cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

Slide the final B/H spoke (158mm) in from the top to close the ring, then fit the last 2 Frame 90° brackets at that junction.

{% include step.html n="8" title="Check and snug every joint" %}

Double-check that every Frame 90° bracket is still fully seated in its slot. A light hammer tap on each bracket, from the inside of the ring toward the outside, helps snug all the connections.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/hex-frame-finished-top-down-full-c6abfb4dad6e.jpg" alt="A finished hex frame from above, the alternating grey spoke and teal crossbeam pieces forming the inner ring inside the aluminum outer hexagon">
  <figcaption><cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

A hex frame is now complete. Build as many as your machine needs (see the note at the top of this page), then move on to [Bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}), [Bottom two layers]({{ '/hardware/assembly/distribution/bin-frame/bottom-two-layers/' | relative_url }}), [Regular layers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}) or [Top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}) to turn one into the layer you need.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>The fastener counts above cover step 1 only (the outer ring). This page hasn't yet been reconciled against the parts calculator's assembly groupings, which don't currently line up with hex-frame-first construction — see the open discussion in Discord before treating the totals here as final.</p>
</div>
