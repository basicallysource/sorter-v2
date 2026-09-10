---
layout: default
title: Arranging C-channels
type: how-to
section: hardware
slug: assembly-arranging-c-channels
kicker: Feeder — Arranging C-channels
lede: How the four C-channels stand, at what heights, and what passes parts between them.
permalink: /hardware/assembly/feeder/arranging-c-channels/
author: barthel
contributors: [brickcyclealice]
og_image: https://assets.basically.website/sorter-parts/c-channel-stands-all-three-full-9b385f0819e2.jpg
warning: >-
  **AI-generated first draft.** Written from the machine assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=feeder) and measured
  off the published STLs, not from an actual build. The parts, the leg lengths and the 80 mm
  step between channels are real and current, and BrickCycleAlice's photographs of all three
  stands are on Steps 2 and 3 — but no step below has been walked through by a builder. Two
  things are still missing: how far two channels overlap horizontally and where round the
  circle each handover happens, and how the classification channel is fixed down. Fill them
  in as you build.
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

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build all four <a href="{{ '/hardware/assembly/feeder/c-channel/' | relative_url }}">C-channels</a> before you start.</strong> They're required components of this page, not optional or covered here — this page arranges and heights four already-built channels, it doesn't build them. Three with the faceted rotor, one with the finned one.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-stator-and-rotor-fitted-w1600-60758bbee2d5.jpg" alt="A finished C-channel seen from above: the white finned classification rotor sitting inside the grey stator ring, with the stepper motor projecting from the right-hand side">
    <figcaption>A finished C-channel, from the C-channel page. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

Four [C-channels]({{ '/hardware/assembly/feeder/c-channel/' | relative_url }}) are built the same way and then stood at different heights, so a part cascades from one to the next under gravity and arrives at the [interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}) singulated.

C1, C2 and C3 each stand on the same three-piece support structure: a **Layout guide** it stands on, three **support legs** standing in that, and a **Support dovetail adapter** on top of each leg that slides up into the C-channel drive from below. The legs are the only thing that differs between the three channels, and their lengths are what set the drop between one channel and the next. The classification channel has no support structure of its own.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>The Leg, Foot and Leg extension are retired.</strong> Three printed parts stacked with dovetails used to hold each channel up, 9 of each across the feeder. They were replaced on 2026-09-02 by the layout guide, the support legs and the dovetail adapters, and the heights on this page only come out right with the new parts. Don't re-add them from an older photo, an older print list, or a machine built before that date.</p>
</div>

Steps below refer to the channels by the names the software uses, in the order a part travels:

- **C1**, the bulk channel, under the [bulk input]({{ '/hardware/assembly/feeder/bulk-input/' | relative_url }}). Highest.
- **C2**, with a [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}).
- **C3**, the same again, and the last metering stage.
- **The classification channel**, inside the [classification chamber]({{ '/hardware/assembly/feeder/classification-chamber/' | relative_url }}), which images the part before it drops into the chute. Lowest.

{% include step.html n="1" title="Preparation" %}

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Three layout guides, one per channel.</strong> It's a ring about 250 mm across and 28 mm thick, spoked to a hub, with three square sockets standing on it. The same part goes under C1, C2 and C3 — it is <em>not</em> one big base that positions all three channels at once, so print three.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-layout-guide-full-8cf1b8fec1ec.png" alt="Render of the layout guide: a spoked ring with three open square sockets standing on it and a round hub in the middle">
    <figcaption>The Layout guide, one per channel. <cite>Render from the published STL.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Three legs per channel, and each channel's are different.</strong> C1's are 2020 aluminium extrusion cut to 228 mm — piece <strong>J</strong> on the <a href="https://parts-calculator.basically.website/framing">cut list</a>, and the only 2020 in the machine that isn't part of the frame. C2's and C3's are printed, and there's a separate STL for each. Both printed legs are the same shape: a 26 mm square spigot at each end and a fatter body between them, so the only difference is how long the body is.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-support-leg-full-87fa6d93be59.png" alt="Render of the printed C-channel 3 support leg: a square body with a narrower square spigot at each end, each spigot drilled through">
    <figcaption>The C-channel 3 support leg. C2's is the same part with a longer body. <cite>Render from the published STL.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Nine dovetail adapters</strong>, three per channel and the same part on all three. Each is 42 mm tall and in two halves: a 41 mm square block, 20 mm of it, with a socket in its underside that swallows the top 18 mm of a leg, and a 22 mm tapered tang above that goes up into the C-channel drive. <strong>The block's top face is what the channel sits on</strong>, 2 mm above the leg — not the tip of the tang.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-support-dovetail-adapter-full-0a3f5f941324.png" alt="Render of the support dovetail adapter: a square block with a tapered tang standing on it and a hole through one side of the block">
    <figcaption>The Support dovetail adapter. <cite>Render from the published STL.</cite></figcaption>
  </figure>
