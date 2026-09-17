---
layout: default
title: Door module
type: how-to
section: hardware
slug: assembly-door-module
kicker: Chute — Door module
lede: The per-layer door mechanism that releases parts into a bin.
permalink: /hardware/assembly/distribution/chute/door-module/
author: spencer
contributors: [barthel]
last_verified: 2026-09-07
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
  - part: scr-m3-12-cs
    qty: 5
  - part: scr-m3-8-cs
    qty: 21
---

The door module is the moving half of the chute. Build it on the bench as one unit, then bolt it to the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}). One per chute, so one per layer.

The door pivots on two bearings held in the bearing assembly. The MG995 servo, coupled through the two-piece servo adapter, swings it between its open and closed positions, and the layer's [layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}) controls when it opens, releasing the part only once the chute stack has rotated the funnel into position over the right bin.

Every step from 2 to 7 now carries photographs of a real build, and the checks called out in steps 4, 5 and 7 come from that build rather than from the geometry. The dimensions quoted are still measured off the parts. Correct this page as you go; the fastener counts are accurate either way.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

Four things make it up:

1. **Chute door**. The flap itself, one printed part.
2. **Bearing assembly**. What the door swings on: the bearing race, a bearing holder (left) and a bearing holder (right), a bearing cover (covered side) and a bearing cover (servo side), and two 6704-2RS bearings.
3. **Servo adapter**. Two printed parts, a servo side and a flap side, that couple the servo's output to the door. The MG995 Servo Horn that comes with the servo is clasped between the two halves, then the halves are screwed together around it: 4 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws, driven through the flap side (it's the half with the visible screw holes) into the servo side. No heat inserts, the screws thread directly into the printed plastic.
4. **MG995 servo** in its four-part bracket: a housing, a lower arm, a side arm and a cover. Built on the bench, in the steps below. **The servo itself is not screwed to anything.** It slides into the housing and the cover goes on over it, and the cover's two screws clamp the servo's mounting tabs in place.

**What each fastener is for.** The list above gives totals for the whole module; this is the split:

- **Bearing assembly, its own:** 10 {% include fastener.html size="M3" variant="heat-insert" %} (4 in the race, 3 in each holder) and 10 {% include fastener.html size="M3" variant="countersunk" length="8" %}. Six hold the covers to the holders, 3 each, and 4 hold the holders to the race, 2 each; all ten are driven in steps 4 and 5. The two 6704-2RS bearings go into the holders in step 1. The covers are thin at the rim, so snug their screws down evenly rather than fully tightening one before the others.
- **Servo adapter, its own:** 4 {% include fastener.html size="M3" variant="countersunk" length="8" %}, no heat inserts. They hold the servo-side and flap-side halves together with the MG995 Servo Horn clasped between them.
- **Servo bracket, its own:** 6 {% include fastener.html size="M3" variant="heat-insert" %} in the housing, two on each of three faces, and one screw per insert. 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} hold the lower arm on, 2 {% include fastener.html size="M3" variant="countersunk" length="12" %} hold the side arm on, and 2 {% include fastener.html size="M3" variant="countersunk" length="12" %} hold the cover on. None of them goes through the servo.
- **Holding the finished module to the chute core:** 4 {% include fastener.html size="M3" variant="countersunk" length="8" %} through the two bearing covers, plus one screw through each bracket arm's mounting ear, step 8. The two arms are not the same thickness there, so they do not take the same screw: the lower arm's ear is 8.40 mm and takes a {% include fastener.html size="M3" variant="countersunk" length="12" %}, the side arm's is 5.00 mm and takes a {% include fastener.html size="M3" variant="countersunk" length="8" %}. All six go into the core's own heat inserts, so there is nothing to press in here for them.

{% include step.html n="1" title="Preparation" %}

Four of the module's parts take heat inserts, 16 between them. Press them all in while the parts are still bare, before anything is screwed together. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

