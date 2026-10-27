---
layout: default
title: How the sorter is put together
type: explanation
section: lab
slug: lab-sorter
kicker: Design and research — The machine
lede: The sorter is a feeder that spreads a pile of bricks into single pieces, and a distribution system that drops each piece into the right bin. This page covers what each part does and what was tried before it.
permalink: /lab/sorter/
audience: curious builder or contributor
applies_to: hardware-v2
owner: docs
last_verified: 2026-10-10
---

Sorter V2 is two machines stacked on top of each other. The **feeder** is a column of four rotating channels that turns a heap of loose LEGO into a single file of pieces and photographs them. The **distribution** system sits underneath: a rotating chute that aims at one of many bins, one layer at a time. A piece goes in at the top of the feeder and leaves through the chute into a bin. The electronics that connect the two have their own page, <a href="{{ '/lab/electronics/' | relative_url }}">How the electronics talk to each other</a>.

## The feeder, from the top down

Every channel is a **C-channel**: a rotor (the spinning part) turning inside a stator (the fixed housing around it). A NEMA 17 stepper motor, which turns in small exact steps, drives the rotor through gears (the motors have their own page, <a href="{{ '/lab/motors/' | relative_url }}">The motors</a>). One shared channel core is built four times, and the four stages are numbered C1 to C4 from the top.

<table>
<thead><tr><th>Stage</th><th>Job</th></tr></thead>
<tbody>
<tr><td>C1, bulk channel</td><td>Where unsorted parts go in. It has a Bulk cap, and no lamp or output guide.</td></tr>
<tr><td>C2 and C3, feeder channels</td><td>The two metering stages between C1 and C4. Each has a camera lamp for detection and an output guide.</td></tr>
<tr><td>C4, classification channel</td><td>Takes the pieces one or two at a time under the classification camera and hands each one to the distribution system. It uses a finned rotor and a cap, and the software calls it the carousel.</td></tr>
</tbody>
</table>

The drops between the channels do the separating, not vibration. Each stand sets an 80 mm step down to the next channel. Each channel only moves when the channel after it has room, so a piece is never pushed onto a busy channel.

Cameras sit on C2, C3 and C4, each in a **camera lamp**: an LED strip ring in a white reflector under a grey cover, with the camera in the middle. The lamp was designed to do away with soldering, to lock the camera position so nothing needs adjusting, and, as a side effect, to remove the big white dome and make the camera arm, lights and bracket identical on all three channels (the <a href="https://www.youtube.com/watch?v=fnBvE-yFbLc">30 August 2026 meeting</a>). Why the light is arranged the way it is has its own page, <a href="{{ '/lab/lighting/' | relative_url }}">How the cameras are lit</a>. C2 and C3 use a 720p camera for detection, C4 uses a 4K camera. Detection runs on all three. Identification only uses the C4 crops, which are close-up images cut out around each piece.

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

The software can move a channel's motor in three ways: Simple Pulse (the default), go-to-angle and constant movement. Which one is used is a software setting. The page on <a href="{{ '/lab/software-architecture-decisions/' | relative_url }}">software architecture decisions</a> covers how the software is split.

### Why it is built this way

