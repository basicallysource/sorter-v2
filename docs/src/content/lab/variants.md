---
layout: default
title: Tested variants
type: explanation
section: lab
slug: lab-variants
kicker: Design and research — Variants
lede: Alternatives to the standard design that people have built or are trying, and where each one stands.
permalink: /lab/variants/
audience: curious builder or contributor
applies_to: hardware-v2
owner: docs
last_verified: 2026-10-11
---

Everything on this page is a variant: a change to the standard Sorter V2 that somebody has made on their own machine. None of them is part of the build instructions in [Hardware]({{ '/hardware/' | relative_url }}), and none is in the parts calculator. The results are what the people who built them reported, and the project has not measured them. Where a file exists it is in the Discord, and the link goes to the message that has it.

Designs that were tried and dropped are on <a href="{{ '/lab/variants/abandoned/' | relative_url }}">Abandoned ideas</a>. The status of each variant is as of 11 October 2026.

## Belt feeder

**What is different.** A printed belt with raised catches on it carries LEGO up out of a large hopper and drops it into the feeder. It replaces the bulk channel (C1) and the second channel (C2), so the machine runs the belt, then C3 and C4.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/variant-belt-feeder-links-w1600-4dee1e919f4b.jpg" alt="Printed belt links lying side by side on a bench, each with a raised catch across the width of the belt">
  <figcaption>The printed belt links. <cite>Photo: Marc.</cite></figcaption>
</figure>

**How it is built.** The belt is made of printed links that hinge on pins, in the style of modular plastic conveyor belts, and not of fabric, which is hard to buy. The links are 100 mm wide, and the catches are 70 mm apart and 4.2 mm high. The catches only have to hold a piece, not scoop it up, so their edges are chamfered on the back only and do not push pieces upwards. The belt climbs at no more than 45°, aiming for 35° to 40°, and then flattens out to carry pieces to the drop point. It runs on 608 bearings through a 4:1 gear reduction from a NEMA 17 motor, and slides on PTFE tube. It has no tensioner, because the weight of the belt keeps it taut. The pins are pieces of ABS filament: pins printed in PLA wore out.

**What was tested.** An endurance rig ran a 157 g weight on the belt at about 200 mm/s for 200 hours. Over that time an 11-link section stretched from 85.9 mm to 86.6 mm, measured at about 1.2 kg of pull. The belt survived. In a full machine the belt reached 2 to 4 parts a minute, held back by the belt slipping on its drive, so that figure says nothing about the layout itself. A standard machine has been reported at around 7 parts a minute.

**Where it stands.** It is still being worked on. The main drive shaft sheared when a piece jammed, and the drive and the frame were reworked since: a two-shaft drive was tried, and the new frame uses dovetails instead of most screws and no 2020 extrusion. The control software for it was not in the repository when last reported. The standard V2 is still the four-channel design.

A second builder runs a belt that feeds C3, and reports about 4 parts a minute with fewer double feeds, because the belt delivers pieces into C3 a few at a time.

<ul class="bulleted-list">
  <li>The endurance test: <a href="https://discord.com/channels/1430279849171222682/1527075509345845410">Conveyer longevity testing</a>, a thread in the Discord</li>
  <li>Where it was last discussed: the <a href="https://www.youtube.com/watch?v=8MJjpO3ikgU">6 September meeting</a></li>
  <li>The standard feeder this replaces: <a href="{{ '/hardware/assembly/feeder/c-channels/' | relative_url }}">C-channels</a></li>
  <li>Why the standard design has four channels: <a href="{{ '/lab/sorter/' | relative_url }}">How the sorter is put together</a></li>
</ul>

## Printed C1 legs instead of 2020 extrusion

**What is different.** The stand under the bulk channel (C1) normally stands on three legs cut from 2020 aluminium extrusion. The variant uses printed legs instead. A printed leg is the same part as the C2 and C3 legs, made longer: 228 mm tall, with the same 20 mm square ends that stand in the layout guide and take the dovetail adapter. The seat for the adapter ends up at the right height, so the drop to C2 is the same 80 mm as in the standard stand.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/variant-c1-printed-legs-full-f661caaf130c.png" alt="Three printed support legs standing side by side in order of height: the new 228 mm leg for C1, the 148 mm leg for C2 and the 68 mm leg for C3">
  <figcaption>The printed legs for C1, C2 and C3, drawn to the same scale. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