Every pocket is the same one the rest of the chute uses: Ø4.2 mm, blind, 5.7 mm deep. The two bearing covers, the chute door and the two servo adapter halves take none.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Servo bracket (housing):</strong> 6 × M3, two on each of three faces. 2 take the lower arm, 2 take the side arm and 2 take the cover. The servo does not screw to the housing at all, so none of these is for it.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-inserts-servo-bracket-housing-w1600-ca8e04d2c1d7.jpg" alt="A printed servo bracket housing standing on end, brass heat inserts pressed into all six pockets: two on the top face, two on the front face beside the open pocket, two on the bottom edge">
    <figcaption>All six, seen from the corner. That is the only angle that catches all three faces at once. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Bearing race:</strong> 4 × M3, two at each end. These are the ones the holders screw down onto.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-inserts-bearing-race-w1600-c3730d2c7c58.jpg" alt="A printed bearing race lying flat, brass heat inserts in the two pockets at each end and a raised chevron in the middle of the same face">
    <figcaption>Two at each end of the race. They are on the same face as the raised chevron in the middle. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Bearing holder (left) and bearing holder (right):</strong> 3 × M3 each, 6 between them, on the outboard face around the bearing bore.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-inserts-bearing-holder-w1600-9f39521a7c9b.jpg" alt="A printed bearing holder held at an angle, three brass heat inserts spaced around its empty bearing bore, one on the small ear and two on the body">
    <figcaption>Three around the bore on the outboard face. One holder is shown; the other takes the same three. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

The photos are of printed parts with the inserts already pressed in, one part at a time, so the brass is what you count. The counts match what the [parts calculator](https://parts-calculator.basically.website/assembly?focus=flap-module) asks for: 6 + 4 + 3 + 3.

<div class="callout">
  <span class="callout-icon" aria-hidden="true">💡</span>
  <p>No bench vice? Stand a bearing holder in the servo bracket housing while you press its inserts. The housing's pocket holds the holder upright and square, and leaves both your hands for the iron. <cite>Tip: BrickCycleAlice.</cite></p>
</div>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-holder-propped-in-housing-w1600-8617b387f402.jpg" alt="A bearing holder with its three brass inserts standing against the open servo bracket housing, which props it upright on the bench">
  <figcaption>A holder propped in the housing, which is steady enough to press against. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

One more sub-assembly goes together here, before the step that uses it, and it takes no inserts.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>The two 6704-2RS bearings:</strong> one into the <strong>bearing holder (left)</strong>, one into the <strong>bearing holder (right)</strong>. There is no wrong way round. Push each one square into the bore until it stops. <strong>Home is not the bottom of the pocket:</strong> the bearing comes up against a small lip inside the bore and sits proud of the floor, so stop when it stops rather than pushing for flush.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-bearings-in-holders-w1600-180e121b8951.jpg" alt="Both printed bearing holders with a 6704-2RS bearing pushed into each bore, a ring of printed plastic still visible around the bearing's outer race, and three brass heat inserts around each face">
    <figcaption>Both holders with their bearings pushed home. The ring of plastic still showing around each bearing is the lip it has stopped against. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="2" title="Slide the servo into the housing and close it with the cover" %}

**The servo is not screwed down.** Slide the MG995 into the housing's pocket, then lay the cover over the open face and drive its 2 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws into the housing's inserts. Tightening those two is what holds the servo: the cover traps the servo's mounting tabs between itself and the housing.

The cover is 6.65 mm thick at the screw, so a 12 mm screw reaches 5.35 mm into the housing's blind 5.70 mm insert and an 8 mm one would reach only 1.35 mm. Snug both down evenly rather than pulling one home first, so the cover seats flat on the tabs.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/housing-cover-open-full-eb4bde91c9c0.png" alt="Render of the servo bracket housing with the cover pulled off it, showing the open pocket the servo slides into and the two screw lugs that line up between the cover and the housing">
  <figcaption>The cover pulled off the housing. The servo goes into the open pocket, and the two lugs the cover screws through are the only fasteners holding it. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-servo-in-housing-w1600-b7436486902c.jpg" alt="An MG995 servo lying in the open pocket of the printed housing with the cover off, its mounting tabs resting across the two brass-lined lugs and its lead running out of the bottom of the pocket">
    <figcaption>Servo in, cover still off. Its tabs lie across the two lugs and nothing screws into the servo itself. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-cover-on-w1600-7153a7d8b99c.jpg" alt="The same housing from the corner with the cover screwed down over the servo, two countersunk screw heads in the cover and the servo's splined output standing through the window in it">
    <figcaption>Cover on, both screws snugged down evenly. That pair is what holds the servo in. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="3" title="Add the bracket arms" %}

