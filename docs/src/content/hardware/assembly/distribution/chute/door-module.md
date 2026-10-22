---
layout: default
title: Door module
type: how-to
section: hardware
slug: assembly-door-module
kicker: Chute — Door module
lede: The per-layer door mechanism that releases parts into a bin.
og_image: https://assets.basically.website/sorter-docs/chute-v3-door-module-on-core-servo-side-full-57b16ba1789b.png
permalink: /hardware/assembly/distribution/chute/door-module/
author: spencer
contributors: [barthel, brickcyclealice, extremetaz, zed0]
tools_needed: ["Hex key, 2 mm", Soldering iron or heat-set insert press]
parts_needed:
  - part: chute-door
    qty: 1
  - part: bearing-race
    qty: 1
  - part: bearing-holder-left
    qty: 1
  - part: bearing-holder-right
    qty: 1
  - part: bearing-cover-covered
    qty: 1
  - part: bearing-cover-servo
    qty: 1
  - part: servo-adapter-servo-side
    qty: 1
  - part: servo-adapter-flap-side
    qty: 1
  - part: mg995-servo-horn
    qty: 1
  - part: servo-bracket-housing
    qty: 1
  - part: servo-bracket-lower-arm
    qty: 1
  - part: servo-bracket-side-arm
    qty: 1
  - part: servo-bracket-cover
    qty: 1
  - part: servo-mg995
    qty: 1
  - part: brg-6704-2rs
    qty: 2
  - part: hsi-m3
    qty: 16
  - part: hsi-m3s
    qty: 4
  - part: scr-m3-8-cs
    qty: 20
  - part: scr-m3-12-cs
    qty: 7
  - part: scr-m3-16-cs
    qty: 2
warning: >-
  **AI-generated first draft.** Written from the 3D parts of the inverted chute, not from an actual
  build, so the order of the steps is not checked against a machine. The door is drawn in one
  position of its swing, and the servo is not drawn at all.
---

The door module is the moving half of the chute. Build it on the bench as one unit, then bolt it to the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}). One per chute, so one per layer.

The door is a flat flap on a shaft. The shaft turns in two bearings, one in each bearing holder, and the holders sit either end of the bearing race, which becomes the sill under the opening in the core. The MG995 servo, coupled through the two-piece servo adapter, swings the door, and the layer's [layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}) controls when it moves, so a part is released only once the chute stack has rotated the opening over the right bin.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

Four things make it up:

1. **Chute door**. The flap itself, one printed part. One end of its shaft is a hexagon: that is the servo end.
2. **Bearing assembly**. What the door swings on: the bearing race, a bearing holder (left) and a bearing holder (right), a bearing cover (covered side) and a bearing cover (servo side), and two 6704-2RS bearings. **The two holders are a mirror pair, not the same part twice.**
3. **Servo adapter**. Two printed parts, a servo side and a flap side, that couple the servo's output to the door. The MG995 Servo Horn that comes with the servo is clasped between the two halves, then the halves are screwed together around it.
4. **MG995 servo** in its four-part bracket: a housing, a lower arm, a side arm and a cover. Built on the bench, in the steps below. **The servo itself is not screwed to anything.** It slides into the housing and the cover goes on over it, and the cover's two screws clamp the servo's mounting tabs in place.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}">chute core</a> before you start.</strong> Press all its heat inserts in first.</p>
    <p>Which wall is which: the <strong>opening side</strong> has the big opening, the <strong>rear</strong> is opposite it, and of the two long walls the <strong>servo side</strong> is the one with nine inserts and the <strong>plain side</strong> the one with six.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-core-with-inserts-opening-side-full-1961b4bfcb14.png" alt="Render of the finished chute core, an upright box open at the top with an opening in one side and brass heat inserts in its walls">
    <figcaption>The prepared chute core, with its heat inserts in. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

{% include step.html n="1" title="Preparation" %}

Four of the module's parts take heat inserts: 16 standard M3 inserts across three of them, and 4 short ones (M3S) in the fourth. Press them all in while the parts are still bare, before anything is screwed together. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