<ul class="bulleted-list">
<li><strong>Several channels in a row.</strong> The drop from one channel to the next has some chance of untangling a clump, so the more channels are stacked in series, the closer the separation gets to complete (<a href="https://discord.com/channels/1430279849171222682/1460692585881534579/1483959968620216392">March 2026</a>).</li>
<li><strong>The 80 mm step.</strong> Each step down to the next channel is 80 mm. No designer has said why this value was chosen, so this is the closest thing on record rather than a confirmed reason. The channels were designed so that a piece fitting inside an 80 mm ball can clear every opening, and Marc said that putting one channel over another would mean raising it by at least another 6 cm "to clear that 80mm clearance ball" (<a href="https://discord.com/channels/1430279849171222682/1460692585881534579/1492222149060984832">April 2026</a>). A step smaller than the largest supported piece would leave it touching two channels at once, which is the same guess a builder made in the <a href="https://discord.com/channels/1430279849171222682/1558828453745401897">design question thread</a>. A taller step has a cost too: the height of the feeder takes away from the number of layers that fit under a given machine height (<a href="https://discord.com/channels/1430279849171222682/1460692585881534579/1493968848968355950">April 2026</a>). We are still asking the designers whether the 80 mm step was derived from the part envelope.</li>
<li id="camera-crop"><strong>The cameras on C2 and C3 do not see the whole rotor.</strong> This is intended. The top and bottom of the ring do not need to be seen. What the software has to follow is the drop, where a piece lands from the channel above, and the exit, where it leaves for the next channel, and a camera that sits closer puts more pixels on those two places. It also keeps the camera arm short and the feeder more compact (<a href="https://discord.com/channels/1430279849171222682/1503528472818094220/1549467425508954143">September 2026</a>). Raising the camera 7 cm shows the whole rotor, and measured from two screenshots of the same camera it costs about 24% of the pixels per millimetre (146 pixels per inch at the rim of the rotor against 112). The stated reason for caring about that resolution is to be able to use the pictures from the channels for classification (<a href="https://discord.com/channels/1430279849171222682/1503528472818094220/1549846512043823138">September 2026</a>). The cost of the crop is that a piece can ride out of view and come back further round. Early on, a channel could forget a piece it could no longer see and stop turning, which was agreed to be still a problem (<a href="https://discord.com/channels/1430279849171222682/1503528472818094220/1549470257322790973">report</a>, <a href="https://discord.com/channels/1430279849171222682/1503528472818094220/1549477430975275080">reply</a>), and the view was not changed to fix it. Instead, a feeder setting called <strong>Out of view</strong> (since 30 September 2026, off by default) tells the machine which arc of C2 or C3 is unseen, so the channel keeps turning while a piece is in it. How to set it is in <a href="{{ '/sorter/first-setup/' | relative_url }}#step-7-cameras">step 7 of first setup</a>.</li>
<li><strong>The shape of the rotors.</strong> The faceted rotor, and why a round rotor fails on long pieces, is explained on <a href="{{ '/lab/printed-parts/' | relative_url }}">Design intentions for the printed parts</a>, with the <a href="https://discord.com/channels/1430279849171222682/1460692585881534579/1475959145181216789">original explanation</a>. The finned rotor on C4 has small walls on the facets that force pieces to move, so that they end up separated and can be classified and ejected cleanly into the distribution (the <a href="https://www.youtube.com/watch?v=MJMTEVCeBLs">26 April 2026 meeting</a>).</li>
</ul>

### Where to find it

<ul class="bulleted-list">
<li><a href="{{ '/hardware/assembly/feeder/' | relative_url }}">Assembling the feeder</a>, with the <a href="{{ '/hardware/assembly/feeder/c-channels/' | relative_url }}">C-channels</a>, the <a href="{{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}">camera lamps</a> and <a href="{{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}">arranging the channels</a></li>
<li>Research: <a href="{{ '/lab/c-channel-singulation/' | relative_url }}">C-channel singulation</a> and <a href="{{ '/lab/feeder-experiments/' | relative_url }}">feeder experiments</a></li>
<li>Feeder logic: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/subsystems/feeder/pulse_perception/flow.py">subsystems/feeder/pulse_perception/flow.py</a></li>
<li>Camera and detection: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/perception/channel.py">perception/channel.py</a></li>
</ul>

## Classification at C4

C4 is controlled by a small program called Two Piece. It is always in one of a few states, and it moves from one to the next as pieces arrive and leave. It turns one way, holds up to two pieces, and cycles through waiting, ejecting and staging. A piece is only released when the distribution system reports that its chute is ready. The chute and the layer door move at the same time, so the piece is never waiting for a door that has not started opening.

Pieces are identified from the C4 crops. Colour is read by comparing the piece with a calibration card, not by an AI model.

### What was tried before

<ul class="bulleted-list">
<li><strong>A carousel with an identification chamber.</strong> C4 replaced it. The reasons on record are that identification from several images of one piece was wanted, the chamber jammed, the bottom camera gave poor pictures and misread often, and C4 has fewer parts.</li>
<li><strong>Imaging a piece from several channels.</strong> It was built and then switched off, and the C4 crops are used on their own.</li>
<li><strong>Two machine-learning methods for recognising pieces: embeddings, and then a classifier.</strong> These are covered on the <a href="{{ '/lab/classification-research/' | relative_url }}">classification research</a> page.</li>
</ul>

### Why it is built this way