The two arms land on two other faces of the housing.

**Lower arm:** 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} into the housing's inserts. It is the wider of the two arms, and it is 4.25 mm thick at the screws, so an 8 mm one reaches 3.75 mm in.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-lower-arm-on-w1600-d777cd9b9a60.jpg" alt="The servo bracket housing with the wide lower arm bolted to it, seen from the cover side, the arm's thick end standing proud with a single empty hole in its sloped face">
    <figcaption>The lower arm on. The empty hole in its raised end is the one that bolts to the chute core later, not now. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-lower-arm-screws-w1600-aebd2878b313.jpg" alt="The same assembly from the servo output end, with two countersunk screw heads visible in the face of the lower arm and the servo's splined output above them">
    <figcaption>From the output end, with the arm's two countersunk screws driven home. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

**Side arm:** 2 {% include fastener.html size="M3" variant="countersunk" length="12" %} into the housing's inserts.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-side-arm-on-w1600-d2fc44863353.jpg" alt="Both arms now on the housing: the wide lower arm across the top and the narrow side arm projecting from the right-hand face with an empty hole in its foot">
    <figcaption>Side arm added, so both arms are now on. Its foot carries the second empty hole. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-both-arms-underside-w1600-882c2dfe8031.jpg" alt="The finished bracket from below with both arms fitted, two countersunk screw heads in the near face and the servo's output shaft visible between the arms">
    <figcaption>The finished bracket from below, both arms fitted. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

Each arm has one further hole, in the ear at its far end. Those two are not driven here; they are what bolts the finished bracket to the chute core in step 8, so leave them empty.

{% include step.html n="4" title="Hang the door on its bearings and the race" %}

The shaft is captured at both ends once this is together, so there is only one order it goes in: the holders have to go onto the shaft before anything is bolted down.

**Check which way round the door goes first.** The shaft runs the length of the door's top edge and is Ø19.8 mm, but one end finishes in a hexagonal spigot 12.0 mm across the flats. That hex end is the servo side — it is what the servo adapter's flap-side half slides onto in step 8. The other end is plain round.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>Check the race is the right way round before any of this is bolted up.</strong> The shaft sits high on the door's axis and the race's step tucks down and under it, so laid together correctly the race and the door read as one flat plane. If they look like a flight of stairs, the race is round the wrong way. Getting it wrong is a lot of screws to undo. <cite>Tip: BrickCycleAlice.</cite></p>
</div>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-door-and-race-apart-w1600-a1c66c18ef8b.jpg" alt="The printed chute door lying beside the bearing race before assembly, the door's shaft running along its top edge with the hexagonal spigot at one end, and the race's stepped profile facing the shaft">
    <figcaption>The two parts before they go together, and the orientation to get right: the race's step goes down and under the shaft. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-door-race-flat-plane-w1600-e407f399bfbc.jpg" alt="The door and race sighted along their length from the hexagonal end of the shaft, the top of the race and the top of the door lying in one continuous flat plane">
    <figcaption>Right way round, sighted along the joint: one flat plane across both, no step to walk up. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>