**What was tested.** The printed legs were tested by two builders, who each printed a set. Both report that the legs are stable. One found that, without any screws, they hold up better than the aluminium legs, and the other sees no reason to use extrusion instead. One of those machines was not running yet, so how the legs behave under vibration has not been reported.

**Why the standard stand uses extrusion.** The bulk channel carries a full bin of LEGO, and extrusion was chosen at C1 because printed legs wobbled under that load and took long to print. The standard stand therefore uses extrusion at C1, while C2 and C3 use printed legs. Whether the printed legs will replace the extrusion in the standard stand has not been announced.

The legs are not in the parts calculator. The file is an STL in the Discord thread linked below. If you pin a printed leg, it needs no T-nut: the M5 x 16 screw cuts its own thread in the plastic, as it does for the C2 and C3 legs.

<ul class="bulleted-list">
  <li>The file and a picture of the three legs side by side: <a href="https://discord.com/channels/1430279849171222682/1549077862039032019/1549079933240868884">the message in the Discord</a></li>
  <li>The standard stands, and how to pin one: <a href="{{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}">Arranging C-channels</a></li>
</ul>

## Orange Pi housing base without heat-set inserts

**What is different.** The standard base has eight holes that take heat-set inserts (small brass threaded sleeves pressed in with a hot tip): four under the Orange Pi, and four in the corner posts the roof screws into. In the variant all eight are smaller, 2.8 mm across instead of 4.0 mm, so the M3 screws cut their own thread straight into the plastic. That is the same size as the holes the roof already has for its own self-tapping screws. Nothing else changes, so it replaces the standard base.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/variant-orange-pi-base-direct-thread-full-f306c49a0b7f.png" alt="The Orange Pi housing base seen from above and one end, with four low posts for the board and four tall corner posts, each with a small hole">
  <figcaption>The variant base. The eight screw holes are the small ones in the posts. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

**Why it was made.** It is quite hard to insert the heat-set insert for the board's post near the corner of the housing, because there is very little space to work there. Leaving the inserts out removes that step.

**Screws.** The same M3 x 6 screws hold the Orange Pi, and the same M3 x 12 screws hold the roof. They bite less deeply than into an insert: after the circuit board only about 4.4 mm of an M3 x 6 screw is in the post. If that feels loose, an M3 x 8 screw still fits.

**Where it stands.** The file was made on 6 October 2026. One builder has printed it and reports that it works well. If 2.8 mm is too tight or too loose on your printer, the size can be adjusted.

<ul class="bulleted-list">
  <li>The file: <a href="https://discord.com/channels/1430279849171222682/1557096698160091167/1557097139304276048">the message in the Discord</a></li>
  <li>The standard base and where the inserts go: <a href="{{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}">Orange Pi housing</a></li>
  <li>Fitting inserts: <a href="{{ '/hardware/helpers/heat-inserts/' | relative_url }}">Heat inserts</a></li>
</ul>

## Single step feeder

**What is different.** It is meant to replace the feeder channels with a single step, a small platform that moves up and down on a linear rail and catches pieces out of a bulk pile. Its output wall is angled, so a single piece can be dropped more easily. It combines the hopper and the singulator (the part that separates pieces one by one) in one unit. The step is moved by a stepper motor with a toothed belt. The rail is used the other way round, with the platform held still and the rail moving, so the rail's stiffness steadies the platform. A V-shaped tray beside it can flip a piece onto a different side for more camera images before tipping it out, and a second servo can tilt the tray back above the hopper to return a double feed.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/variant-single-step-feeder-full-02f98a881f31.png" alt="A design drawing of the single step feeder: a hopper above a tilting tray, on a frame, with a camera arm over it">
  <figcaption>The single step feeder prototype. <cite>Rendered from the design, not from a build. Render: Marc.</cite></figcaption>
</figure>

**What was tested.** In software-controlled runs it dropped single pieces straight from a bulk pile. Small pieces work well, and an assembled wheel, with its awkward centre of gravity, struggled to go up. No speed has been measured. The tray that empties it did not work yet at the time.

**Where it stands.** It is an early experiment, and the hopper is smaller than a standard bulk bucket. It is not meant to replace the standard feeder yet.

<ul class="bulleted-list">
  <li>The first video: <a href="https://discord.com/channels/1430279849171222682/1547347895563591761/1549141900693471272">the message in the Discord</a></li>
  <li>The discussion of how it works and what it can do: <a href="https://discord.com/channels/1430279849171222682/1547347895563591761/1551312803716006041">the message in the Discord</a></li>
