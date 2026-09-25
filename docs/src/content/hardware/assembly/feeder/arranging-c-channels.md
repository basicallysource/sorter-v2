---
layout: default
title: Arranging C-channels
type: how-to
section: hardware
slug: assembly-arranging-c-channels
kicker: Feeder — Arranging C-channels
lede: The stands the four C-channels sit on, the heights they set, and the order the channels go onto the top plate.
permalink: /hardware/assembly/feeder/arranging-c-channels/
author: barthel
contributors: [brickcyclealice, daddyosbricksbill, reveryx]
og_image: https://assets.basically.website/sorter-parts/c-channel-drives-all-four-full-44246243494e.jpg
last_verified: 2026-09-25
parts_needed:
  - part: layout-guide
    qty: 3
  - part: ext-2020-c1
    qty: 3
  - part: channel-two-support-leg
    qty: 3
  - part: channel-three-support-leg
    qty: 3
  - part: support-dovetail-adapter
    qty: 9
---

**Four finished channels go on this page. It does not build any of them.**

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>One <a href="{{ '/hardware/assembly/feeder/c-channels/bulk-channel/' | relative_url }}">bulk channel</a>, C1.</strong> The faceted rotor in, and the Bulk cap on the stator.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-bulk-channel-cap-fitted-w1600-f75843bda905.jpg" alt="A finished C1 on the bench: the tall cylindrical bulk cap seated on the channel below it, its outlet opening at the front right, the stepper motor at the front with its lead coiled">
    <figcaption>C1, cap on. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Two <a href="{{ '/hardware/assembly/feeder/c-channels/feeder-channels/' | relative_url }}">feeder channels</a>, C2 and C3.</strong> The faceted rotor in and an output guide on. They are the same build; only the height differs, and that is set here.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-finished-stage-w1600-9bd3719c4180.jpg" alt="A C-channel from above on a plain surface: the faceted rotor sitting down in the stator ring, with the stepper motor and its lead standing off one side">
    <figcaption>A feeder channel, rotor in. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>One <a href="{{ '/hardware/assembly/feeder/c-channels/classification-channel/' | relative_url }}">classification channel</a>, C4.</strong> The finned rotor, capped. It is the only one of the four with no support structure of its own.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/render-classification-channel-finished-full-683c6f99f962.png" alt="Render of the finished classification channel: the finned rotor sitting down in the stator ring with its cap seated in the middle of it, its fins running out to the rim">
    <figcaption>C4, capped rotor in. <cite>Rendered from the part geometry, not from a build.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Three <a href="{{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}">camera lamps</a>.</strong> Two feeder lamps and one classification lamp. C1 takes none.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-ov9732-lead-routing-w1600-e5c818271b94.jpg" alt="The lamp on channel 3 from a low angle: the camera board in the cover's opening, the red and black lamp leads cable-tied to the arm, and the rectangular slot in the cover below the board">
    <figcaption>A finished camera lamp. <cite>Photo: Daddy-O's Bricks - Bill.</cite></figcaption>
  </figure>
</div>

The four stand at different heights, so a part cascades from one to the next under gravity and arrives at the [interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}) singulated.

C1, C2 and C3 each stand on their own three-legged stand, and **the legs are the only thing that differs between them**: their lengths are what set the drop from one channel to the next. C4 has no stand at all. It sits flat on the top plate, located by C3's layout guide, and it goes in before the other three.

Steps below use the names the software uses, C1 to C4, in the order a part travels: C1 highest, C4 lowest.

{% include step.html n="1" title="Build C1's stand" %}

The tallest one. Three moves, and they are the same three on every channel:

<ol class="numbered-steps">
  <li>Put a layout guide down flat, sockets up.</li>
  <li>Stand the three legs in it. C1's are <strong>C-channel 1 support leg</strong>, 228 mm of 2020 extrusion, <strong>piece J</strong> on the <a href="https://parts-calculator.basically.website/framing">framing list</a>. They are held by their own weight.</li>
  <li>Drop a dovetail adapter over the top of each leg. <strong>The adapter's flat top face is what the channel sits on</strong>, not the tip of the tang above it.</li>
</ol>

The channel itself goes on later, in step 6, once all three stands are laid out and C4 is in.