1. **Slide a holder onto each end of the shaft**, bearings already seated. The bearing's Ø20 bore takes the Ø19.8 shaft, and the holder's own Ø21.0 mm hole clears the shaft by 0.6 mm all round, so neither should need forcing.
2. **Lay the race along the back of the shaft**, on the opposite side from the flap, and bolt each holder down onto its end of it: 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} per holder, 4 in total, into the race's four inserts. The holder seats flat against the race's end. The race arches over the shaft with about 0.5 mm of clearance and never touches it; if it does touch, something is not seated.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-holder-on-race-end-w1600-71a9cfaaf366.jpg" alt="Close view of one end of the assembled flap: the bearing holder bolted to the end of the bearing race with two countersunk screws in its face, the bearing seated in its bore with the door's shaft through it, and the door plate above">
  <figcaption>One end, done. The holder is bolted to the end of the race and the shaft runs through its bearing. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/bearing-assembly-blue-full-1cb33257bd5a.png" alt="Two renders, one above the other: on top the chute door with its shaft, the bearing race over the shaft, and the two bearing holders drawn out along the shaft with a blue bearing in each; below, the same parts pushed together so the holders sit on the ends of the race">
  <figcaption>The holders, with their bearings in blue, going onto the ends of the shaft and down onto the race. The covers are not shown. <cite>Rendered from the parts' own geometry in assembly position, not from a build. Render: Balloon.</cite></figcaption>
</figure>

Hung this way the door has **80.5° of swing**, from 10.7° off horizontal at its flattest to 88.9° at its steepest. Both ends of that are the door meeting the race across its full width, not the holders.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/door-travel-limits-full-323c3b543a10.png" alt="Render of the assembled door module seen from the servo end at an angle, with the chute door drawn twice: once in grey lying almost flat, and once in orange hanging almost vertically, both pivoting on the same shaft below the bearing race">
  <figcaption>The two ends of the door's swing, 80.5° apart. Grey is the flattest the door goes, with the plate 10.7° off horizontal; orange is the steepest, at 88.9°. The covers are not shown. <cite>Measured and rendered from the parts' own geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

{% include step.html n="5" title="Fit the bearing covers" %}

**The two covers are not the same part.** The Bearing cover (servo) has an open centre, and it goes on the hex end of the shaft, because the shaft has to come through it to reach the servo adapter. The Bearing cover (covered) is closed and goes on the plain end.

Put one on each holder with 3 {% include fastener.html size="M3" variant="countersunk" length="8" %} each, 6 in total, into the three inserts pressed in step 1. The cover's raised rim, 5.00 mm tall, drops into the pocket on top of the bearing and clamps it against the step: if a bearing has not gone fully home against its lip, its cover will not pull flat.

Each cover has **two further holes that stay empty here** — they take the screws that hold the flap assembly to the chute core in step 6.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-cover-one-end-w1600-cbc69bf7f4ff.jpg" alt="The flap assembly with a round bearing cover fitted on the near end, its screws driven around the rim, the door plate running away to the right">
    <figcaption>One end covered. The two holes left empty in the rim are for step 6. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-covers-both-ends-w1600-ffa9c5829cb0.jpg" alt="The whole flap assembly with both covers on, the near cover showing the open centre the shaft comes through and the far cover closed">
    <figcaption>Both on, and the difference visible: the near one is open for the shaft, the far one is closed. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="6" title="Bolt the flap assembly to the chute core" %}

Six of the core's 18 inserts belong to this module. Four are used here, two in step 8:

- **2 bearing covers**, 4 {% include fastener.html size="M3" variant="countersunk" length="8" %} in total, 2 per cover, into 5.00 mm of wall. These are the two holes left empty in each cover in step 5.
- **Servo bracket lower arm**, 1 {% include fastener.html size="M3" variant="countersunk" length="12" %}, and **side arm**, 1 {% include fastener.html size="M3" variant="countersunk" length="8" %} — step 8.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-core-door-module-side-4-full-f61ab38ed984.png" alt="Render of the servo side of the chute core with four heat inserts circled in red">
    <figcaption>The long side the servo sits on: two inserts for that side's bearing cover, two for the servo bracket arms. <cite>Render: Balloon.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-core-door-module-side-2-full-c9afd2f336aa.png" alt="Render of the other long side of the chute core with two heat inserts circled in red">
    <figcaption>The other long side: two inserts, both for the second bearing cover. <cite>Render: Balloon.</cite></figcaption>
  </figure>
</div>

