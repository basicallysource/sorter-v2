---
layout: default
title: Design
type: landing
section: design
slug: design
kicker: How It Works
lede: A bird's-eye view of how the machine is designed. What talks to what, and where in the repository to read the details.
permalink: /design/
last_verified: 2026-10-10
---

These pages explain the design from a distance. Each one gives the overall picture in a few lines, then links to the files that hold the detail. They do not repeat the build instructions: to build something, use [Hardware]({{ '/hardware/' | relative_url }}).

## Pages

<div class="callout-grid">
  <div class="callout">
    <strong><a href="{{ '/design/electronics/' | relative_url }}">How the electronics talk to each other</a></strong>
    <p>How the Orange Pi and the Pico on the control board communicate, which Pico pins drive the steppers, lamps, servos and switches, and where each of those lives in the firmware.</p>
  </div>
</div>

For why the software is split between a simple firmware and a smart host, see [Software architecture decisions]({{ '/lab/software-architecture-decisions/' | relative_url }}).
