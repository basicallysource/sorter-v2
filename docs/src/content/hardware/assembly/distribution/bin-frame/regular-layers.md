---
layout: default
title: Regular layers
type: how-to
section: hardware
slug: assembly-regular-layers
kicker: Bin frame — Regular layers
lede: The repeating bin layers above the base. Build N−2 for an N-layer machine.
permalink: /hardware/assembly/distribution/bin-frame/regular-layers/
parts_needed:
  - part: ext-bracket-left
    qty: 6
  - part: ext-bracket-cover
    qty: 6
  - part: ext-bracket-bottom-vertical
    qty: 6
  - part: frame-90deg-bracket
    qty: 12
  - part: frame-crossbeam
    qty: 6
  - part: bin-retainer-left
    qty: 6
  - part: bin-retainer-right
    qty: 6
  - part: scr-m5-12-shcs
  - part: scr-m5-16-shcs
  - part: scr-m5-20-shcs
  - part: tnut-m5-2020
---

Build N−2 regular layers for an N-layer machine — the bottom two are covered by the [bottom two layers]({{ '/hardware/assembly/distribution/bin-frame/bottom-two-layers/' | relative_url }}). This is also the basis for the top and bottom layers, so you will run through it more than once.

Some of the ordering below may look unusual. It is written this way to avoid putting unnecessary strain on pieces, and to leave room for slide-in T-nuts where you want them.

<div class="callout">
  <p>Every joint here can be fastened two ways: <strong>self-tap</strong> an M5 screw directly into the printed bracket (or through the extrusion, bracing against it), or drop a <strong>T-nut</strong> into the extrusion and screw into that. Slide-in T-nuts have to go in before the ends of the extrusion are closed off; drop-in and roll-in T-nuts can be added at any point. Which route you pick changes the exact screw and T-nut counts, so the parts list above names the fasteners without fixing a quantity.</p>
</div>

**Extrusion pieces** (aluminum, cut to length), per layer:

| Piece | Name | Qty |
|---|---|---|
| A/G | Outer horizontal / Horizontal interface frame | 6 |
| B/H | Spoke / Interface spoke (short) | 6 |
| C | Layer vertical support | 6 |

