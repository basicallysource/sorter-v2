---
layout: default
title: Abandoned ideas
type: explanation
section: lab
slug: lab-abandoned-ideas
kicker: Design and research — Variants
lede: Designs that were built, tried or proposed for Sorter V2 and then dropped, with a short description of each and why it went.
permalink: /lab/variants/abandoned/
audience: curious builder or contributor
applies_to: hardware-v2
owner: docs
last_verified: 2026-10-11
---

This page is the other half of <a href="{{ '/lab/variants/' | relative_url }}">Tested variants</a>. A tested variant is a change somebody is running on their own machine. Everything here was dropped, replaced or set aside. None of it is part of the build, and you do not need it to build a sorter. It is here so that an old photo, an old forum post or an old message does not send you back to a design the project has left.

Each entry says what the idea was and why it went, as far as the reasons are written down. Where the reason is not on record, the entry says so. The status of each is as of 11 October 2026.

## Classification

### The carousel and the identification chamber

**What it was.** Earlier machines ended in a carousel: a rotating platform that carried one piece at a time into a closed classification chamber. A camera above and a camera below, looking up through an acrylic sheet, photographed the piece before it was released to the chute.

**Why it was dropped.** There was no single cause.

<ul class="bulleted-list">
  <li><strong>Something simpler did the job.</strong> In April 2026 a builder replaced the carousel with a fourth C-channel: a flat rotor with a camera and lights above it. That is the classification channel (C4) of today. At the <a href="https://www.youtube.com/watch?v=6GWR7YUG_e0&amp;t=1462s">19 April meeting</a> the agreement was that if its throughput was comparable and its accuracy was north of 90%, the project would go ahead with it and stop putting effort into the carousel.</li>
  <li><strong>The staged photo was no longer needed.</strong> The service that identifies the pieces accepts up to eight images of one piece in a single request, so the piece does not have to be held still in a studio for one good shot (same meeting).</li>
  <li><strong>It jammed.</strong> Large pieces jammed against the chamber wall, and a piece sometimes landed standing upright. A taller wall helped with that but meant a longer drop, so more energy and more bounce (<a href="https://discord.com/channels/1430279849171222682/1440488123279736912/1492957783333802075">12 April 2026</a>).</li>
  <li><strong>The view from below was poor.</strong> The identification service was failing in roughly 15% of cases, which was put down to glare on the acrylic sheet and to pieces that had rolled to the back and blended into the platform (<a href="https://www.youtube.com/watch?v=Jl2zgY1sGUw&amp;t=2691s">8 March meeting</a>). At the <a href="https://www.youtube.com/watch?v=LbUg7IYcBmo">23 March meeting</a> the bottom camera was described as seeing the platform at such a steep angle, through so much glass and glare, that the picture was not very useful.</li>
  <li><strong>Fewer parts.</strong> C4 is built from the same kind of channel as the three above it.</li>
</ul>

**Where it stands.** By <a href="https://discord.com/channels/1430279849171222682/1440488123279736912/1528766303815602236">20 July 2026</a> a contributor wrote that the whole carousel idea "has been canned for now". The word survives in the software, where the C4 stepper and the C4 camera are still called the carousel (<a href="{{ '/sorter/machine-toml-reference/' | relative_url }}">machine.toml reference</a>).

<ul class="bulleted-list">
  <li>The channel that replaced it: <a href="{{ '/hardware/assembly/feeder/c-channels/classification-channel/' | relative_url }}">Classification channel assembly</a></li>
  <li>How C4 works now: <a href="{{ '/lab/sorter/' | relative_url }}">How the sorter is put together</a></li>
</ul>

### Identifying a piece from images taken in several channels

**What it was.** The April 2026 plan was to follow each piece through the C-channels and send pictures from every stage to the identification service together.

**Why it was dropped.** It was built and then switched off. Only pictures from C4 are sent now, so that the identity the machine commits to is always a view of the piece after it has landed. Two reasons are written in the code. A test that gave priority to frames taken while the piece was falling failed: the frames were too blurred, and the service identified nothing in the test (a very small test, two runs). And the link that handed a piece from one channel's camera to the next was cut, because when pieces clump, a wrong hand-over merges two pieces into one query.

A piece that lies face down is therefore still seen from above only. That is an open problem, not a solved one.

### Embeddings for recognising pieces

**What it was.** The first approach to recognition compared a new picture with a database of stored picture fingerprints (embeddings, from a model called DINO V2) and took the closest.

**Why it was dropped.** One badly photographed example in the database could poison a whole class: a 1 x 2 brick photographed without its pin showing confused the model between the plain and the pinned brick. After about four weeks a regular classifier was found to do better once there are enough good, varied images of each part.

<ul class="bulleted-list">
  <li>The comparison: <a href="{{ '/lab/classification-research/' | relative_url }}">Classification research</a></li>
</ul>

### Reading colour with machine learning

**What it was.** Having a model decide the colour of a piece.

**Why it was dropped.** Lighting differs between machines and rooms, and machine-learning colour detection did not hold up across them. Colour is read by comparing the piece with a calibration card in the picture instead (<a href="{{ '/lab/classification-research/' | relative_url }}">Classification research</a>).

## The feeder

The experiments below came before the C-channels. The full write-up, with the numbers, is on <a href="{{ '/lab/feeder-experiments/' | relative_url }}">Feeder experiments</a>.

### A spiral labyrinth turntable

**What it was.** A spinning disc with spiral walls, meant to separate pieces over distance using the motion of the disc.

**Why it was dropped.** Clumps stayed clumped, and pieces mostly drifted outwards without touching the walls. Small prototypes gave misleadingly good results. A larger disc separated better but made the machine too wide, and stacking two discs let the pieces clump again.

### A flat rotating V-channel

