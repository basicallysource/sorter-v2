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
last_verified: 2026-09-10
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
    <p><strong>Build all four <a href="{{ '/hardware/assembly/feeder/c-channels/' | relative_url }}">C-channels</a> before you start.</strong> They're required components of this page, not optional or covered here — this page arranges and heights four already-built channels, it doesn't build them. Three with the faceted rotor, one with the finned one.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-finished-stage-w1600-9bd3719c4180.jpg" alt="A finished C-channel: the grey finned rotor sitting down in the grey stator ring, with the stepper motor and its lead standing off one side">
    <figcaption>A finished C-channel, from the C-channels pages. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

Four [C-channels]({{ '/hardware/assembly/feeder/c-channels/' | relative_url }}) are built on the same core and then stood at different heights, so a part cascades from one to the next under gravity and arrives at the [interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}) singulated.

C1, C2 and C3 each stand on the same three-piece support structure: a **Layout guide** it stands on, three **support legs** standing in that, and a **Support dovetail adapter** on top of each leg that slides up into the C-channel drive from below. The legs are the only thing that differs between the three channels, and their lengths are what set the drop between one channel and the next. The classification channel has no support structure of its own: it stands on the top plate and is located by C3's layout guide (step 6), and it goes in before the other three.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>The Leg, Foot and Leg extension are retired.</strong> Three printed parts stacked with dovetails used to hold each channel up, 9 of each across the feeder. They were replaced on 2026-09-02 by the layout guide, the support legs and the dovetail adapters, and the heights on this page only come out right with the new parts. Don't re-add them from an older photo, an older print list, or a machine built before that date.</p>
</div>

Steps below refer to the channels by the names the software uses, in the order a part travels:

- **C1**, the [bulk channel]({{ '/hardware/assembly/feeder/c-channels/bulk-channel/' | relative_url }}), where parts go in. Highest.
- **C2**, with a [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}).
- **C3**, the same again, and the last metering stage.
- **The [classification channel]({{ '/hardware/assembly/feeder/c-channels/classification-channel/' | relative_url }})**, which images the part before it drops into the chute. Lowest.

**The camera lamps go on here**, once the channels are standing in their places rather than while a channel is on the bench: each one hangs off the dovetail on the bottom of its arm mount, onto the bottom of that channel's NEMA bracket. C2, C3 and the classification channel take one each. See [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}).

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
  <p><strong>There are no fasteners in the stand at all.</strong> Every joint in it is gravity or friction: a leg stands in the layout guide, an adapter sits on a leg, and the three adapters push up into the drive. Nothing here is screwed and nothing takes a heat insert. The printed legs and the adapters do have holes through them — 2 × Ø4.20 in each leg, 2 × Ø5.50 in each adapter — and none of them is fastened. Don't go looking for the screws. There is a case for adding one on C1, which carries the bulk bin; see step 2.</p>
</div>

{% include step.html n="2" title="Build C1's stand" %}

The tallest one. Three moves, and they are the same three on every channel:

<ol class="numbered-steps">
  <li>Put a layout guide down flat, sockets up.</li>
  <li>Stand the three legs in it — for C1, the 228 mm lengths of 2020. The sockets are 18 mm deep and the legs are held by their own weight.</li>
  <li>Drop a dovetail adapter over the top of each leg. The socket in its underside takes the top 18 mm of the leg, so the block's top face lands 2 mm above it. That face is what the channel will sit on.</li>
</ol>

The channel itself goes on later, in step 7, once all three stands are laid out and the classification channel is in.

<div class="callout">
  <p><strong>How the 2020 sits at each end.</strong> Into the layout guide it slides with a firm fit. At the adapter it is only braced on three sides. Nothing is fastened at either end, here or anywhere else in the stand. <cite>Tip: BrickCycleAlice.</cite></p>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>C1 carries the bulk bin, and a full bin is heavy.</strong> The stand is a friction fit end to end and nothing stops the drive lifting off its adapters, so a machine that gets leaned on — or refilled by someone using the feeder to steady themselves — is worth bolting. Which T-nut and bolt suit the 2020 legs hasn't been settled, so there is no combination to quote here yet.</p>
</div>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-stand-c1-full-408a46f64257.jpg" alt="C1's stand: the layout guide flat on a bench with three 2020 aluminium extrusion legs standing in its sockets, each capped by a printed dovetail adapter">
  <figcaption>C1's stand, on the 228 mm 2020 legs. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="3" title="Build C2's stand" %}

The same three moves, with the **148 mm printed** legs.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-stand-c2-full-6c846cbbedd2.jpg" alt="C2's stand: the layout guide with three printed support legs standing in its sockets, each capped by a dovetail adapter">
  <figcaption>C2's stand, on the 148 mm printed legs. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-stand-adapter-dovetail-full-5476503ba39a.jpg" alt="Close-up of one leg: it stands in the layout guide's square socket at the bottom, and the dovetail adapter caps its top, with a ribbed dovetail rail across the adapter's upper face">
  <figcaption>One leg of that stand, both joints. The square socket in the layout guide at the bottom, the adapter over the top of the leg, and the dovetail rail on the adapter's upper face — that rail is what the C-channel drive slides onto. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="4" title="Build C3's stand" %}

