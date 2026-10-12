---
layout: default
title: Classification
type: explanation
section: lab
slug: lab-abandoned-classification
kicker: Design and research — Abandoned ideas
lede: The carousel, imaging from several channels, embeddings and colour by machine learning: how the machine identifies a piece, and the earlier approaches that were dropped.
permalink: /lab/variants/abandoned/classification/
audience: curious builder or contributor
applies_to: hardware-v2
owner: docs
last_verified: 2026-10-11
---

Back to <a href="{{ '/lab/variants/abandoned/' | relative_url }}">Abandoned ideas</a>. How the machine identifies a piece, and the earlier ways of doing it that were dropped. Each entry says what the idea was and why it went, as far as the reasons are written down. The status of each is as of 11 October 2026.

## The carousel and the identification chamber

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

## Identifying a piece from images taken in several channels

**What it was.** The April 2026 plan was to follow each piece through the C-channels and send pictures from every stage to the identification service together.

**Why it was dropped.** It was built and then switched off. Only pictures from C4 are sent now, so that the identity the machine commits to is always a view of the piece after it has landed. Two reasons are written in the code. A test that gave priority to frames taken while the piece was falling failed: the frames were too blurred, and the service identified nothing in the test (a very small test, two runs). And the link that handed a piece from one channel's camera to the next was cut, because when pieces clump, a wrong hand-over merges two pieces into one query.

A piece that lies face down is therefore still seen from above only. That is an open problem, not a solved one.

## Embeddings for recognising pieces

**What it was.** The first approach to recognition compared a new picture with a database of stored picture fingerprints (embeddings, from a model called DINO V2) and took the closest.

**Why it was dropped.** One badly photographed example in the database could poison a whole class: a 1 x 2 brick photographed without its pin showing confused the model between the plain and the pinned brick. After about four weeks a regular classifier was found to do better once there are enough good, varied images of each part.

<ul class="bulleted-list">
  <li>The comparison: <a href="{{ '/lab/classification-research/' | relative_url }}">Classification research</a></li>
</ul>

## Reading colour with machine learning

**What it was.** Having a model decide the colour of a piece.

**Why it was dropped.** Lighting differs between machines and rooms, and machine-learning colour detection did not hold up across them. Colour is read by comparing the piece with a calibration card in the picture instead (<a href="{{ '/lab/classification-research/' | relative_url }}">Classification research</a>).
