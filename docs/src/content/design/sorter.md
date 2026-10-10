---
layout: default
title: How the sorter is put together
type: explanation
section: design
slug: design-sorter
kicker: Design — The machine
lede: The sorter is a feeder that spreads a pile of bricks into single pieces, and a distribution system that drops each piece into the right bin. This page covers what each part does and what was tried before it.
permalink: /design/sorter/
last_verified: 2026-10-10
---

Sorter V2 is two machines stacked on top of each other. The **feeder** is a column of four rotating channels that turns a heap of loose LEGO into a single file of pieces and photographs them. The **distribution** system sits underneath: a rotating chute that aims at one of many bins, one layer at a time. A piece goes in at the top of the feeder and leaves through the chute into a bin. The electronics that connect the two have their own page, <a href="{{ '/design/electronics/' | relative_url }}">How the electronics talk to each other</a>.

## The feeder, from the top down

Every channel is a **C-channel**: a rotor turning inside a stator, driven by a NEMA 17 stepper through a gear train. One shared channel core is built four times, and the four stages are numbered C1 to C4 from the top.

<table>
<thead><tr><th>Stage</th><th>Job</th></tr></thead>
<tbody>
<tr><td>C1, bulk channel</td><td>Where unsorted parts go in. It has a Bulk cap, and no lamp or output guide.</td></tr>
<tr><td>C2 and C3, feeder channels</td><td>The two metering stages between C1 and C4. Each has a camera lamp for detection and an output guide.</td></tr>
<tr><td>C4, classification channel</td><td>Takes the pieces one or two at a time under the classification camera and hands each one to the distribution system. It uses a finned rotor and a cap, and the software calls it the carousel.</td></tr>
</tbody>
</table>

The drops between the channels do the separating, not vibration. Each stand sets an 80 mm step down to the next channel. Each channel only acts when the one in front of it has room, so the stack never pushes a piece onto a busy channel.

Cameras sit on C2, C3 and C4, each in a **camera lamp**: an LED strip ring in a white reflector under a grey cover, with the camera in the middle. C2 and C3 use a 720p camera for detection, C4 uses a 4K camera. Detection runs on all three, and identification uses the C4 crops.

### What was tried before

<ul class="bulleted-list">
<li><strong>A spiral labyrinth turntable.</strong> Clumps of pieces stayed clumped, small prototypes gave misleading results, a larger diameter made the machine too wide, and stacking turntables let the pieces clump again.</li>
<li><strong>A flat rotating V-channel.</strong> Nothing agitates the pieces, so it cannot separate them on its own.</li>
<li><strong>A vibratory V-channel on die springs.</strong> It worked, but it was loud.</li>
<li><strong>One big stair-step bulk feeder.</strong> The first generation used it, and C1 replaced it. A step feeder was also dropped as an idea because a piece lying badly may never ride up a step.</li>
<li><strong>More than four channels.</strong> Five channels in series showed the separation gain flattening out after about three.</li>
<li><strong>Light posts, an overhead camera mount and a classification dome.</strong> The camera lamp replaced all three, so each camera now brings its own light.</li>
<li><strong>Printed foot, leg and leg-extension stands.</strong> C1 now stands on 2020 extrusion legs and C2 and C3 on single printed legs. C4 sits flat on the top plate.</li>
</ul>

The feeder can run in three modes, Simple Pulse (the default), go-to-angle and constant movement. Which one is active is a software choice, and the lab page on <a href="{{ '/lab/software-architecture-decisions/' | relative_url }}">software architecture decisions</a> covers how the software is split.

### Where to find it

<ul class="bulleted-list">
<li><a href="{{ '/hardware/assembly/feeder/' | relative_url }}">Assembling the feeder</a>, with the <a href="{{ '/hardware/assembly/feeder/c-channels/' | relative_url }}">C-channels</a>, the <a href="{{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}">camera lamps</a> and <a href="{{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}">arranging the channels</a></li>
<li>Lab: <a href="{{ '/lab/c-channel-singulation/' | relative_url }}">C-channel singulation</a> and <a href="{{ '/lab/feeder-experiments/' | relative_url }}">feeder experiments</a></li>
<li>Feeder logic: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/subsystems/feeder/pulse_perception/flow.py">subsystems/feeder/pulse_perception/flow.py</a></li>
<li>Camera and detection: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/perception/channel.py">perception/channel.py</a></li>
</ul>

## Classification at C4

C4 is a small state machine called Two Piece. It turns one way, holds up to two pieces, and cycles through waiting, ejecting and staging. A piece is only released when the distribution system reports that its chute is ready. The chute and the layer door move at the same time, so the piece is never waiting for a door that has not started opening.

Pieces are identified from the C4 crops. Colour is read against a calibration card rather than by a learned model.

### What was tried before