The bearing race, the chute door, the two bearing covers and the servo adapter's flap-side half take none.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Servo bracket (housing):</strong> 6 × M3, two on each of three faces. 2 take the cover, 2 take the side arm and 2 take the lower arm. The servo does not screw to the housing at all, so none of these is for it.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-housing-pockets-all-full-40b0ed372c80.png" alt="Render of the servo bracket housing seen from a corner, with all six pockets ringed in red: two on the lugs beside the big opening, two on the prongs either side of the slot, and two near one end of the underside">
    <figcaption>All six, seen from the corner. That is the only angle that catches all three faces at once. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Bearing holder (left) and bearing holder (right):</strong> 5 × M3 each, 10 between them, on two faces. 3 are around the bearing bore on the outboard face and take the bearing cover. 2 are in the foot, on the face that takes the bearing race. The picture shows the right holder; the left is its mirror, with the same five.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-holder-pockets-all-full-8fd7b894ad12.png" alt="Render of a bearing holder seen from a corner, with all five pockets ringed in red: three around the round bore and two side by side in the foot">
    <figcaption>All five on one holder: three around the bore, two in the foot. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Servo adapter (servo side):</strong> 4 × <strong>short</strong> M3 insert (M3S, <code>hsi-m3s</code>), one in each of the four round pockets on the face that goes against the flap-side half, the one with the slot for the horn. Do not use the standard M3 inserts here.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-servo-adapter-pockets-full-31467fbc322d.png" alt="Render of the servo-side half of the servo adapter, a round disc with a slot cut across its centre hole for the horn and four small round pockets ringed in red, evenly spaced around the edge">
    <figcaption>The four pockets for the short inserts, on the slotted face. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

The renders show the pockets without a brass insert in them, so count the rings, not the brass.

One more sub-assembly goes together here, before the step that uses it, and it takes no inserts.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>The two 6704-2RS bearings:</strong> one into the <strong>bearing holder (left)</strong>, one into the <strong>bearing holder (right)</strong>, from the outboard face, the one with the three inserts around the bore. There is no wrong way round. Push each one square into the bore until it stops against the step inside it. The bearing sits in the outer, wider part of the bore and leaves the rest of that part empty: the cover's raised rim fills it in step 5.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-bearing-seated-full-7304eb4b10b3.png" alt="Render of a bearing holder with a blue 6704 bearing pushed home in its round bore">
    <figcaption>The bearing (blue) pushed home in its holder. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

{% include step.html n="2" title="Slide the servo into the housing and close it with the cover" %}

**The servo is not screwed down.** Slide the MG995 into the housing's pocket with its splined output towards the cover and its wires pointing out of the small open end of the housing, the end with the slot between the two prongs. Then lay the cover over the open face and drive its 2 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws into the housing's inserts. Tightening those two is what holds the servo: the cover traps the servo's mounting tabs between itself and the housing.

Snug both down evenly rather than pulling one home first, so the cover seats flat on the tabs.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-housing-cover-off-full-654a0bb135db.png" alt="Render of the servo bracket housing with its open-frame cover held off the face that takes it, showing the pocket the servo slides into and the two lugs the cover screws through">
  <figcaption>The cover held off the housing. The servo goes into the open pocket, and the two lugs the cover screws through are the only fasteners holding it. The servo itself has no model and is not drawn. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

{% include step.html n="3" title="Add the bracket arms" %}

The two arms land on two other faces of the housing. They are not the same part and they do not take the same screw, so tell them apart before you pick one up.

- **The side arm** is the long bent piece. It goes on the slotted face of the housing, and its far end is an ear with **two** holes in it.
- **The lower arm** is the shorter piece that goes under the housing, and its far end has **one** hole.

**Side arm:** 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} into the housing's inserts.

**Lower arm:** 2 {% include fastener.html size="M3" variant="countersunk" length="12" %} into the housing's inserts. Use the 12 mm on this arm, not the 8 mm.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-servo-bracket-exploded-full-be25f72a245e.png" alt="Render of the four servo bracket parts pulled apart: the housing in the middle, the open-frame cover at one side, the bent side arm above it and the lower arm below it">
    <figcaption>The four parts of the bracket. The servo itself has no model and is not drawn. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-servo-bracket-assembled-full-0220094f4bb6.png" alt="Render of the servo bracket put together: the housing with the side arm running up from it and the lower arm underneath, the cover on the face turned away">
    <figcaption>Put together. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