</div>

<div class="callout">
  <p><strong>There are no fasteners in the stand at all.</strong> Every joint in it is gravity or friction: a leg stands in the layout guide, an adapter sits on a leg, and the three adapters push up into the drive. Nothing here is screwed and nothing takes a heat insert. The printed legs and the adapters do have holes through them — 2 × Ø4.20 in each leg, 2 × Ø5.50 in each adapter — and none of them is fastened. Don't go looking for the screws.</p>
</div>

{% include step.html n="2" title="Stand each channel" %}

Build the same stack three times, once per channel, with that channel's legs:

<ol class="numbered-steps">
  <li>Put the layout guide down flat, sockets up.</li>
  <li>Stand the three legs in it. The sockets are 18 mm deep and the legs are held by their own weight — C1's extrusion, C2's and C3's printed legs.</li>
  <li>Drop a dovetail adapter over the top of each leg. The socket in its underside takes the top 18 mm of the leg, so the block's top face lands 2 mm above the leg on every channel — that face is the seat.</li>
  <li>Lower the built C-channel onto the three tangs so they engage the drive from below. It's a friction fit; the channel's weight holds it.</li>
</ol>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>C1's legs don't fit their sockets closely.</strong> Both sockets — the one in the layout guide and the one under the adapter — are 26 mm square and 18 mm deep, which is what the printed legs' spigots are made to. C1's leg is 2020 extrusion, 20 mm square, so on the STLs it has about 3 mm of slack a side at both ends, and nothing in the parts registry says what takes that up. It goes together — the first photo below is C1 built — but the heights only come out right if the extrusion bottoms out in the socket rather than sitting proud. Worth checking on your own parts.</p>
</div>

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-parts/c-channel-stand-c1-full-408a46f64257.jpg" alt="C1's stand: the layout guide flat on a bench with three 2020 aluminium extrusion legs standing in its sockets, each capped by a printed dovetail adapter">
    <figcaption>C1, on the 228 mm 2020 legs. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-parts/c-channel-stand-c2-full-6c846cbbedd2.jpg" alt="C2's stand: the layout guide with three printed support legs standing in its sockets, each capped by a dovetail adapter">
    <figcaption>C2, on the 148 mm printed legs. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-parts/c-channel-stand-c3-full-8a3466156d18.jpg" alt="C3's stand: the layout guide with three short printed support legs and their dovetail adapters">
    <figcaption>C3, on the 68 mm printed legs. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-stand-adapter-dovetail-full-5476503ba39a.jpg" alt="Close-up of one leg: it stands in the layout guide's square socket at the bottom, and the dovetail adapter caps its top, with a ribbed dovetail rail across the adapter's upper face">
  <figcaption>One leg, both joints. The square socket in the layout guide at the bottom, the adapter over the top of the leg, and the dovetail rail on the adapter's upper face — that rail is what the C-channel drive slides onto. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-stand-c3-side-full-0887a0989be9.jpg" alt="The C3 stand from a lower angle, showing all three dovetail adapters and the way their rails are oriented">
  <figcaption>The same C3 stand from lower down, with all three adapters in view. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

**Not recorded:** how the three legs are clocked around the channel — which of the three sits under the stepper, under the exit, or under the camera lamp arm. The layout guide is exported on its own, so the STLs don't say.

{% include step.html n="3" title="★ Set the heights and the spacing" %}