</ul>

## Inverted door flap

**What is different.** The flap on each layer's door is on the opposite side. It was changed because pieces dropped out of the wrong layers when the C-channel was not centred over the drop. Its designer found that it seemed to put less strain on the servo.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/variant-inverted-flap-chute-w1600-53bd044dbd6f.jpg" alt="A printed chute with the door flap on the inverted side, mounted on a turntable base on a desk">
  <figcaption>A chute with the inverted flap. <cite>Photo: Marc.</cite></figcaption>
</figure>

**What is known.** It is built on at least two machines. One builder moved to it on 8 September 2026 and printed new brackets at the same time for a different servo, the SC15, because the SC09 servos tended to bind up and overload. Another reported that the funnels they found for it are a few centimetres short of the bins, so pieces fall out through the gap. It is not in the parts calculator.

<ul class="bulleted-list">
  <li>The change and its reason: <a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1546967674339463250">the message in the Discord</a></li>
  <li>The servo swap: the <a href="https://www.youtube.com/watch?v=8MJjpO3ikgU">6 September meeting</a></li>
  <li>The standard door: <a href="{{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}">Door module</a></li>
</ul>

## A position encoder on the chute motor

**What is different.** A small magnetic position sensor (an AS5600 encoder) is fitted to the back of the chute's NEMA 23 motor. The control board reads it over I²C and so knows whether the chute is really turning. The standard machine instead relies on the driver's stall detection (see [The motors]({{ '/lab/motors/' | relative_url }})), which was not catching jams on that machine and needs tuning. The encoder needs no calibration. It fits under the sticker on the motor's rear shaft hole, with no drilling. A small converter board steps the 5 V down to the 3.3 V it needs.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/variant-as5600-encoder-holder-full-d93962455631.png" alt="A NEMA 23 stepper motor with a printed holder in pink on its rear end that carries the encoder">
  <figcaption>The holder that carries the encoder on the back of the motor. <cite>Rendered from the design, not from a build. Render: Marc.</cite></figcaption>
</figure>

**Where it stands.** It has been running since early September 2026, and its builder reported on 10 October that it is still on the machine and works well. It is only on the chute motor, because only there does the exact position matter.

<ul class="bulleted-list">
  <li>The first report: <a href="https://discord.com/channels/1430279849171222682/1430279852015091804/1545190395959578635">the message in the Discord</a>, and a later one: <a href="https://discord.com/channels/1430279849171222682/1558542800922869794/1558544434814255156">the message in the Discord</a></li>
  <li>The explanation in the <a href="https://www.youtube.com/watch?v=8MJjpO3ikgU">6 September meeting</a></li>
</ul>

## Printed layer frame pieces

**What is different.** Printed segments replace the three extrusion parts of each layer's frame: the crossbeam, the 90° bracket and the spoke. A full ring was put together on 4 August 2026. The builder found two small problems: a small gap between the segments, and a support that reaches slightly past the end of the bins, without touching the chute.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/variant-printed-layer-frame-w1600-7c60cce2cd40.jpg" alt="A ring of printed hexagonal-grid frame segments joined at blue corner pieces, with a black funnel segment, lying on a floor">
  <figcaption>A full ring of printed frame segments. <cite>Photo: zed0.</cite></figcaption>
</figure>

**What was found.** It does not yet win on printing time or weight. The benefit is that it needs no aluminium extrusion, and the segments could be trimmed to the areas that need them.

<ul class="bulleted-list">
  <li>The design, and the finished ring: <a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1533475881773830164">the first message</a> and <a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1534206842480361593">the build report</a></li>
  <li>The standard frame: <a href="{{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}">Hex frame</a></li>
</ul>

## One long extrusion per leg

**What is different.** The standard machine cuts each layer's legs as separate lengths of extrusion. In this variant the layers are built first, from the printed parts alone, and one full-length extrusion is then slid through them for each leg.

**What was found.** It works well, but it gives up the modularity of the standard way, where you can add layers one at a time later.

<ul class="bulleted-list">
  <li>The comparison: <a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1556720170037412026">the message in the Discord</a> and <a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1556722443178082498">the answer</a></li>
  <li>The standard stacking: <a href="{{ '/hardware/assembly/distribution/stacking-the-layers/' | relative_url }}">Stacking the layers</a></li>
</ul>
