---
layout: default
title: Design and research
type: landing
section: lab
slug: lab
kicker: Design, Research & Contributor References
lede: This section holds how the machine is designed and why, the durable findings from hands-on research, and the contributor references the rest of the project builds on.
permalink: /lab/
---

<div class="notice">
  <strong>You do not need to read this section to build a sorter</strong>
  <p>This section is optional background. These pages give more detail about how the sorter works and why it is designed the way it is, and keep the research behind it. The build instructions in <a href="{{ '/hardware/' | relative_url }}">Hardware</a> do not depend on them. Read them if you are curious, want to repair or change something, or want to know what was tried before.</p>
</div>

## How the machine is designed

The design pages give the overall picture in a few lines, then link to the files that hold the detail. Links to the relevant parts are provided on every page, for people who want to dig deeper: the source code, the parts catalog, and the matching build pages and the other pages in this section. You can ignore them if you only want the overview. Where a page says that we are still finding out why something was decided, the reason was not written down and we are asking around. We will add it when we have it. Some of the pages use electronics and software words that you may not know. Where a word first appears, it is explained in the same sentence.

<div class="callout-grid">
  <div class="callout">
    <strong><a href="{{ '/lab/sorter/' | relative_url }}">How the sorter is put together</a></strong>
    <p>The feeder and the distribution system, what each part does, and the alternatives that were tried before the current design.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/printed-parts/' | relative_url }}">Design intentions for the printed parts</a></strong>
    <p>What the printed parts are designed to do, the thinking behind how they fit together and are printed, and which screws and other hardware they use.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/contribute/' | relative_url }}">How to contribute</a></strong>
    <p>Where the project lives, how to help, when the team meets each week, and what Balloon, the assistant in the Discord, can do for you.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/electronics/' | relative_url }}">How the electronics talk to each other</a></strong>
    <p>How the Orange Pi and the Pico on the control board communicate: the cable, the messages, and where each part lives in the firmware.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/orange-pi/' | relative_url }}">What is connected to the Orange Pi</a></strong>
    <p>Everything the Orange Pi talks to, and what the software does with each.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/pico/' | relative_url }}">What is connected to the Pico</a></strong>
    <p>Everything the Pico on the control board is connected to, with a pin diagram and a table of what each pin does.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/usb/' | relative_url }}">The USB connections and the hub</a></strong>
    <p>The USB hub, what hangs on it, and how the software finds each device.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/motors/' | relative_url }}">The motors</a></strong>
    <p>The five stepper motors, what each one turns, how their drivers are set up, and how the machine notices a blocked motor.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/servos/' | relative_url }}">The servos and the layer adapter boards</a></strong>
    <p>How the chute doors are moved: the servo chip, the ribbon cable down the stack, and what each layer's adapter board does.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/power/' | relative_url }}">Power distribution</a></strong>
    <p>How power gets from the supply to every board and motor, with the ratings of the cables, connectors and devices.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/variants/' | relative_url }}">Tested variants</a></strong>
    <p>Alternatives to the standard design that people have built or are trying, such as a belt feeder, printed C1 legs and an Orange Pi base without heat-set inserts.</p>
  </div>
</div>

## Research areas

<div class="callout-grid">
  <div class="callout">
    <strong><a href="{{ '/lab/object-detection/' | relative_url }}">Object detection research</a></strong>
    <p>Which detector runtimes we validated, where the canonical artifacts live, the cross-device benchmark workflow, and the Raspberry Pi 5 Hailo HEF compile path.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/c-channel-singulation/' | relative_url }}">C-channel singulation</a></strong>
    <p>How the sorter separates tangled LEGO into single pieces using rotating C-shaped channels — a novel approach with no known published precedent.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/classification-research/' | relative_url }}">Classification research</a></strong>
    <p>Embeddings vs classifiers, the Brickognize API, training data strategy, and why color detection avoids ML entirely.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/feeder-experiments/' | relative_url }}">Feeder experiments</a></strong>
    <p>Turntable, vibration, and chute experiments that preceded the C-channel design — what was tested, what failed, and what the data showed.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/software-architecture-decisions/' | relative_url }}">Software architecture decisions</a></strong>
    <p>Why the project uses a dumb-firmware / smart-host split, what alternatives were evaluated, and the design principles behind the stack.</p>
  </div>
  <div class="callout">
    <strong><a href="https://github.com/basicallysource/sorter-v2/tree/main/software/sorter-design-system">Design system</a></strong>
    <p>How the SorterOS UI, Hive, and this documentation site look and are built: the rules, and the components to copy. A contributor reference, run from the repository.</p>
  </div>
</div>

## What belongs in this section

This section sits one level below the end-user-facing sections. Content lands here when:

<ul class="bulleted-list">
  <li>it's a <strong>contributor reference</strong> the rest of the project builds on but that an operator would never need to read (the software architecture decisions);</li>
  <li>it <strong>explains how the machine is designed</strong>, as an overview, for someone who is curious about it and not building from it (the design pages above);</li>
  <li>it records a <strong>variant</strong> that somebody has built or is trying, and that is not part of the standard build (the tested variants page);</li>
  <li>it's an <strong>active research thread</strong> where we're still validating conclusions, and the findings aren't ready to be promoted into a stable hardware or SorterOS docs page (the object detection work).</li>
</ul>

Once a finding stabilizes enough to be promoted — for example, when we settle on a single accelerated deployment path and it belongs in the SorterOS setup docs — it graduates out of this section into the appropriate top-level section.

## Artifact policy

The durable rule across all the research here:

<ol class="numbered-steps">
  <li>Keep decisions and workflows in checked-in Markdown on these pages.</li>
  <li>Keep only the latest canonical benchmark and compile artifacts under <code>software/sorter/backend/blob/</code>.</li>
  <li>Regenerate reports from benchmark JSONs instead of treating every HTML file as permanent.</li>
  <li>Promote a finding out of this section only after it has both a quality comparison against a reference and a sustained-throughput measurement.</li>
</ol>