<ul class="bulleted-list">
<li><strong>Two pieces at a time.</strong> C4 holds up to two pieces at a time. We are currently trying to find out why this was decided this way, and will add the reason or an explanation later.</li>
<li><strong>Identification by an online service.</strong> The plan for now is to stay with Brickognize, because telling apart the 20 or more blue shades reliably would need a model that knows the exact camera settings and lighting (<a href="https://discord.com/channels/1430279849171222682/1437511568194666596/1486065747682656368">March 2026</a>). It is free, and the models that find where pieces are run locally for free (<a href="https://discord.com/channels/1430279849171222682/1430279852015091804/1520811400878886913">June 2026</a>). Others argued for the project's own models, since a picture good enough for a person to recognise should be good enough for the software too (<a href="https://discord.com/channels/1430279849171222682/1480683231555617020/1480689801777905664">March 2026</a>). A local model for offline use is planned, with no date.</li>
</ul>

### Where to find it

<ul class="bulleted-list">
<li><a href="{{ '/hardware/assembly/feeder/c-channels/classification-channel/' | relative_url }}">Classification channel assembly</a></li>
<li>Research: <a href="{{ '/lab/classification-research/' | relative_url }}">Classification research</a></li>
<li>Code: <a href="https://github.com/basicallysource/sorter-v2/tree/main/software/sorter/backend/subsystems/classification_channel/two_piece">subsystems/classification_channel/two_piece</a></li>
</ul>

## The distribution system

Distribution is a tower of layers. Each layer holds bins and has its own **chute**: a chute core with heat-set inserts, a door module with a servo, a layer adapter board, and funnel brackets that carry a funnel. The chutes of every layer are linked, and the whole stack rotates as one unit under a single NEMA 23 stepper. The bins never move. Once the stack points at a column of bins, the door of the right layer opens and the piece drops into the bin below it.

<ul class="bulleted-list">
<li><strong>Top interface.</strong> The interface between the feeder and the bin tower, where the rotating chute starts. It carries the stepper that turns the stack. Gears with a ratio of 120 to 25 turn it. It can turn up to 350 degrees, where a hard stop ends the movement. The software divides the turn into six sections by default.</li>
<li><strong>Bin tower.</strong> A hex frame with the layers stacked in it, 160 mm per layer. A layer holds 18 bins with a third funnel or 12 with a half funnel, chosen per layer. Three and five layers are the common builds. One ribbon chain reaches up to ten layers, see <a href="{{ '/lab/servos/' | relative_url }}">The servos and the layer adapter boards</a>.</li>
<li><strong>Bottom interface.</strong> A Lazy Susan bearing the stack rests on, so it turns freely at the base. The top interface uses the same stock 8 inch bearing.</li>
<li><strong>Bins.</strong> One per sorting target, held in place by retainers.</li>
</ul>

### What was tried before

<ul class="bulleted-list">
<li><strong>A linear layout.</strong> The first design carried pieces on a conveyor to tipping bins. It is more expandable and suits a wall, and it was compared with the circular design. The circular stack was chosen as the machine for this version.</li>
<li><strong>Idler wheels on bearing races at the foot of the stack.</strong> The wheels wore and tore at the races and came unscrewed. The bottom Lazy Susan replaced them, and a double Lazy Susan ran a week without problems.</li>
<li><strong>Early chute drops.</strong> About 78 per cent of test drops landed in the right place. A later test with taller bin walls and a soft flap landed 20 of 20. No figure exists yet for the current geometry.</li>
<li><strong>Wiring the rotating stack.</strong> Slip rings (parts that pass power to something that turns) and a static servo were discussed. Nothing was adopted, and the layer boards are chained together by ribbon cable. Serial servos, which would cut the wires to the layers, are planned for a later board revision. Reasons and open points are on <a href="{{ '/lab/servos/' | relative_url }}">The servos and the layer adapter boards</a>.</li>
</ul>

### Why it is built this way