**The covers are what hold the flap on.** Nothing else in the bearing assembly touches the core: the race and the holders are carried by the two covers, which are already screwed to the holders from step 5. Offer the whole assembly up so a cover lands on each long side of the core, and drive 2 screws per cover into the inserts above.

8 mm is the right length because the cover is 5.00 mm at those holes, so the screw reaches 3.00 mm into the core's blind 5.70 mm insert. Measured off the STLs.

Snug all four down before tightening any of them, then cycle the door by hand through its full swing. It should turn freely on the bearings and not touch the core anywhere; if it binds, slacken off and let the assembly settle square before tightening again.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-flap-sliding-in-w1600-de953979e4b1.jpg" alt="The flap assembly being offered up to the chute core, one bearing cover standing proud of the core's long side before its screws go in">
  <figcaption>How it goes in: a cover lands on each long side of the core, and the two screws per cover go in from there. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-flap-closed-w1600-2cf8babd0acb.jpg" alt="The flap bolted to the core, seen down onto the top face, with the door closed so no blade shows below the core">
    <figcaption>Bolted down, door fully closed: nothing showing below the core. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-flap-open-w1600-740514c1bff8.jpg" alt="The same assembly with the door fully open, the thin door plate hanging down clear of the core">
    <figcaption>Door fully open, the plate hanging clear. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-flap-closed-other-side-w1600-2b268da4eb66.jpg" alt="The other side of the same assembly, the bearing cover with the hexagonal socket in the middle, door closed">
    <figcaption>The other side, door closed. This is the cover with the hex socket, so this end faces the servo. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-flap-open-other-side-w1600-f4850a808fe4.jpg" alt="The same side with the door fully open, the door plate hanging below the core">
    <figcaption>The other side, door open. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-flap-from-back-w1600-542076f9f69f.jpg" alt="The assembly end on from the back with the door closed, four brass inserts in the flat top plate and the bearing race with its chevron sitting between the two holders">
  <figcaption>From the back with the door closed: the race and its chevron sit between the two holders. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

{% include step.html n="7" title="Build the servo adapter" %}

The servo-side and flap-side plates clamp the MG995 Servo Horn between them. The horn ships with the servo, it isn't printed. Drop the horn into the servo-side half **splined sleeve first**: the sleeve sits in the hole in the middle of that half and the two arms lie in the slot around it. It does not fit any other way. Bring the flap-side half down over it and drive 4 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws through the flap side (it's the half with the visible screw holes) into the servo side. The screws cut their own thread in the printed plastic.

<div class="callout">
  <span class="callout-icon" aria-hidden="true">💡</span>
  <p>The four screw holes are not spaced evenly around the centre. They sit on a 15 mm radius but the gaps between them alternate 84° and 96°, so the flap side only drops on in two of the four quarter turns. Line all four holes up by eye before you press the halves together, rather than finding out on the third screw. <cite>Tip: BrickCycleAlice.</cite></p>
</div>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/mg995-servo-horn-sleeve-right-full-7518b1e88254.png" alt="The MG995 Servo Horn, a two-arm splined servo arm that ships with the servo, with its splined sleeve facing to the right">
    <figcaption>The MG995 Servo Horn. The splined sleeve, facing right here, is what goes into the servo-side (tan) half in the next picture; on the machine it is also what slides onto the servo's output shaft. <cite>Reference photo of the stock part, not from a build. Photographer not recorded.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/servo-adapter-exploded-full-57d2c57e666b.png" alt="Exploded render of the two servo adapter halves facing each other: the flap-side half in blue on the left showing its hexagonal socket and four countersunk holes, the servo-side half in tan on the right showing the long slot the two-arm horn seats in and its four pilot holes">
    <figcaption>Exploded, in build order. The horn goes into the servo-side half (tan), sleeve into the middle hole and arms in the slot, then the flap-side half (blue) goes over it and takes the 4 screws. The hex socket in the flap side is what the door's shaft ends up in. <cite>Rendered from the part geometry in assembly position, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-servo-adapter-servo-side-w1600-eaf8aa259871.jpg" alt="The finished servo adapter seen from the servo side: the black two-arm horn lying flush in its slot in the grey printed disc, the splined sleeve's opening in the middle of it and four empty countersunk holes around the face">
    <figcaption>Finished, servo side. The horn sits flush in its slot with the splined sleeve in the middle, and that opening is what goes onto the servo's output shaft. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-servo-adapter-flap-side-w1600-76e5eb69f26e.jpg" alt="The same adapter from the flap side: a raised hub with a hexagonal socket in the middle and the four countersunk screws driven from this face around it">
    <figcaption>The other side, and the one to check: four screws home, and the hexagonal socket in the raised hub that takes the hex end of the door's shaft. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="8" title="Bolt the servo bracket on and couple it to the door" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>Watch the video below before you finish this step.</strong> It is possible to break a door here, so see how the coupling is set in the video before you commit to a position. The door only has 80.5° of travel and both ends of it are the door itself meeting the race, so there is nowhere for it to give. <cite>Tip: BrickCycleAlice.</cite></p>
