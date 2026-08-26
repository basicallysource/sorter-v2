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
  post to the adapter, are now measured off the part geometry. The assembly order, the COB
  plate's retention, and every photograph are still missing. Fill it in as you build.
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

The light post is a vertical printed post carrying a 50 mm COB LED plate, which lights the channel from the side so the overhead camera sees parts against an even background. It bolts to a [C-channel]({{ '/hardware/assembly/feeder/c-channel/' | relative_url }})'s NEMA bracket.

The fasteners and quantities in the parts list come from the parts registry and are called out inline at each step. **The list above is one post's worth**, and the machine takes 2, one each on the second and third feeder channels.

{% include fastener-legend.html %}

{% include step.html n="1" title="Preparation" %}

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Light post:</strong> no heat inserts, front or back — every screw here is self-tapping. The 2 M3 × 20 mm screws that hold it to the NEMA bracket, and the 3 M3 × 12 mm that hold the cap adapter on top (Step 2), all thread straight into the print.</p>
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

All 3 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws join the Light post cap adapter down onto the Light post — the cap takes none of them. Measured off the two STLs: the post's top face carries 3 self-tapping pilot holes, 2.8 mm across, spaced 120° apart on a 12.1 mm radius; the adapter has a matching 3.4 mm clearance hole over each one. Screw down through the adapter into the post.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/post-iso-render-full-d45cabf034b8.png" alt="Angled render of the post's top, with the adapter's ring seated over it and two of the three screw pockets visible">
  <figcaption>The joint from a slight angle, adapter seated on the post. Two of the three screw pockets are visible here; the third is on the far side. Rendered from the part geometry, not from a build. Render: Balloon.</figcaption>
</figure>

**Still not recorded:** which way the lobed boss lines up on the adapter — the geometry rules out the two wrong 120°/240° rotations if you match it by eye, but nobody has confirmed which adapter feature it keys to. <span class="fastener-todo">fastener not recorded</span>

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Fit the cap and the COB plate" %}

The Light post cap has no screw holes of its own anywhere in its geometry — it fits over the post-and-adapter assembly without fasteners, so it needs no heat insert either. The 50 mm COB plate mounts inside it, facing across the channel.

**Not recorded:** how the cap is retained (snap or friction fit — the geometry doesn't say which) and what holds the COB plate in place. <span class="fastener-todo">fastener not recorded</span>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The C-channel COB light boards need a current-limiting resistor.</b> <b>220&#8486;, 1/4 W, in series, one per board.</b> Wired straight to 24V a 50 mm COB plate pulls about 0.5A and melts its printed mount. A board fed from a basically board v1.3 LED header already has one on the board. Full detail: <a href="{{ '/hardware/electronics/#43--leds-from-basically-board-v13' | relative_url }}">LEDs, on the wire harness page</a>.</p>
</div>

<div class="img-placeholder">Image coming</div>

{% include step.html n="4" title="Bolt the post to the NEMA bracket" %}

Bolt the post to the C-channel's NEMA bracket with 2 {% include fastener.html size="M3" variant="countersunk" length="20" %} screws, which thread straight into the printed post. No heat insert, no nut.

**Not recorded:** which holes in the bracket they use, and which way the post faces relative to the channel.

<div class="img-placeholder">Image coming</div>

{% include step.html n="5" title="Aim the light" %}

Side lighting is deliberate: overhead COB lighting was tried first and washed out the ArUco tags, see [feeder experiments]({{ '/lab/feeder-experiments/' | relative_url }}).

**Not recorded:** how high the plate sits above the channel and how it is aimed. Both change the camera exposure, so write down what worked.

Build the second post the same way. Wiring is on the [electronics]({{ '/hardware/electronics/' | relative_url }}) page.

<div class="img-placeholder">Image coming</div>