The same again, with the **68 mm printed** legs.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-stand-c3-full-8a3466156d18.jpg" alt="C3's stand: the layout guide with three short printed support legs and their dovetail adapters">
  <figcaption>C3's stand, on the 68 mm printed legs. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-stand-c3-side-full-0887a0989be9.jpg" alt="The C3 stand from a lower angle, showing all three dovetail adapters and the way their rails are oriented">
  <figcaption>The same stand from lower down, with all three adapters in view. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="5" title="Lay the three stands out" %}

Put all three on the [top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }})'s top plate. **The drop between channels comes out of this on its own** — you don't measure it, you get it by using the right leg on each channel and standing all three guides on the same flat surface.

| Channel | Leg | Length |
|---|---|---|
| C1 | `ext-2020-c1`, 2020 extrusion, piece J | 228 mm |
| C2 | C-channel 2 support leg, printed | 148 mm |
| C3 | C-channel 3 support leg, printed | 68 mm |

228, 148, 68 — an even **80 mm step**. Every leg sockets the same 18 mm into its guide and carries the same adapter, so the step passes straight through to the drives: measured from the underside of the layout guides, the three seats land at **240 mm, 160 mm and 80 mm**. Another 80 mm below C3 is zero, which is the plate itself, and that is where the classification channel goes.

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
  <p><strong>Clock all three the same way, with the steppers toward the centre of the guides.</strong> Nothing in the STLs says which of a channel's three legs sits under the motor — the layout guide is exported on its own — so this is how it is actually built. <cite>Tip: BrickCycleAlice.</cite></p>
</div>

<div class="callout">
  <p>Don't add more drop than this to fix bouncing. A part is supposed to arrive at the next rotor with most of its energy gone; a bigger drop makes pieces bounce further and re-clump, which is the problem the cascade exists to solve. If parts are riding round a channel instead of leaving it, that's the <a href="{{ '/hardware/assembly/feeder/c-channels/feeder-channels/' | relative_url }}">output guide</a>'s job, not the height's.</p>
</div>

{% include step.html n="6" title="Install the classification channel" %}

C4 goes in first, before the three above it, and it takes **no support structure of its own** — no layout guide, no legs, no adapters. It sits flat on the top plate and slides onto the layout guide that C3 stands in.

The top plate itself has no mount holes for a C-channel, so nothing bolts down here.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/c-channel-c4-on-c3-guide-full-574058daee19.jpg" alt="The classification channel's drive, stator ring with its stepper motor on the bracket, slid onto the layout guide that C3 stands in, with the three stands lying around it">
  <figcaption>The classification channel's drive slid onto C3's layout guide, with the three stands beside it. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="7" title="Install C1, C2 and C3" %}

Now the other three drives go on their stands. Lower each one onto its three dovetail adapters so the tangs engage it from below. It's a friction fit; the channel's own weight holds it.

The rotors are out of both photographs below, which is the only way to see the joints — with a rotor in, the middle of a channel is covered. They also show the clocking from step 5: every stepper ends up in the middle of the group.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-parts/c-channel-drives-three-on-full-0fb34fea7ae4.jpg" alt="Three C-channel drives sitting on their stands with no rotors fitted, the fourth stand still empty beside them, all the steppers pointing into the middle of the group">
    <figcaption>Three drives on, one stand still empty. Rotors left out so the joints show. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-parts/c-channel-drives-all-four-full-44246243494e.jpg" alt="All four C-channel drives in place without rotors, their stepper motors gathered together at the centre of the group">
    <figcaption>All four drives in place, steppers together in the middle. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="8" title="Fit the rotors and the output guides" %}

With the channels standing, drop the rotor units in and fit the output guides at the same time. <cite>Order: BrickCycleAlice.</cite>

One [output guide]({{ '/hardware/assembly/feeder/c-channels/feeder-channels/' | relative_url }}) on C2 and one on C3. Each belongs to the channel it is mounted on, not to the gap between two; C1 and the classification channel take none.

<div class="img-placeholder">Image coming</div>

{% include step.html n="9" title="Add the bulk input and the camera lamps" %}

The [bulk cap and bucket]({{ '/hardware/assembly/feeder/c-channels/bulk-channel/' | relative_url }}) on C1. A [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}) on C2 and on C3 — C1 has neither a lamp nor an output guide, because it's fed in bulk and nothing reads vision off it.

<div class="img-placeholder">Image coming</div>

{% include step.html n="10" title="Turn it all by hand" %}

Run parts through the whole cascade by hand, one channel at a time, before wiring the steppers. Anything that needs a nudge here will jam under power. Wiring is on the [electronics]({{ '/hardware/electronics/' | relative_url }}) page.

<div class="img-placeholder">Image coming</div>