**The drop is 80 mm per handover, and it's built into the legs.** You don't measure it; you get it by using the right leg on each channel and standing all three layout guides on the same flat surface.

| Channel | Leg | Length |
|---|---|---|
| C1 | `ext-2020-c1`, 2020 extrusion, piece J | 228 mm |
| C2 | C-channel 2 support leg, printed | 148 mm |
| C3 | C-channel 3 support leg, printed | 68 mm |

228, 148, 68 — an even 80 mm step. Every leg sockets the same 18 mm into its guide and carries the same adapter, so the step passes straight through to the drives: measured from the underside of the layout guides, the three seats land at **240 mm, 160 mm and 80 mm**. Another 80 mm below C3 is zero, which is the surface the guides themselves stand on. That's the argument in step 6 for where the classification channel goes.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-parts/c-channel-support-heights-full-a32b5d7f02ad.png" alt="Elevation of the three support stacks side by side, C1 tallest to C3 shortest, with dashed lines marking seat heights at 240, 160 and 80 mm above the surface the layout guides stand on, and 80 mm marked between each pair">
    <figcaption>The three stacks to scale, from the published STLs, with one of each channel's three legs shown. C1's leg is drawn as a plain 20 × 20 × 228 mm extrusion. The dashed lines are the faces the C-channel drives sit on. <cite>Render from the published STLs.</cite></figcaption>
  </figure>
</div>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-stands-all-three-full-9b385f0819e2.jpg" alt="All three stands laid out together, longest legs to shortest, showing the three leg lengths side by side">
  <figcaption>The three stands built, longest to shortest. This is the whole of the height setting: same guide, same adapter, three leg lengths. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<div class="callout">
  <p>Don't add more drop than this to fix bouncing. A part is supposed to arrive at the next rotor with most of its energy gone; a bigger drop makes pieces bounce further and re-clump, which is the problem the cascade exists to solve. If parts are riding round a channel instead of leaving it, that's the <a href="{{ '/hardware/assembly/feeder/output-guides/' | relative_url }}">output guide</a>'s job, not the height's.</p>
</div>

**Still not recorded**, and these are the numbers this page most needs from a real build:

- how far two channels overlap horizontally, which is what fixes where the guides sit relative to one another,
- how far around the circle each handover happens.

<div class="img-placeholder">Image coming</div>

{% include step.html n="4" title="Fit the output guides" %}

One [output guide]({{ '/hardware/assembly/feeder/output-guides/' | relative_url }}) on C2 and one on C3. Each belongs to the channel it is mounted on, not to the gap between two; C1 and the classification channel take none.

<div class="img-placeholder">Image coming</div>

{% include step.html n="5" title="Add the bulk input and the camera lamps" %}

[Bulk input]({{ '/hardware/assembly/feeder/bulk-input/' | relative_url }}) on C1. A [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}) on C2 and on C3 — C1 has neither a lamp nor an output guide, because it's fed in bulk and nothing reads vision off it.

<div class="img-placeholder">Image coming</div>

{% include step.html n="6" title="★ Stand the classification channel" %}

**The classification channel has no support structure in the parts list** — no layout guide, no legs, no adapters. Where its weight goes is the one part of the feeder nobody has written down, and it's been asked in the server twice without an answer.

What the geometry says, which is an inference and not a build: the 80 mm step continues, so C4's seat falls exactly at the level the three layout guides stand on. Resting the drive straight on the [top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }})'s plate puts it at the right height — the stator and the NEMA bracket bottom out together and the stepper mounts on the bracket's upper face, so nothing hangs below the seating plane to foul the plate. What that doesn't give you is anything holding it down or setting which way it's clocked. The top plate has no mount holes for a C-channel.

**If you work this out on your own machine, it's the single most useful thing you could send back.** <span class="fastener-todo">not recorded</span>

<div class="img-placeholder">Image coming</div>

{% include step.html n="7" title="Turn it all by hand" %}

Run parts through the whole cascade by hand, one channel at a time, before wiring the steppers. Anything that needs a nudge here will jam under power. Wiring is on the [electronics]({{ '/hardware/electronics/' | relative_url }}) page.

<div class="img-placeholder">Image coming</div>