<ul class="bulleted-list">
<li><strong>A circular stack.</strong> Reasons given when it was proposed (the <a href="https://www.youtube.com/watch?v=mVQgnf22BZg">11 November 2025 meeting</a>): one stepper can serve every slot, there are no belts to assemble, tune and maintain, a position is just an angle and a layer number, and a change of bin size changes the footprint of the machine less than it would in a linear layout. Later in the Discord (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1458078883747332202">January 2026</a>): a machine is made bigger or smaller by stacking more layers, there are no belts or gantries to calibrate, and modularity was a key requirement that a gantry cannot give (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1458084887449043036">same thread</a>). The linear layout was kept in mind as a more expandable option that suits a wall, and the meeting agreed to go ahead with the circle.</li>
<li><strong>One stepper and a gear.</strong> A printed gear was chosen over a belt because there is no belt of the right size to source (the <a href="https://www.youtube.com/watch?v=7Z1wlY-plNo">5 December 2025 meeting</a>). </li>
<li><strong>The gear ratio.</strong> The chute is turned by a 25-tooth motor gear, a 25-tooth idler gear and a 120-tooth gear on the chute, a reduction of 4.8 to 1. A large reduction was wanted from the start: a large gear on the chute alone gives roughly eight to one (the <a href="https://www.youtube.com/watch?v=7Z1wlY-plNo&amp;t=1040">5 December 2025 meeting</a>). In January 2026 the ratio was 5 to 1, aiming for 25 to 30 rpm at the chute, a full turn in about 3 seconds, which is about 150 rpm at the motor (the <a href="https://www.youtube.com/watch?v=TOuqbUtFj0I&amp;t=4734">10 January 2026 meeting</a>). The idler is there because the chute moves up and down by about a millimetre as it turns, which is the height of a gear tooth. With a bevel gear that was enough to lose the mesh and make the motor skip. The first spur-gear version did not have the problem but got in the way of the cable cage, and an idler between the motor and the chute was proposed instead (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1472140981875769375">February 2026</a>, <a href="https://www.youtube.com/watch?v=hyDhw8clVdc&amp;t=840">15 February 2026 meeting</a>). An idler also makes the ratio easy to tune: changing the size of the motor gear and the idler changes the speed and torque of the chute without moving the stepper or the chute gear. A small idler with a big motor gear gives more speed, a big idler with a small motor gear gives more torque (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1472142868805193890">same thread</a>). Why the tooth counts are exactly 25, 25 and 120 has not been written down, and we are still trying to find out.</li>
<li><strong>Almost a full turn, with a hard stop.</strong> The chute cannot turn all the way round, because a continuous spin would destroy the cable that runs to the layers (<a href="https://www.youtube.com/watch?v=7Z1wlY-plNo">same meeting</a>). The 351 degrees come from the printed stop (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1480830210889879613">March 2026</a>).</li>
<li><strong>Six sections.</strong> A layer has six structural dividers (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1440614728081608774">November 2025</a>), and one slot is a sixth of a layer (<a href="https://discord.com/channels/1430279849171222682/1448367089399365683/1450792587727208458">December 2025</a>). A slot holds three third-size bins or two half-size bins (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1514357594100334714">June 2026</a>), which is where 18 and 12 per layer come from.</li>
<li><strong>The bin sizes.</strong> Only the third-size and half-size bins are used, and the large size is not. No designer has stated a reason, so this is the closest thing on record rather than a confirmed one. The only reason offered is capacity: a layer holds 18 third-size bins or 12 half-size bins, and the larger the bin, the fewer a layer holds. A designer of the original chute and layer family guessed the same, "best guess is for most capacity", while saying they did not know why it was dropped (<a href="https://discord.com/channels/1430279849171222682/1558831925743976530/1560186923165810802">October 2026</a>). It also matches how the sizes were set. In November 2025 a small, medium and large family was described, with the smallest bin dictating the size of the funnel (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1444460197677371447">November 2025</a>). By February 2026 "big medium small" was called arbitrary, and the sizes were restated as a number of bins per layer, which allowed six (full width), 12, 18, 24 or 30 (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1477429588723236864">February 2026</a>). The third size was designed to fit a piece at least 48 mm (6 studs) wide and the half size one at least 64 mm (8 studs) wide, with some room to spare. A full-width "mega bin" for an 80 mm piece, with one bin across the whole section and a much shorter funnel, has not been designed (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1514397217505673316">June 2026</a>). So the large size was not removed from a finished design, it was never drawn. Whether capacity was the deciding reason is still unconfirmed.</li>
<li><strong>A closed funnel.</strong> Pieces bounce and lose energy, and can still get stuck in a shallow funnel, so the funnel should be covered to stop them jumping out (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1457463288328622232">January 2026</a>, <a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1457463873019052163">same thread</a>). The 11 November 2025 meeting made the same point about the chute.</li>
<li><strong>The height of a layer.</strong> Each layer is 160 mm tall because the bins are tilted. A bin is 80 mm high and is tilted by 30 degrees, and a bin of that size at that angle takes up exactly 160 mm of height (<a href="https://discord.com/channels/1430279849171222682/1558828441678118953/1558842994545660105">a designer's answer and sketch, October 2026</a>). The 30 degrees is the angle of the chute, and the bin is tilted to match it, so that the gap between the chute and the bin wall is small and pieces do not jump out (the <a href="https://youtube.com/watch?v=TOuqbUtFj0I&amp;t=2670">10 January 2026 meeting</a>). The first chute was about 13 degrees, and pieces got stuck on it (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1456778822644142122">January 2026</a>). In the same meeting, 25 degrees was reported as still too shallow for a piece to keep sliding once it has lost its speed, and 30 degrees was chosen so that it keeps sliding (<a href="https://youtube.com/watch?v=TOuqbUtFj0I&amp;t=4298">recording</a>; the transcript is hard to read at that point). The chute was changed to 30 degrees on <a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1457377610681155616">4 January 2026</a>. A steeper chute leaves less room for the bin under the funnel, which has to be 65 mm high inside, so the layers were made taller in exchange (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1457440975029796926">same day</a>).</li>
<li><strong>The hexagon.</strong> The frame is a hexagon because it was the easiest shape to build for the form factor the machine was designed around. A circle is hard to make, and every extra side means more pieces, so six sides was a good middle ground (<a href="https://discord.com/channels/1430279849171222682/1558831340323995699/1559113573488402474">the designer's answer, October 2026</a>). No one wrote down a reason for the number six at the time, so this is the designer's recollection rather than a recorded decision. The path to it is recorded. The stack started as a circle, because a round design is simpler and holds more bins for a given footprint (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1438251842583658739">November 2025</a>). Straightening the curves into "more of a multi hexagon" was suggested so that the cardboard bins could be cut flat and folded, at the cost of a little space (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1438187241355608136">same month</a>). The frame then moved from plywood to 2020 aluminum extrusion with straight segments (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1444456887054761989">29 November 2025</a>).</li>
<li><strong>The Lazy Susan bearings.</strong> The bottom bearing replaced wheels that tore into their bearing races and could come unscrewed, and it was judged more stable (the <a href="https://www.youtube.com/watch?v=MJcjmxJ-uq8">7 June 2026 meeting</a>). The top one is only for aligning the driving gear (the <a href="https://www.youtube.com/watch?v=w-2Jn6bx13Q">1 March 2026 meeting</a>).</li>
<li><strong>The bearing size.</strong> The Lazy Susan bearings are 8 inch (200 mm). No reason for that size has been found in the record. What is on record is how a Lazy Susan was chosen at all and what the size constrains. The load on the bottom is only thrust, so a Lazy Susan style slew ring bearing could be an option (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1440090798787006585">November 2025</a>), and the centre section was to rotate on an upper and a lower one (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1442937006035566784">same month</a>). A specific bearing was picked tentatively for the top and bottom on <a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1448375181805617274">10 December 2025</a>. The bearing's inner diameter is the biggest opening the chute can have, so the chute narrows to it (the <a href="https://www.youtube.com/watch?v=7Z1wlY-plNo&amp;t=421s">5 December 2025 meeting</a>). The models follow the part that was bought: a designer found theirs measured 202 mm, not 200, and corrected the model (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1452029807620788255">December 2025</a>). 8 inch is 203.2 mm and similar listings differ slightly, which raised a worry about sourcing, since there is no standard between them (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1452049821023207586">same day</a>). So 200 mm looks like the nominal size of the part the design was built around, but that is an inference, not a stated reason. We are still asking the designers why 8 inch rather than another size, and will add the answer when we have it.</li>
</ul>

### Where to find it

<ul class="bulleted-list">
<li><a href="{{ '/hardware/assembly/distribution/' | relative_url }}">Assembling the distribution</a>, with the <a href="{{ '/hardware/assembly/distribution/top-interface/' | relative_url }}">top interface</a>, the <a href="{{ '/hardware/assembly/distribution/chute/' | relative_url }}">chute</a>, the <a href="{{ '/hardware/assembly/distribution/bin-frame/' | relative_url }}">bin frame</a> and the <a href="{{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}">bottom interface</a></li>
<li><a href="{{ '/hardware/assembly/install-bins/' | relative_url }}">Installing the bins</a></li>
<li>Part page: <a href="{{ '/hardware/parts/lazy-susan/' | relative_url }}">Lazy Susan</a></li>
<li>Code: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/subsystems/distribution/chute.py">subsystems/distribution/chute.py</a></li>
</ul>

## How the software drives it

A computer, the Orange Pi, runs the camera vision, decides what happens next and serves the web interface. A small Pico board only moves motors and servos when told to. The reasons for that split, and the alternatives that were rejected, are on <a href="{{ '/lab/software-architecture-decisions/' | relative_url }}">Software architecture decisions</a>. The rest is on <a href="{{ '/lab/electronics/' | relative_url }}">How the electronics talk to each other</a>, which links on to the pin list, the motors and the servos.