Each arm has further holes in the ear at its far end, two on the side arm and one on the lower arm. Those are not driven here; they are what bolts the finished bracket to the chute core in step 8, so leave them empty.

{% include step.html n="4" title="Hang the door on its bearings and the race" %}

The shaft is captured at both ends once this is together, so there is only one order it goes in: the holders have to go onto the shaft before anything is bolted down.

**Check which way round the door goes first.** The shaft runs the length of the door's hinge edge, and one end finishes in a hexagonal spigot. That hex end is the servo side: it is what the servo adapter's flap-side half slides onto in step 8. The other end is plain round. **The bearing holder (right) goes on the hex end**, the bearing holder (left) on the plain end.

1. **Slide a holder onto each end of the shaft**, bearings already seated, with the three-insert face of each facing out, away from the door. Neither should need forcing.
2. **Lay the race across the feet of the two holders**, against the face of each foot that has the two inserts, with the row of six holes facing away from the door, and bolt each holder down onto its end of it: 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} per holder, 4 in total, into the inserts in the holders' feet. The race has a row of six holes along its long face. **Use the four outer ones for the holders**, two at each end. The two in the middle are for step 6, so leave them empty for now.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-door-holders-race-exploded-full-0fe701bb7a53.png" alt="Render of the orange door lying on its shaft with a green bearing holder pulled out beyond each end of the shaft, each holding a blue bearing, and the purple bearing race with its row of six holes pulled out to one side">
    <figcaption>The three groups before they go together: the door, the two holders with their bearings, and the race. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-door-holders-race-assembled-full-b1527c2a67c7.png" alt="Render of the door, both holders and the race put together, the race running between the two holders with its row of six holes facing away from the door">
    <figcaption>Put together. The door can swing on its shaft, and it is drawn in one position of that swing. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

{% include step.html n="5" title="Fit the bearing covers" %}

**The two covers are not the same part.** The **Bearing cover (servo side)** has an open centre and goes on the hex end of the shaft. The **Bearing cover (covered side)** is closed and goes on the plain end.

Put one on each holder, on the face with the three inserts, with 3 {% include fastener.html size="M3" variant="countersunk" length="8" %} each, 6 in total. The cover's raised rim drops into the bore on top of the bearing and clamps it: if a bearing has not gone fully home, its cover will not pull flat. The covers are thin at the rim, so snug the three screws down evenly rather than tightening one fully first.

Each cover has **two further holes that stay empty here**. They take the screws that hold the flap assembly to the chute core in step 6.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-covers-exploded-full-3eab52f1ee8e.png" alt="Render of the door, holders and race with a tan bearing cover held out beyond each holder, the nearer one closed and the farther one open in the middle">
    <figcaption>The covers going on, one at each end. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-covers-assembled-full-4dc55b903029.png" alt="Render of the same assembly with both covers screwed to their holders">
    <figcaption>Both on. This is the flap assembly. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

{% include step.html n="6" title="Bolt the flap assembly to the chute core" %}

Six of the core's 21 inserts belong to this step: 4 for the covers (the two beside the round notch on each long wall) and 2 for the race (low on the opening side, under the opening). The three on the servo side wall wait for step 8.

Slide the flap assembly into the opening in the core's side, race first, so that the race lands against the low wall under the opening and a cover lands on each long wall of the core. **It goes in at a slant, not straight**: line it up with the sloping pad on the long wall, the pad the funnel brackets bolt to, and push it in along that slope. Straight in, the holders catch on the core. Then:

- **The race**, 2 {% include fastener.html size="M3" variant="countersunk" length="16" %} through the two middle holes into the two inserts under the opening. Use the 16 mm here, not a shorter screw.
- **The covers**, 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} per cover, 4 in total, into the inserts beside the round notch. These are the two holes left empty in each cover in step 5.

Snug all six down before tightening any of them, then swing the door by hand through its full travel. It should turn freely on the bearings and not catch on the core anywhere; if it binds, slacken off and let the assembly settle square before tightening again.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-flap-assembly-slide-in-full-6ff8b5643296.png" alt="Render of the grey chute core with the flap assembly held out in front of its opening, the race at the front and a round cover at each side">
    <figcaption>How it goes in: from the opening side, race first. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-flap-assembly-seated-full-b87a283ec0f2.png" alt="Render of the flap assembly seated in the core, the race lying against the wall under the opening and a cover on each long wall">
    <figcaption>Seated. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