**What it was.** A flat turning table that carried pieces in a line to a fixed exit.

**Why it was dropped.** It moves pieces but nothing agitates them, so it cannot separate them. It only works if the pieces arrive already separated.

### A vibrating V-channel

**What it was.** A V-shaped channel shaken on compression springs.

**Why it was dropped.** It separated pieces well, but it was loud. Rotating channels, where the drop from one channel to the next does the separating, replaced the vibration.

### A stair-step feeder

**What it was.** The first generation used one large stair-step bulk feeder. C1 replaced it. The idea has since been proposed again, in a smaller form, as a way to feed pieces one at a time.

**Why it was dropped.** The step size and angle have to be such that any piece will ride up the step. That works in a bulk bucket, where a piece lies almost flat on its side, but not for the full range of LEGO pieces (<a href="https://discord.com/channels/1430279849171222682/1457470938873331834/1460770147936501871">13 January 2026</a>).

<ul class="bulleted-list">
  <li>A single step feeder that is being tried: <a href="{{ '/lab/variants/' | relative_url }}">Tested variants</a></li>
</ul>

### Round rotors

**What it was.** A rotor with a round outline.

**Why it was dropped.** A round rotor touches a long piece at only one point, while the stator wall touches it at two, so large pieces do not move along. The facets of the faceted rotor turn that point into a line of contact (<a href="https://discord.com/channels/1430279849171222682/1460692585881534579/1475959145181216789">the original explanation</a>).

### More than four channels

**What it was.** A builder put five C-channels in series to see how evenly the pieces could be spread from the bulk channel to the last (<a href="https://discord.com/channels/1430279849171222682/1460692585881534579/1475427028772585595">23 February 2026</a>).

**Why it was dropped.** The separation levelled off after about three channels: pieces ended up queued rather than spread out. The standard machine has four, and no comparison of throughput between different numbers of channels exists.

### Light posts, the overhead camera mount and the classification dome

**What they were.** Each feeder channel had a vertical post with a lamp on its end, and the cameras hung on an overhead mount from two steel rods. The classification channel had a large white dome over it.

**Why they were dropped.** The camera lamp replaced all of them. It was designed to do away with soldering, to lock the camera position so that nothing needs adjusting, and to remove the big dome, so that the camera arm, lights and bracket are the same on all three channels (<a href="https://www.youtube.com/watch?v=fnBvE-yFbLc">30 August 2026 meeting</a>). These parts are marked as not used in the parts calculator, and old photos of them show a design that is no longer built.

<ul class="bulleted-list">
  <li>What replaced them: <a href="{{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}">Camera lamps</a></li>
</ul>

### Printed feet, legs and leg extensions

**What they were.** The first stands for the channels, built from a foot, a leg and up to two leg extensions stacked on each other.

**Why they were dropped.** They worked, but they were unstable. The layout guide, the support legs and the dovetail adapters replaced them. C1 now stands on 2020 extrusion legs, and C2 and C3 on single printed legs.

<ul class="bulleted-list">
  <li>The current stands: <a href="{{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}">Arranging C-channels</a></li>
</ul>

## Distribution

### A linear layout

**What it was.** The first design carried pieces along a conveyor to tipping bins, in a line, instead of down a stack of layers.

**Why it was set aside.** It is more expandable and suits a wall, and it was compared with the circular design at the <a href="https://www.youtube.com/watch?v=mVQgnf22BZg">11 November 2025 meeting</a>. The circular stack was chosen for this version: one stepper serves every slot, there are no belts to assemble and tune, and a position is just an angle and a layer number. A linear version has been discussed again since, in the Discord, and nothing has been decided about it.

<ul class="bulleted-list">
  <li>The reasons for the circle: <a href="{{ '/lab/sorter/' | relative_url }}">How the sorter is put together</a></li>
</ul>

### Idler wheels at the foot of the stack

**What it was.** Wheels running on bearing races that held the rotating stack in place at the bottom.

**Why it was dropped.** The wheels wore and tore at the races, and came unscrewed. The Lazy Susan bearing replaced them and was judged more stable (<a href="https://www.youtube.com/watch?v=MJcjmxJ-uq8">7 June 2026 meeting</a>).

<ul class="bulleted-list">
  <li>The bearing: <a href="{{ '/hardware/parts/lazy-susan/' | relative_url }}">Lazy Susan</a></li>
</ul>

## Electronics and software

### Boards on plates screwed to the extrusion

**What it was.** The control board and the Orange Pi each stood on a printed plate bolted to the 2020 extrusion, with a 40 mm fan on a bracket over the board.

**Why it was dropped.** The printed control board housing replaced the plate on 23 August 2026, and the printed Orange Pi housing replaced the other in September 2026. The reason for the move is not written down in the parts calculator. The fan bracket went because each housing now carries its own fan, or the Orange Pi's own heatsink fan does the job. Old photos still show the plates.

<ul class="bulleted-list">
  <li>The housings: <a href="{{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}">Orange Pi housing</a></li>
</ul>

### The three-plate box for the power supply

**What it was.** Three printed plates screwed onto the Mean Well 24 V supply's own case.

**Why it was dropped.** The cap was not secure. The five-piece PSU housing, whose two lids screw down, replaced it in September 2026.

### Firmata for talking to the motor board

**What it was.** The first version of the machine used Firmata, a ready-made protocol for controlling a microcontroller from a computer.

**Why it was dropped.** Its 7-bit encoding mangled data, the project is effectively dead, and its threading behaved unreliably. The current firmware uses its own protocol, over USB. Klipper, ROS 2, Marlin and Wi-Fi to the board were also considered and rejected (<a href="{{ '/lab/software-architecture-decisions/' | relative_url }}">Software architecture decisions</a>).
