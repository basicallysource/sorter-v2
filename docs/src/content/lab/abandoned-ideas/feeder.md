---
layout: default
title: Feeder
type: explanation
section: lab
slug: lab-abandoned-feeder
kicker: Design and research — Abandoned ideas
lede: Turntables, vibration, step feeders, rotor shapes, lighting and camera posts, stands, and the ArUco tags: the feeder ideas that were dropped, and why.
permalink: /lab/variants/abandoned/feeder/
audience: curious builder or contributor
applies_to: hardware-v2
owner: docs
last_verified: 2026-10-11
---

Back to <a href="{{ '/lab/variants/abandoned/' | relative_url }}">Abandoned ideas</a>. Several of these came before the C-channels; the full write-up of those experiments, with the numbers, is on <a href="{{ '/lab/feeder-experiments/' | relative_url }}">Feeder experiments</a>. Each entry says what the idea was and why it went, as far as the reasons are written down. The status of each is as of 11 October 2026.

## A spiral labyrinth turntable

**What it was.** A spinning disc with spiral walls, meant to separate pieces over distance using the motion of the disc.

**Why it was dropped.** Clumps stayed clumped, and pieces mostly drifted outwards without touching the walls. Small prototypes gave misleadingly good results. A larger disc separated better but made the machine too wide, and stacking two discs let the pieces clump again.

## A flat rotating V-channel

**What it was.** A flat turning table that carried pieces in a line to a fixed exit.

**Why it was dropped.** It moves pieces but nothing agitates them, so it cannot separate them. It only works if the pieces arrive already separated.

## A vibrating V-channel

**What it was.** A V-shaped channel shaken on compression springs.

**Why it was dropped.** It separated pieces well, but it was loud. Rotating channels, where the drop from one channel to the next does the separating, replaced the vibration.

## A stair-step feeder

**What it was.** The first generation used one large stair-step bulk feeder. C1 replaced it. The idea has since been proposed again, in a smaller form, as a way to feed pieces one at a time.

**Why it was dropped.** The step size and angle have to be such that any piece will ride up the step. That works in a bulk bucket, where a piece lies almost flat on its side, but not for the full range of LEGO pieces (<a href="https://discord.com/channels/1430279849171222682/1457470938873331834/1460770147936501871">13 January 2026</a>).

<ul class="bulleted-list">
  <li>A single step feeder that is being tried: <a href="{{ '/lab/variants/' | relative_url }}">Tested variants</a></li>
</ul>

## Round rotors

**What it was.** A rotor with a round outline.

**Why it was dropped.** A round rotor touches a long piece at only one point, while the stator wall touches it at two, so large pieces do not move along. The facets of the faceted rotor turn that point into a line of contact (<a href="https://discord.com/channels/1430279849171222682/1460692585881534579/1475959145181216789">the original explanation</a>).

## More than four channels

**What it was.** A builder put five C-channels in series to see how evenly the pieces could be spread from the bulk channel to the last (<a href="https://discord.com/channels/1430279849171222682/1460692585881534579/1475427028772585595">23 February 2026</a>).

**Why it was dropped.** The separation levelled off after about three channels: pieces ended up queued rather than spread out. The standard machine has four, and no comparison of throughput between different numbers of channels exists.

## Light posts, the overhead camera mount and the classification dome

**What they were.** Each feeder channel had a vertical post with a lamp on its end, and the cameras hung on an overhead mount from two steel rods. The classification channel had a large white dome over it.

**Why they were dropped.** The camera lamp replaced all of them. It was designed to do away with soldering, to lock the camera position so that nothing needs adjusting, and to remove the big dome, so that the camera arm, lights and bracket are the same on all three channels (<a href="https://www.youtube.com/watch?v=fnBvE-yFbLc">30 August 2026 meeting</a>). These parts are marked as not used in the parts calculator, and old photos of them show a design that is no longer built.

<ul class="bulleted-list">
  <li>What replaced them: <a href="{{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}">Camera lamps</a></li>
</ul>

## Printed feet, legs and leg extensions

**What they were.** The first stands for the channels, built from a foot, a leg and up to two leg extensions stacked on each other.

**Why they were dropped.** They worked, but they were unstable. The layout guide, the support legs and the dovetail adapters replaced them. C1 now stands on 2020 extrusion legs, and C2 and C3 on single printed legs.

<ul class="bulleted-list">
  <li>The current stands: <a href="{{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}">Arranging C-channels</a></li>
</ul>