<div class="callout">
  <p><strong>How the 2020 sits at each end.</strong> Into the layout guide it slides with a firm fit. At the adapter it is only braced on three sides. <cite>Tip: BrickCycleAlice.</cite></p>
</div>

<div class="callout">
  <p><strong>Nothing in the stand is fastened.</strong> Every joint is gravity or friction, so there are no screws in the parts list and nothing takes a heat insert. Don't go looking for them.</p>
  <p><strong>Pinning a stand is optional, and none of it is counted anywhere.</strong> If you want to, the legs and adapters have holes for it: an {% include fastener.html size="M5" variant="socket-button" length="16" %} goes through the adapter and cuts its own thread in a printed leg. <strong>C1's legs are extrusion, not printed</strong>, so those need an {% include fastener.html size="M5" variant="t-nut" %} in the slot for the screw to pull against. C1 is the one worth pinning, because it carries the bulk bin.</p>
</div>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-stand-c1-full-408a46f64257.jpg" alt="C1's stand: the layout guide flat on a bench with three 2020 aluminium extrusion legs standing in its sockets, each capped by a printed dovetail adapter">
  <figcaption>C1's stand, on its three 2020 legs. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="2" title="Build C2's stand" %}

The same three moves, with three **C-channel 2 support legs**, printed.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-stand-c2-full-6c846cbbedd2.jpg" alt="C2's stand: the layout guide with three printed support legs standing in its sockets, each capped by a dovetail adapter">
  <figcaption>C2's stand, on its three printed legs. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-stand-adapter-dovetail-full-5476503ba39a.jpg" alt="Close-up of one leg: it stands in the layout guide's square socket at the bottom, and the dovetail adapter caps its top, with a ribbed dovetail rail across the adapter's upper face">
  <figcaption>One leg of that stand, both joints. The square socket in the layout guide at the bottom, the adapter over the top of the leg, and the dovetail rail on the adapter's upper face — that rail is what the C-channel drive slides onto. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="3" title="Build C3's stand" %}

The same again, with three **C-channel 3 support legs**, printed.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-stand-c3-full-8a3466156d18.jpg" alt="C3's stand: the layout guide with three short printed support legs and their dovetail adapters">
  <figcaption>C3's stand, on its three printed legs. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-stand-c3-side-full-0887a0989be9.jpg" alt="The C3 stand from a lower angle, showing all three dovetail adapters and the way their rails are oriented">
  <figcaption>The same stand from lower down, with all three adapters in view. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="4" title="Lay the three stands out" %}

Put all three on the [top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }})'s top plate. **The drop between channels comes out of this on its own.** You do not measure it: each channel has its own leg, and standing all three guides on the same flat surface sets the rest.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-parts/c-channel-support-heights-full-a32b5d7f02ad.png" alt="Elevation of the three support stacks side by side, C1 tallest to C3 shortest, with dashed lines marking seat heights at 240, 160 and 80 mm above the surface the layout guides stand on, and 80 mm marked between each pair">
    <figcaption>The three stacks to scale, with one of each channel's three legs shown. The dashed lines are the faces the C-channel drives sit on, and C4 sits on the plate itself, the same step again below C3. <cite>Render from the published STLs.</cite></figcaption>
  </figure>
</div>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-stands-all-three-full-9b385f0819e2.jpg" alt="All three stands laid out together, longest legs to shortest, showing the three leg lengths side by side">
  <figcaption>The three stands built, longest to shortest. Same guide, same adapter, three different legs. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<div class="callout">
  <p><strong>Clock all three the same way, with the steppers toward the centre of the guides.</strong> Nothing in the STLs says which of a channel's three legs sits under the motor — the layout guide is exported on its own — so this is how it is actually built. <cite>Tip: BrickCycleAlice.</cite></p>
</div>

<div class="callout">
  <p>Don't add more drop than this to fix bouncing. A part is supposed to arrive at the next rotor with most of its energy gone; a bigger drop makes pieces bounce further and re-clump, which is the problem the cascade exists to solve. If parts are riding round a channel instead of leaving it, that's the <a href="{{ '/hardware/assembly/feeder/c-channels/feeder-channels/' | relative_url }}">output guide</a>'s job, not the height's.</p>