</div>

The bracket goes on the same long side as the servo-side bearing cover, into the other two inserts in the first render above. The two arms do not take the same screw, because their mounting ears are not the same thickness:

- **Lower arm**, 1 {% include fastener.html size="M3" variant="countersunk" length="12" %} through an ear 8.40 mm thick. An 8 mm screw would not reach the insert at all; the 12 reaches 3.60 mm into it.
- **Side arm**, 1 {% include fastener.html size="M3" variant="countersunk" length="8" %} through an ear 5.00 mm thick, the same as the bearing covers'. The 8 reaches 3.00 mm in; a 12 would bottom out in the pocket.

Then couple the servo to the door through the two-piece adapter you built in the step above. Its servo side goes onto the servo's splined output, through the horn clasped inside it, and its flap side has a hexagonal socket 12.4 mm across the flats that takes **the hex end of the door's shaft** — the end step 4 told you to point at the servo. The spigot is 12.0 mm across the flats, so it is a slip fit with about 0.4 mm to spare.

Clock it before you commit: centre the servo (or let it settle at its power-on default), fit the adapter at roughly the middle of the door's swing, then fine-tune once you can check both open and closed by eye. The video below shows how it is set.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/door-module-servo-video-frame-full-1f27d2aaa634.jpg" alt="Photograph of a real door module part-way through assembly: a hand holds the assembled servo adapter, a white disc with a hexagonal boss in the middle and four countersunk screws around it, in front of the MG995 in its printed bracket">
  <figcaption>The same job on a real machine. The disc in frame is the servo adapter from step 7, screwed together with its four countersunk screws, with the hexagonal socket that takes the door's shaft facing the camera; the MG995 sits in its bracket behind it. <cite>Frame from the video below. Video: Spencer.</cite></figcaption>
</figure>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-bracket-on-core-coupled-w1600-753b3624aba0.jpg" alt="The servo bracket bolted to the chute core with the servo adapter fitted on the servo's output, seen face on, the adapter's four screws and hex socket visible">
    <figcaption>Bracket bolted on and the adapter fitted to the servo, seen face on. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-door-module-bracket-on-core-top-w1600-94ef36ed29c6.jpg" alt="The same assembly from above, the servo in its bracket standing off the chute core with the door hanging below">
    <figcaption>From above, with the servo standing off the core and the door below. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>The MG995 only rotates 180°. Install the servo so the door can reach <strong>both</strong> its fully open and fully closed positions inside that range: clock the horn and set the mounting angle so neither extreme falls outside the servo's travel. Before you tighten anything down, cycle the door by hand through both positions to confirm it swings freely and doesn't bind on the bearings or the core.</p>
</div>

<figure class="video-figure">
  <div class="video-embed video-embed-wide">
    <iframe
      src="https://www.youtube.com/embed/TMo_xE-Zyy0"
      title="How to install the MG995 servo"
      allow="encrypted-media; picture-in-picture; web-share"
      allowfullscreen
      loading="lazy"></iframe>
  </div>
  <figcaption><cite>Video: Spencer.</cite></figcaption>
</figure>