<ul class="bulleted-list">
<li><strong>A carousel with an identification chamber.</strong> C4 replaced it. The reasons on record are that identification from several images of one piece was wanted, the chamber jammed, the bottom camera gave poor pictures and misread often, and C4 has fewer parts.</li>
<li><strong>Imaging a piece from several channels.</strong> It was built and then switched off, and the C4 crops are used on their own.</li>
<li><strong>Embeddings and then a classifier for recognition.</strong> These are covered on the <a href="{{ '/lab/classification-research/' | relative_url }}">classification research</a> page.</li>
</ul>

### Where to find it

<ul class="bulleted-list">
<li><a href="{{ '/hardware/assembly/feeder/c-channels/classification-channel/' | relative_url }}">Classification channel assembly</a></li>
<li>Lab: <a href="{{ '/lab/classification-research/' | relative_url }}">Classification research</a></li>
<li>Code: <a href="https://github.com/basicallysource/sorter-v2/tree/main/software/sorter/backend/subsystems/classification_channel/two_piece">subsystems/classification_channel/two_piece</a></li>
</ul>

## The distribution system

Distribution is a tower of layers. Each layer holds bins and has its own **chute**: a chute core with heat-set inserts, a door module with a servo, a layer adapter board, and funnel brackets that carry a funnel. The chutes of every layer are linked, and the whole stack rotates as one unit under a single NEMA 23 stepper. The bins never move. Once the stack points at a column of bins, the door of the right layer opens and the piece drops into the bin below it.

<ul class="bulleted-list">
<li><strong>Top interface.</strong> The interface between the feeder and the bin tower, where the rotating chute starts. It carries the stepper that turns the stack. A 120 to 25 gear ratio turns it, with a 350 degree hard stop and six sections by default.</li>
<li><strong>Bin tower.</strong> A hex frame with the layers stacked in it, 160 mm per layer. A layer holds 18 bins with a third funnel or 12 with a half funnel, chosen per layer. Three and five layers are the common builds, and the firmware can drive up to 16.</li>
<li><strong>Bottom interface.</strong> A Lazy Susan bearing the stack rests on, so it turns freely at the base. The top interface uses the same stock 8 inch bearing.</li>
<li><strong>Bins.</strong> One per sorting target, held in place by retainers.</li>
</ul>

### What was tried before

<ul class="bulleted-list">
<li><strong>A linear layout.</strong> The first design carried pieces on a conveyor to tipping bins. It is more expandable and suits a wall, and it was compared with the circular design. The circular stack was chosen as the machine for this version.</li>
<li><strong>Idler wheels on bearing races at the foot of the stack.</strong> The wheels wore and tore at the races and came unscrewed. The bottom Lazy Susan replaced them, and a double Lazy Susan ran a week without problems.</li>
<li><strong>Early chute drops.</strong> About 78 per cent of test drops landed in the right place. A later test with taller bin walls and a soft flap landed 20 of 20. No figure exists yet for the current geometry.</li>
<li><strong>Wiring the rotating stack.</strong> Slip rings and a static servo were discussed. Nothing was adopted, and the layer boards are chained together by ribbon cable.</li>
</ul>

### Where to find it

<ul class="bulleted-list">
<li><a href="{{ '/hardware/assembly/distribution/' | relative_url }}">Assembling the distribution</a>, with the <a href="{{ '/hardware/assembly/distribution/top-interface/' | relative_url }}">top interface</a>, the <a href="{{ '/hardware/assembly/distribution/chute/' | relative_url }}">chute</a>, the <a href="{{ '/hardware/assembly/distribution/bin-frame/' | relative_url }}">bin frame</a> and the <a href="{{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}">bottom interface</a></li>
<li><a href="{{ '/hardware/assembly/install-bins/' | relative_url }}">Installing the bins</a></li>
<li>Part page: <a href="{{ '/hardware/parts/lazy-susan/' | relative_url }}">Lazy Susan</a></li>
<li>Code: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/subsystems/distribution/chute.py">subsystems/distribution/chute.py</a></li>
</ul>

## How the software drives it

A host computer runs the vision, the flow logic and the web interface, and a Pico runs a deliberately simple firmware that moves motors and servos on command. The split was chosen after Klipper, ROS2, Marlin and Firmata were considered, and the reasons are on the <a href="{{ '/lab/software-architecture-decisions/' | relative_url }}">software architecture decisions</a> page. Which pin does what, and how the two talk, is covered in <a href="{{ '/design/electronics/' | relative_url }}">How the electronics talk to each other</a>. Which cable goes in which socket is on <a href="{{ '/hardware/electronics/connecting/' | relative_url }}">Connecting the components</a>.

### Where to find it

<ul class="bulleted-list">
<li><a href="{{ '/design/electronics/' | relative_url }}">How the electronics talk to each other</a></li>
<li><a href="{{ '/lab/software-architecture-decisions/' | relative_url }}">Lab: software architecture decisions</a></li>
<li>Firmware: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/sorter_interface_firmware.cpp">sorter_interface_firmware.cpp</a></li>
</ul>
