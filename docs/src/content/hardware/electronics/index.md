---
layout: default
title: Electronics
type: landing
section: hardware
slug: electronics
kicker: Hardware — Electronics
lede: The power supply, the two boards and every cable between them. What the harness is made of, where each box mounts on the machine, and what plugs into what.
permalink: /hardware/electronics/
og_image: https://assets.basically.website/sorter-parts/ctrl-board-basically-full-f7caadca07d5.png
author: barthel
contributors: [spencer]
---

The machine's electronics are one 24 V supply, two boards and the cables between them. The supply is a Mean Well LRS-350-24 in a printed box; **basically board v1.3**, the basically Embedded Control Board, drives the steppers, the lamps and the limit switch; and an **Orange Pi 5** runs the software and the cameras. Each of the three has its own printed part bolted to the same frame: a box for the supply, a housing for the control board, and an open mount for the Pi.

<ol class="numbered-steps">
  <li><strong><a href="{{ '/hardware/electronics/wire-harness/' | relative_url }}">Wire harness</a></strong>. The reference: the supply's spec, the interconnect diagram, every cable with its ends, lengths and gauges, the stepper pinout, and what is still undecided. Read it to know what a cable is; you do not build anything from this page.</li>
  <li><strong><a href="{{ '/hardware/electronics/installation/' | relative_url }}">Installing the electronics</a></strong>. The build: the PSU box, the control board and its housing, the Orange Pi and its mount, and the step that bolts all three onto the hex frame. Five pages, in order.</li>
  <li><strong><a href="{{ '/hardware/electronics/connecting/' | relative_url }}">Connecting the components</a></strong>. Every cable plugged in, and the socket each end goes into. Assumes the boxes are on the frame and the cables exist.</li>
</ol>

**Where the cables themselves come from.** [Ordering the wire harness]({{ '/hardware/parts/harness-order/' | relative_url }}) is the same schedule as a buy-and-build list, one row per cable, so a supplier can quote it. Four of them are made by hand instead, each on its own page under [Helpers]({{ '/hardware/helpers/' | relative_url }}): the [PSU output pigtails]({{ '/hardware/helpers/psu-pigtail/' | relative_url }}), the [control board's 24 V lead]({{ '/hardware/helpers/board-24v-lead/' | relative_url }}), the [chute stepper lead]({{ '/hardware/helpers/chute-stepper-lead/' | relative_url }}) and the [prepared LED strips]({{ '/hardware/helpers/led-strip/' | relative_url }}).

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Two things on these pages involve mains voltage</b>, both inside the PSU box: the fused IEC inlet and the supply's own AC terminals. Read the <a href="{{ '/hardware/electronics/installation/psu-box/' | relative_url }}">PSU box</a> page fully before starting it, and do not plug a cable into the inlet until that box is complete and its wiring verified.</p>
</div>

The wiring is still being specced, so the harness page is working notes rather than finished documentation and says so at the top. [Software setup]({{ '/hardware/software-setup/' | relative_url }}) is what comes after all of this.