</div>

{% include step.html n="5" title="Install the classification channel" %}

C4 goes in first, before the three above it, and it takes **no support structure of its own** — no layout guide, no legs, no adapters. It sits flat on the top plate and slides onto the layout guide that C3 stands in.

The top plate itself has no mount holes for a C-channel, so nothing bolts down here.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-c4-on-c3-guide-full-574058daee19.jpg" alt="The classification channel's drive, stator ring with its stepper motor on the bracket, slid onto the layout guide that C3 stands in, with the three stands lying around it">
  <figcaption>The classification channel's drive slid onto C3's layout guide, with the three stands beside it. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="6" title="Install C1, C2 and C3" %}

Now the other three drives go on their stands. Lower each one onto its three dovetail adapters so the tangs engage it from below. It's a friction fit; the channel's own weight holds it.

The drive in the photograph below has no rotor in it, which is the only way to see the joints; yours arrive from the channel pages with theirs already in. It also shows the clocking from step 4: every stepper ends up in the middle of the group.

<figure class="single-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-drives-three-on-full-0fb34fea7ae4.jpg" alt="Three C-channel drives sitting on their stands with no rotors fitted, the fourth stand still empty beside them, all the steppers pointing into the middle of the group">
    <figcaption>Three drives on, one stand still empty. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="7" title="Hang the camera lamps" %}

One [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}) on C2, one on C3 and one on C4. **C1 takes none**, because it's fed in bulk and nothing reads vision off it.

**Which dovetail the arm goes in.** The outside of every channel wall carries a row of dovetails, evenly spaced all the way round except where the exit opening interrupts them. Count anticlockwise from the exit, seen from above, taking the first dovetail past the exit as number 1:

- **C2 and C3**: the **5th**.
- **C4**: the **8th**, which is the last one before the channel above covers the wall.

**It goes on from underneath.** Offer the arm mount up to the bottom edge of the channel wall, feed its rail into the dovetail, and push it up until it clips over the top edge. Nothing screws into this joint.

A camera has to see its channel's drop zone and its exit in the same frame. You check that at [first setup]({{ '/sorter/first-setup/' | relative_url }}) step 7; if one cannot, its lamp is in the wrong dovetail.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>The dovetail on the arm can break</strong> when a lamp needs to be removed and repositioned. Use caution if repositioning is needed.</p>
</div>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-dovetail-c3-w1600-85089c63ca95.jpg" alt="A standing C-channel from outside, the grey camera lamp arm mount running down the wall with its LED leads cable-tied to it, and its foot in one of the dovetails in the bottom edge of the wall">
    <figcaption>C3, with the arm mount home in its 5th dovetail. C2 is the same. <cite>Photo: Daddy-O's Bricks - Bill.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-dovetail-classification-w1600-bb7f28e0d58c.jpg" alt="The classification channel with its lamp overhead, the arm coming down the outside of the wall to the dovetail, and the finned rotor visible in the channel below">
    <figcaption>A lamp on its channel, the arm coming down the outside of the wall to its dovetail. <cite>Photo: Daddy-O's Bricks - Bill.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-arm-mount-seated-w1600-ff6fd6c3355d.jpg" alt="Close view of the arm mount seated on a channel: the ribbed rail of the mount home in the dovetail and clipped over the wall's top edge, with the arm bracket and two countersunk screws beside it">
    <figcaption>Seated. The rail is fully home in the dovetail and the mount sits flat against the wall. <cite>Photo: Daddy-O's Bricks - Bill.</cite></figcaption>
  </figure>
</div>

{% include step.html n="8" title="Turn it all by hand" %}

Run parts through the whole cascade by hand, one channel at a time, before wiring the steppers. Anything that needs a nudge here will jam under power. Wiring is on the [electronics]({{ '/hardware/electronics/' | relative_url }}) page.

## The finished result

Four channels standing at their own heights, each one dropping into the next.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-drives-all-four-full-44246243494e.jpg" alt="All four C-channel drives standing arranged on the top plate, seen from above, their stepper motors gathered together at the centre of the group">
  <figcaption>The four arranged, seen from above. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

Back to the [feeder]({{ '/hardware/assembly/feeder/' | relative_url }}).