{% include step.html n="7" title="Build the servo adapter" %}

The servo-side and flap-side plates clamp the MG995 Servo Horn between them. The horn ships with the servo, it isn't printed. Drop the horn into the servo-side half **splined sleeve first**: the sleeve sits in the hole in the middle of that half and the two arms lie in the slot around it. It does not fit any other way. Bring the flap-side half down over it and drive 4 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws through the flap side (it's the half with the hexagonal socket and the countersunk holes) into the four short inserts in the servo side.

The flap-side half has a raised hub with a hexagonal socket. The hub points at the door, and the socket is what takes the door's hexagonal spigot at first setup, see [coupling a chute door to its servo]({{ '/hardware/helpers/door-servo-coupling/' | relative_url }}).

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-servo-adapter-exploded-flap-side-full-2c01ab089f58.png" alt="Render of the two servo adapter halves facing each other: the pink flap-side half in front with its raised hub, hexagonal socket and four holes, and the purple servo-side half behind it with a slot cut across its centre hole">
    <figcaption>Exploded, in build order. The horn goes into the servo-side half (purple), then the flap-side half (pink) goes over it. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-servo-adapter-exploded-servo-side-full-779146e3b3b0.png" alt="Render of the same two halves from the other side: the flat back of the flap-side half, and the servo-side half with its round centre hole">
    <figcaption>The same two halves from the servo end. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

{% include step.html n="8" title="Bolt the servo bracket on" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>Do not couple the servo to the door yet.</strong> Nobody knows what angle a new servo's shaft is at, and each time the machine starts it swings every flap to 0&deg; on the way to opening it. A door coupled at a guessed angle gets driven into the chute wall at every start, and that can break servos. The adapter goes on at first setup, once the machine has set the shaft to 0&deg;: <a href="{{ '/hardware/helpers/door-servo-coupling/' | relative_url }}">coupling a chute door to its servo</a>.</p>
</div>

The bracket goes on the same long wall as the servo-side bearing cover, into the three inserts there that are not under a cover: two on the small raised pad and one low down. The two arms do not take the same screw here either:

<ul class="bulleted-list">
  <li><strong>Side arm</strong>, 2 {% include fastener.html size="M3" variant="countersunk" length="12" %}, through the two holes in its ear.</li>
  <li><strong>Lower arm</strong>, 1 {% include fastener.html size="M3" variant="countersunk" length="12" %}.</li>
</ul>

**Leave the servo adapter off.** Bolt the bracket on without it: the servo's splined shaft and the hex end of the door's shaft face each other with a gap between them. Put the adapter you built in step 7 and the small screw from the servo's bag in a bag, write the layer on it, and keep it with the chute.

**Never turn the servo's shaft by hand**, now or later. Its gearbox barely turns backwards, so forcing it rounds off the teeth inside the horn or breaks the servo.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-door-module-on-core-window-side-full-a3fa21b3d986.png" alt="Render of the chute core with the servo bracket bolted to its long wall, the side arm running up to the core and the lower arm underneath, the servo adapter discs between the bracket and the bearing cover, and the door inside the opening">
  <figcaption>The bracket bolted on, seen from the opening side. The render also shows the adapter, between the bracket and the bearing cover, which goes on at first setup. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

## The finished result

The module is finished when the bracket is on the core, the door swings freely through its whole travel, and the adapter and the servo's small screw are bagged with the layer, ready for first setup. One of these per layer.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-door-module-on-core-servo-side-full-57b16ba1789b.png" alt="Render of the door module on the chute core seen from the servo side: the blue servo bracket on the long wall with the side arm running up and the lower arm underneath, the servo adapter discs between the bracket and the bearing cover, the purple race under the opening and the orange door resting inside it">
  <figcaption>A module on its core, from the servo side, shown with the adapter that goes on at first setup. The servo itself has no model, so the bracket shows empty. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

The servo's plug goes on the [layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}). The [Chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}) page carries the other sub-assemblies that go on the same core, and is where you should return once you're done here.
