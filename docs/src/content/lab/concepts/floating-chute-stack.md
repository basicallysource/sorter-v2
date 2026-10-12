---
layout: default
title: Floating chute stack
type: explanation
section: lab
slug: lab-floating-chute-stack
kicker: Design and research — Variants — Concepts
lede: "A proposal to take everything electrical off the rotating chute stack, build each bin layer as a self-contained module, and replace the stiff chute stack with a column of tapered-hex-coupled chutes held at two points."
permalink: /lab/concepts/floating-chute-stack/
audience: contributor or builder interested in changing the distribution section
applies_to: hardware-v2
owner: docs
author: soran82
warning: >-
  **Concept, not verified and not built.** Part dimensions were measured from the published STL files.
  Masses, accelerations and tolerances are estimates and are marked as such. The door actuation (section
  4) is the least mature part and needs a CAD check before anything is built. Nothing on the build pages
  changes because of this page.
---

This page is a concept proposal for the distribution section, version 0.1 of 2026-10-10. It is written from the hardware pages (the chute, the door module, the layer adapter board, the top interface, stacking the layers and the bottom interface) and from the part files in the [parts calculator](https://parts-calculator.basically.website/).

## 1. Summary

<h3>What the current design costs</h3>

<ul class="bulleted-list">
  <li>The servo, the layer adapter board and the ribbon cable between chutes (RIB2) rotate with every chute, and RIB1 runs through a cable cage.</li>
  <li>The frame has to be finished first. The chutes and funnels are fitted into the closed tower afterwards.</li>
  <li>The stack is held by two Lazy Susans only, and the layer connectors cannot be adjusted once it is stacked.</li>
  <li>The stepper sits at the top, where the joints carry the least weight.</li>
</ul>

<h3>What is proposed</h3>

<ol class="numbered-list">
  <li><strong>Layer module.</strong> The frame, guide ring, chute, funnel, actuator and bins are built and tested one layer at a time.</li>
  <li><strong>Two-point support.</strong> The bottom Lazy Susan carries all of the axial load. The top bearing is radial only, adjustable and free to move axially. The layers in between only guide.</li>
  <li><strong>Tapered hex coupling between chutes</strong>, held together by the weight above, with the drive at the bottom.</li>
  <li><strong>Static door actuation.</strong> A fixed ring on each layer pushes a short lever on the door shaft.</li>
</ol>

| Change | Main benefit | Risk |
|---|---|---|
| Layer modules | Assemble and test on the bench, replace one layer without unstacking | Low |
| Two-point support with guide rings | Statically determinate axis, no need to line up N bearings on one axis | Low |
| Tapered hex coupling, drive at the bottom | Low backlash without springs, self-centering, torque and preload scale together | Low to medium |
| Static door actuation (ring and lever) | No cables or electronics on the rotating stack | High (the space is tight) |

## 2. The current design and its limits

Everything in this table is taken from the hardware pages.

| Topic | As documented | Consequence |
|---|---|---|
| Wiring | One MG995 servo and one layer adapter board per chute, a 300 mm ribbon (RIB2) between chutes, and RIB1 (1.2 to 1.5 m) through the cable cage at the top. | Everything electrical rotates. J3 and J4 can be swapped: "every layer below it moves the wrong flap". |
| Assembly order | "Do not add the chutes while you build the layers." The whole frame first, then the chutes one at a time without funnels, funnels snapped on in the standing tower, bottom interface last. | The sockets are "hard to reach" inside the tower. There is no per-layer test and no way to add or replace a layer without opening the tower. |
| Alignment | The chute stack rotates on the top and bottom Lazy Susan, and the layer connectors join the chutes ("Nothing here is adjustable once the tower is stacked"). | Tolerance stack-up is absorbed by screws and printed parts, not by the design. |
| Drive | A NEMA 23 and gear train at the top interface, with the limit switch at the top. | The joint that carries the most torque (the top one) carries the least weight. |

## 3. The concept

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/floating-stack-two-architectures-full-05769de3e112.png" alt="Two side-by-side schematics of the chute stack. Today: servos, adapter boards and ribbon cables on every rotating chute, and a stepper with a cable cage at the top. Proposed: tapered joints between chutes, guide rings and fixed micro servos on the frame, static wiring down the side, and the stepper at the bottom.">
  <figcaption>The same stack in two architectures (schematic, not to scale). Red marks what rotates with the stack and causes the wiring problem. Teal marks what the proposal adds or moves. <cite>Drawn from the concept proposal, not from a build. Drawing: Jan-Henning Grell (Soran82).</cite></figcaption>
</figure>

**Today**

1. Servo, layer adapter board and RIB2 ribbon on every rotating chute.
2. Stepper and RIB1 cable cage at the top.
3. The bottom Lazy Susan carries the stack, and the chutes are inserted into the closed frame.
4. The funnel hangs on brackets on the rotating core.

**Proposed**

- **A.** Top bearing: radial only, adjustable in x and y, free in z.
- **B.** Guide ring per layer: radial clearance, carries no load.
- **C.** Tapered hex joint between chutes (the weight preloads it).
- **D.** Fixed ring and lever on the door shaft, with a micro servo on the frame.
- **E.** Bottom Lazy Susan (axial and radial) and the stepper with the limit switch at the bottom.
- **F.** Static wiring along the frame, nothing electrical rotates.

### 3.1 Layer module

Each bin layer becomes a unit: hex frame, guide ring, chute core with door and funnel, door actuator and its static wiring, and bins. It is assembled and tested on the bench and then stacked. The chutes of neighbouring modules connect through the tapered hex joint (3.3), so no ribbon cable between layers is needed. The corner joints of the frame (12 M5 screws per joint) stay as they are.

### 3.2 Two-point support (variant B)

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/floating-stack-two-point-support-full-021738192096.png" alt="Side view of a column of three chutes. The top bearing is radial only and adjustable in x and y. Guide rings sit around each chute with clearance. Tapered hex joints join the chutes. The bottom Lazy Susan carries the whole stack, with a NEMA 23 and gear beside it. An arrow shows the weight flowing down through the joints.">
  <figcaption>Two fixed constraints define the axis. Everything between only guides. <cite>Drawn from the concept proposal, not from a build. Drawing: Jan-Henning Grell (Soran82).</cite></figcaption>
</figure>

Two fixed constraints define the axis, and everything between only guides. The bottom Lazy Susan is the only axial support. The top bearing is mounted loosely, aligned to the bottom one with the column assembled, then locked (slotted holes, as already used on the top plate). Intermediate layers carry no weight, so no layer needs to be coaxial with its neighbours.

| Support | Constrains | Leaves free |
|---|---|---|
| Bottom Lazy Susan | axial (z), radial (x, y) | rotation |
| Top bearing | radial (x, y) after alignment | axial (z), rotation |
| Guide ring per layer | radial limit only (clearance, estimated ±2 mm) | everything else |

**Why not a bearing per layer carrying its own weight (variant A)?** Each bearing would fix the chute height, which conflicts with the height the joints need, and N bearings would have to be coaxial. In variant B the weight has to travel through the joints, which is also what preloads the tapered couplings.

### 3.3 Tapered hex coupling and bottom drive

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/floating-stack-tapered-hex-joint-full-246192be02b0.png" alt="Left: section of the proposed joint. A tapered hex spigot on the underside of one chute core seats in a tapered socket on top of the core below, with the weight above acting as preload. Right: top view of the hexagon with an index key at one corner so only one angular position fits.">
  <figcaption>Section and top view of the proposed chute-to-chute joint. <cite>Drawn from the concept proposal, not from a build. Drawing: Jan-Henning Grell (Soran82).</cite></figcaption>
</figure>

The spigot on the underside of each core seats in a tapered socket on the top of the core below. The taper turns radial play into a small axial travel, so print tolerances are absorbed instead of becoming backlash. An index key allows only one angular position. The starting values (A/F 70 to 80 mm, depth 25 to 30 mm, half-angle 15 to 20°) are proposals to be validated.

**Why the drive belongs at the bottom.** The torque a joint transmits is set by the inertia of the layers below it when the drive is at the top, and by the layers above it when the drive is at the bottom. The preload a joint receives from gravity is set by the layers above it. With the drive at the bottom, torque and preload both scale with the number of layers above the joint, so the ratio is the same for every joint (about one, for the tangential force at 50 mm radius against the weight, see the estimates in section 6). With the drive at the top the ratio is inverted and the top joint would need a spring.

This holds only for wedge-type joints (cone or serrations). A straight hex with a clearance fit is not preloaded by weight and keeps its backlash.

## 4. Static door actuation

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/floating-stack-door-lever-end-view-full-364b3ad8a097.png" alt="End view of the door shaft. The door hangs closed at about 25 degrees below horizontal or open vertically. A short lever on the shaft rests on the underside of a fixed ring that a micro servo on the frame raises or lowers.">
  <figcaption>End view of the door shaft with the lever and the fixed ring. <cite>Drawn from the concept proposal, not from a build. Drawing: Jan-Henning Grell (Soran82).</cite></figcaption>
</figure>

The door already falls open by gravity, so a ring only has to hold it closed and let it go. A short lever is clamped on the 12 mm hex spigot, where the MG995 adapter sits today. The lever rests against the underside of a fixed ring. Raising the ring lets the door fall (the door torque keeps the lever in contact, so the ring controls the speed). Lowering the ring pushes the lever down and closes the door. The bearing race already provides both end stops, so no servo "clocking" step is needed.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/floating-stack-ring-plan-view-full-684a07695656.png" alt="Plan view of a chute core with the circle swept by its corners (radius about 97 mm) and a ring around it at radius 99 to 112 mm. The lever tip reaches the ring at radius 102 to 108 mm. The funnel extends to the right and passes through the ring's annulus at another height.">
  <figcaption>Plan view of the ring around the swept core. <cite>Drawn from the concept proposal, not from a build. Drawing: Jan-Henning Grell (Soran82).</cite></figcaption>
</figure>

The ring has to sit outside the swept core and inside the height band the funnels leave free. The core's corners sweep a circle of about 97 mm radius, so the ring and the lever tip must be at 99 mm or more. At that radius the funnels of this layer and the next layer pass through the same annulus, at different heights (next table).

**Envelope check (first pass, from the STL bounding boxes).** Coordinates are in the chute core frame, and the next layer is assumed to be offset by +160 mm in z (the layer pitch from the docs). The check uses bounding boxes and the funnel's main planes, not the full meshes.

| Item (at radius 99 to 112 mm from the stack axis) | z (mm) |
|---|---|
| Top surface of this layer's funnel (highest at the funnel edges, y = ±72) | ≈ 129 to 138 |
| Underside of the next layer's funnel body | ≈ 169 to 197 |
| Next layer's funnel brackets (bounding box starts here, y 60 to 76) | ≥ 158 |
| Free band for ring and lever tip | ≈ 138 to 158 (about 20 mm) |
| Door swing of about 65° with a 20 mm lever, vertical tip travel | ≈ 18 to 21 |

The free band is about as tall as the lever travel plus the ring thickness. It may just fit with a lever of 15 to 20 mm, or it may not. If it does not, the options are:

<ul class="bulleted-list">
  <li>a link or bell crank that carries the motion to a larger radius, where the band is about 60 mm tall;</li>
  <li>a relief in the funnel top or bracket near the lever;</li>
  <li>keeping a servo on the chute and moving only the cables off the rotating part (a slip ring).</li>
</ul>

### What this does for the wiring

<ul class="bulleted-list">
  <li>No layer adapter board, no RIB2 chain and no servo cable on the rotating chutes.</li>
  <li>RIB1 and the cable cage in the top interface are no longer needed. The stepper, limit switch and all actuators sit on the fixed frame (the limit switch moves to the bottom with the drive).</li>
  <li>The control board drives N fixed micro servos directly (or one multi-channel driver), and the cables are static.</li>
</ul>

## 5. Measured data

Measured from the STL files in the parts calculator.

| Item | Value |
|---|---|
| Chute core, envelope | x −63 to 60, y ±74, z −2.5 to 226 (123 × 148 × 229 mm). The corners sweep r ≈ 97 mm. |
| Door shaft | Axis parallel to x, at y = +52.3, z = 150.4. Shaft Ø19.8. |
| Hex spigot | ≈ 12 A/F, ends at x = 72.8. The core face is at x = 60. |
| Servo adapter (flap side) | x 73.8 to 84.8, Ø42 |
| Door | 46.9 g, plate ≈ 108 × 123 mm, centre of mass ≈ 53 mm from the axis. Closed ≈ 25° below horizontal, open ≈ vertical. |
| Funnel, third size | x 60 to 229, y ±72, z −13 to 144. Inner width 110 to 60.6 mm. 216.3 g. |
| Funnel bracket (each) | x 36 to 130, y 60 to 76 (mirrored), z −2 to 108. 28.8 g. |
| Other masses (calculator) | core 223.6 g, funnel half 158.2 g, bearing race 20.1 g |
| Layer pitch (docs) | 160 mm |

Files used: `chute-core-fccd4907faf0.stl`, `chute-door-9291f5d03edc.stl`, `funnel-third-287f8f9936b9.stl`, `funnel-bracket-left-ced3172731e0.stl`, `funnel-bracket-right-f7932bce6ef7.stl`, `servo-adapter-flap-side-546231d66be3.stl` and `bearing-race-b832b7eab72a.stl`, all under `assets.basically.website/sorter-parts/`. The parts are assumed to share the assembly frame, except the servo adapter, whose position was taken from the shaft axis.

## 6. Estimates and assumptions

These are estimates, not measurements.

| Quantity | Value | Basis |
|---|---|---|
| Mass per layer (chute) | ≈ 0.65 kg | core + door + funnel third + 2 brackets + servo (55 g assumed) + connectors |
| Axial load on the bottom bearing | ≈ 3 kg for 5 layers | 0.65 kg × 5, without parts and screws |
| Inertia per layer | ≈ 0.005 kg·m² | funnel as a point mass at r ≈ 0.14 m plus the core |
| Angular acceleration | ≈ 50 rad/s² | assumed: 60° in about 0.3 s |
| Torque of one layer | ≈ 0.24 N·m | inertia × acceleration |
| Tangential force at r = 50 mm | ≈ 4.7 N | torque / radius |
| Weight preload per layer | ≈ 6.4 N | 0.65 kg × 9.81 |
| Axial release force of the cone | ≈ 0.9 N (10°) to 1.7 N (20°) | tangential force × tan(half-angle), friction ignored |
| Resulting margin against lift-off | ≥ 3× | preload / release force |
| Backlash with a plain clearance fit | ≈ 0.3° per joint | 0.5 mm play at r = 100 mm. Up to ≈ 1.4° over four joints, ≈ 5 mm at the funnel. |
| Lateral tolerance per layer | ±0.5 mm | assumed. ±2.5 mm worst case over five layers, about ±1 mm statistically. |
| Door torque to hold | ≈ 22 mN·m (door) + part | mass × g × 53 mm × cos 26° |

## 7. Open questions

1. **Envelope.** Does a ring plus a 15 to 20 mm lever fit in the band between the funnels at r ≈ 100 mm, or is a link to a larger radius needed? This needs checking against the real assembly.
2. **Rotation range and stations.** How many angular stations does the chute stack use, and how large is the allowed angular error at the funnel?
3. **Drive at the bottom.** Is there room under the bottom layer between the casters for a NEMA 23, gear train and limit switch?
4. **Coupling.** A tapered hex with an index key, or a face serration (Hirth type, 24 teeth) that also indexes? What cross-section and depth fit the 110 mm core interior?
5. **Part path.** The joint has to keep the interior of the core continuous so pieces pass from chute to chute without a step. What step is permissible?
6. **Top interface.** The rotating chute at the top would then follow the stack instead of being driven. Is the feeder entry tolerant enough for that?
7. **Extensibility.** How many layers does a module stack have to support (N = 3 to 5, or more)?

## Sources

<ul class="bulleted-list">
  <li><a href="{{ '/hardware/' | relative_url }}">The hardware build pages</a>: Chute, Door module, Layer adapter board, Funnel brackets, Top interface, Stacking the layers and Bottom interface.</li>
  <li>The <a href="https://parts-calculator.basically.website/">parts calculator</a> (STL files and masses).</li>
</ul>
