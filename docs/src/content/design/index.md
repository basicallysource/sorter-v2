---
layout: default
title: Design
type: landing
section: design
slug: design
kicker: How It Works
lede: A bird's-eye view of how the machine is designed: what talks to what, and where to read the details.
permalink: /design/
last_verified: 2026-10-10
---

<div class="notice">
  <strong>You do not need to read this section to build a sorter</strong>
  <p>These pages give more detail about how the sorter works and why it is designed the way it is. The build instructions in <a href="{{ '/hardware/' | relative_url }}">Hardware</a> do not depend on them. Read them if you are curious, want to repair or change something, or want to know what was tried before.</p>
</div>

Each page gives the overall picture in a few lines, then links to the files that hold the detail. Some of the pages use electronics and software words that you may not know. Where a word first appears, it is explained in the same sentence.

## Pages

<div class="callout-grid">
  <div class="callout">
    <strong><a href="{{ '/design/sorter/' | relative_url }}">How the sorter is put together</a></strong>
    <p>The feeder and the distribution system, what each part does, and the alternatives that were tried before the current design.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/design/printed-parts/' | relative_url }}">Design intentions for the printed parts</a></strong>
    <p>What the printed parts are designed to do, and the thinking behind how they fit together and are printed.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/design/electronics/' | relative_url }}">How the electronics talk to each other</a></strong>
    <p>How the Orange Pi and the Pico on the control board communicate, which Pico pins drive the steppers, lamps, servos and switches, and where each of those lives in the firmware.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/design/orange-pi/' | relative_url }}">What is connected to the Orange Pi</a></strong>
    <p>Everything the Orange Pi talks to, and what the software does with each.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/design/usb/' | relative_url }}">The USB connections and the hub</a></strong>
    <p>The USB hub, what hangs on it, and how the software finds each device.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/design/power/' | relative_url }}">Power distribution</a></strong>
    <p>How power gets from the supply to every board and motor, with the ratings of the cables, connectors and devices.</p>
  </div>
</div>

For why the software is split between a simple firmware and a smart host, see [Software architecture decisions]({{ '/lab/software-architecture-decisions/' | relative_url }}).
