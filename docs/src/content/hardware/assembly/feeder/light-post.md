---
layout: default
title: Light post
type: how-to
section: hardware
slug: assembly-light-post
kicker: Feeder — Light post
lede: The vertical COB light that lights a C-channel for the overhead camera.
permalink: /hardware/assembly/feeder/light-post/
author: barthel
warning: >-
  **AI-generated first draft, mounting order still unbuilt.** Written from the machine assembly
  tree in the [parts calculator](https://parts-calculator.basically.website/assembly?focus=light-post),
  not from an actual build. The two screws into the NEMA bracket, and the three that join the
  post to the adapter, are now measured off the part geometry, and Spencer's bench photographs
  below are of a built post. The order the parts go together in, how the cap is retained, and
  how the post is aimed are still missing. Fill it in as you build.
og_image: https://assets.basically.website/sorter-parts/light-post-assembled-full-2b59e7e84bdb.jpg
parts_needed:
  - part: light-post
    qty: 1
  - part: light-post-cap
    qty: 1
  - part: light-post-cap-adapter
    qty: 1
  - part: led-cob-50mm-24v
    qty: 1
  - part: scr-m3-12-cs
    qty: 3
  - part: scr-m3-20-cs
    qty: 2
---

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">&#9888;</span>
  <p><b>This part is retired.</b> It was replaced on 2026-09-02 by the <a href="{{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}">camera lamp</a>, one per channel, which carries both the light and the camera. This page is kept for machines already built this way. Do not print or buy these parts for a new build.</p>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/feeder/c-channel/' | relative_url }}">C-channel</a> before you start.</strong> It's a required component of this page, not optional or covered here — Step 4 bolts the post onto one's NEMA bracket, it doesn't build one.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-stator-and-rotor-fitted-w1600-60758bbee2d5.jpg" alt="A finished C-channel seen from above: the white finned classification rotor sitting inside the grey stator ring, with the stepper motor projecting from the right-hand side">
    <figcaption>A finished C-channel, from the C-channel page. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

The light post is a vertical printed post carrying a 50 mm COB LED plate, which lights the channel from the side so the overhead camera sees parts against an even background. It bolts to a [C-channel]({{ '/hardware/assembly/feeder/c-channel/' | relative_url }})'s NEMA bracket.

The fasteners and quantities in the parts list come from the parts registry and are called out inline at each step. **The list above is one post's worth**, and the machine takes 2, one each on C2 and C3.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/light-post-assembled-full-2b59e7e84bdb.jpg" alt="A finished light post on the bench: the black printed post with the 50 mm COB plate on its end, and the red and black leads running out of the post to a DC barrel plug">
  <figcaption>A finished post: the plate on the end, the leads leaving the bottom on a barrel plug. <cite>Photo: Spencer.</cite></figcaption>
</figure>

{% include fastener-legend.html %}

{% include step.html n="1" title="Preparation" %}

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Light post:</strong> no heat inserts, front or back — every screw here is self-tapping. The 2 × {% include fastener.html size="M3" variant="countersunk" length="20" %} screws that hold it to the NEMA bracket (Step 4), and the 3 × {% include fastener.html size="M3" variant="countersunk" length="12" %} that hold the cap adapter on top (Step 2), all thread straight into the print.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Light post cap:</strong> prints white, so it does not soak up the light it is carrying. Whether it takes an insert for the COB plate is not recorded.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

The post and the cap adapter follow the feeder colour.

{% include step.html n="2" title="Screw the adapter to the post" %}

Put the COB plate on the post's end first, leads down through the centre, then the Light post cap adapter over it. All 3 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws go down through the adapter and the plate into the post, so the plate is clamped between the two. The cap takes none of them.

Measured off the two STLs: the post's top face carries 3 self-tapping pilot holes, 2.8 mm across, spaced 120° apart on a 12.1 mm radius; the adapter has a matching 3.4 mm clearance hole over each one.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/post-iso-render-full-d45cabf034b8.png" alt="Angled render of the post's top, with the adapter's ring seated over it and two of the three screw pockets visible">
  <figcaption>The joint from a slight angle, adapter seated on the post. Two of the three screw pockets are visible here; the third is on the far side. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

**Not recorded:** which way the lobed boss lines up on the adapter — the geometry rules out the two wrong 120°/240° rotations if you match it by eye, but nobody has confirmed which adapter feature it keys to. <span class="fastener-todo">fastener not recorded</span>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/light-post-top-cap-off-full-d076a7bff4a1.jpg" alt="The end of the post with the cap off: the aluminium back of the COB plate with the black cap adapter on it, three countersunk screws going down through both into the post, and the leads coming up through the centre hole">
    <figcaption>The joint from the back, cap off: the adapter on the plate, its three screws through both into the post. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/light-post-led-side-full-428b89ff9243.jpg" alt="The LED side of the COB plate, close up: the post's forked end holds the plate at its centre, with the leads passing through the centre hole">
    <figcaption>The same joint from the front, the post's forked end at the plate's centre. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

{% include step.html n="3" title="Fit the cap over it" %}

The Light post cap has no screw holes of its own anywhere in its geometry — it fits over the post-and-adapter assembly without fasteners, so it needs no heat insert either. The plate faces across the channel, LEDs outward.

**Not recorded:** how the cap is retained (snap or friction fit — the geometry doesn't say which). <span class="fastener-todo">fastener not recorded</span>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The C-channel COB light boards need a current-limiting resistor.</b> <b>220&#8486;, 1/4 W, in series, one per board.</b> Wired straight to 24V a 50 mm COB plate pulls about 0.5A and melts its printed mount. A board fed from a basically board v1.3 LED header already has one on the board. Full detail: <a href="{{ '/hardware/electronics/#43--leds-from-basically-board-v13' | relative_url }}">LEDs, on the wire harness page</a>.</p>
</div>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/light-post-led-side-centre-full-b25b6589047d.jpg" alt="The LED side of the COB plate straight on: the post's forked end at the centre with the leads leaving through it">
  <figcaption>The face that lights the channel, straight on. The leads leave through the centre of the plate. <cite>Photo: Spencer.</cite></figcaption>
</figure>

{% include step.html n="4" title="Bolt the post to the NEMA bracket" %}

Bolt the post to the C-channel's NEMA bracket with 2 {% include fastener.html size="M3" variant="countersunk" length="20" %} screws, which thread straight into the printed post. No heat insert, no nut.

**Not recorded:** which holes in the bracket they use, and which way the post faces relative to the channel.

<div class="img-placeholder">Image coming</div>

{% include step.html n="5" title="Aim the light" %}

Side lighting is deliberate: overhead COB lighting was tried first and washed out the ArUco tags, see [feeder experiments]({{ '/lab/feeder-experiments/' | relative_url }}).

**Not recorded:** how high the plate sits above the channel and how it is aimed. Both change the camera exposure, so write down what worked.

Build the second post the same way. Wiring is on the [electronics]({{ '/hardware/electronics/' | relative_url }}) page.

<div class="img-placeholder">Image coming</div>