{% include step.html n="1" title="Assemble the frame brackets" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/LWruBv-fMz4"
    title="Assembling the frame brackets"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Slide piece A/G (Outer horizontal / Horizontal interface frame) into an External bracket — side. Use an M5 × 16 mm screw to tap directly through the outer of the two adjacent holes on the bracket, bracing it against the extrusion. If you would rather not tap and brace, put T-nuts in the extrusion and use the inner holes to fasten into them instead.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/frame-corner-joint.063fa3cadd0c1934.png" alt="Two A/G aluminum extrusions meeting at an External bracket — side, forming one corner of the hexagon">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/frame-corner-joint-angled.ac67d9bc6bce967a.png" alt="Angled view of the same corner joint, showing the fasteners along the extrusion">
  </figure>
</div>

If you are using slide-in T-nuts rather than drop-in or roll-in T-nuts, insert 2 into the innermost section of the extrusion and 4 into the outermost section before you connect the next External bracket — side. This is the last time the ends of the extrusion are accessible.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/extrusion-tnut-holes.a5cd7a57ac7338f4.png" alt="Side view of an A/G extrusion showing the row of holes where T-nuts sit and the screws pass through">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/extrusion-into-bracket.b977c4a0bcefd0d0.png" alt="An A/G extrusion sliding into an External bracket — side">
  </figure>
</div>

Repeat to make two semi-circles, each of three sections of extrusion and three External bracket — sides. Then slot the two half-hexagons together into a full hexagon and secure it with 2 more M5 × 16 mm button head screws. Joining this way, rather than working your way around the hexagon, avoids forcing the brackets into awkward angles.

<img class="doc-figure" src="https://img.basically.website/web/assembly/regular-layers/two-half-hexagons.de6425b1945641e1.png" alt="Two three-section half-hexagons laid out before being joined into a full hexagon">

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/hexagon-assembled.7ea6820b0d0d9ce3.png" alt="The completed hexagon frame of six A/G extrusions and six corner brackets">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/hexagon-assembled-top.0fdfcc70f7a2377b.png" alt="Top-down view of the completed hexagon frame">
  </figure>
</div>

{% include step.html n="2" title="Attach the spokes" %}

Prepare 12 Frame 90° brackets by drilling out the holes on the long side so an M5 screw can rotate freely. No drill of the right diameter? Overtighten an M5 screw with an electric screwdriver to break the threads out instead.

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/ULeByfqfVZs"
    title="Preparing the Frame 90° brackets and attaching the spokes"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Loosely attach the long side of 2 Frame 90° brackets to the inner face of one A/G extrusion using 2 M5 × 12 mm screws, either into your existing slide-in T-nuts or with drop-in / roll-in T-nuts. Slide piece B/H (Spoke / Interface spoke (short)) into the two brackets and secure it with 2 M5 × 16 mm screws tapped into the Frame 90° brackets, bracing against the extrusion. Now tighten the M5 × 12 mm screws that were holding the brackets loosely.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/spoke-brackets-attached.d9ac4d500ee3b690.png" alt="Two Frame 90° brackets fastened to the inner face of an A/G extrusion, seen from inside the hexagon">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/spoke-installed.63790c0e4cedaa87.png" alt="A B/H spoke extrusion standing up in the two Frame 90° brackets">
  </figure>
</div>

On each side of this B/H spoke, slide a Frame crossbeam into place until it is level with the end of the extrusion, and secure it with an M5 × 20 mm screw. Do this on every second side of the hexagon, so on three spokes in total.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/spoke-crossbeams-first.c0d2b9ecfe878b3a.png" alt="A spoke with a Frame crossbeam slid into place on each side">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/spokes-crossbeams-top.65a5a6b0c434cf18.png" alt="Top-down view of three spokes with crossbeams, forming a partial inner ring">
  </figure>
</div>

On each of the remaining 3 sides, use 2 M5 × 12 mm screws to loosely fasten 2 Frame 90° brackets, aligning them with the gap in the crossbeams. Slide the remaining B/H pieces into the slots, through both the crossbeams and the brackets. Secure them with 2 M5 × 16 mm screws tapped into the Frame 90° brackets and 2 M5 × 20 mm screws through the crossbeams, then tighten the M5 × 12 mm screws.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/spokes-progress-1.d298d9db0a731a4d.png" alt="The hexagon partway through spoke installation, some sides done">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/spokes-progress-2.2bfc863a0d215b56.png" alt="More spokes and crossbeams filled in around the hexagon">
  </figure>
</div>

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/spokes-progress-3.8606bb1a9265097c.png" alt="Nearly all spokes and crossbeams installed">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/spokes-nearly-complete.5659132ade9d5c80.png" alt="The spoke ring almost complete, seen at an angle">
  </figure>
</div>

<img class="doc-figure" src="https://img.basically.website/web/assembly/regular-layers/spokes-complete-top.69a43b6af97c12ea.png" alt="Top-down view of the finished hexagon with all six spokes and crossbeams forming the central ring">

<div class="callout">
  <p>If you are building the interface layer, stop here and return to the interface layer guide.</p>
</div>

{% include step.html n="3" title="Install the verticals" %}

On each corner, slot an External bracket — cover onto the External bracket — side (do this before the extrusion goes in, it is tricky to fit afterwards). Slot piece C (Layer vertical support) between the cover and the side bracket. At typical cut length you can leave it 3 mm short at either end, so aim to sit it about 3 mm above the bottom. Secure it with 2 M5 × 16 mm screws tapped through the holes near the bottom of the External bracket — side.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/vertical-corner-detail.1bcb7ad18dd2eda4.png" alt="A corner with piece C vertical extrusion held between the External bracket — cover and the External bracket — side, seen from below">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/verticals-installed.4b2855e18b1b3061.png" alt="The hexagon with vertical supports standing up at each corner">
  </figure>
</div>

On each corner, slide an External bracket — bottom vertical onto piece C, making sure the angles align at the bottom. Secure it with 2 M5 × 16 mm screws through the outer holes on the bottom vertical bracket. The extrusion will likely rest a few mm below the top.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/vertical-bottom-bracket.1c195fdb2d5c3184.png" alt="Close-up of an External bracket — bottom vertical at the base of a corner vertical extrusion">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/regular-layers/verticals-top.29e60bff7b3c77d6.png" alt="Top view of the layer with vertical supports and bottom brackets at every corner">
  </figure>
</div>

{% include step.html n="4" title="Add the bin retainers" %}

On each side of the hexagon, attach both the Bin retainer (left) and the Bin retainer (right) to the front face of A/G using 4 M5 × 12 mm screws, either into the T-nuts already there or with drop-in / roll-in T-nuts.

<img class="doc-figure" src="https://img.basically.website/web/assembly/regular-layers/bin-retainers-installed.1abad654cdf254ea.png" alt="Bin retainers fastened to the outer faces of the hexagon frame">

A regular layer is now complete. You will also need to build a [Chute core]({{ '/hardware/assembly/distribution/chute/' | relative_url }}) for each layer.
