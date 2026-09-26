---
layout: default
title: Installing the electronics
type: landing
section: hardware
slug: electronics-installation
kicker: Electronics — Installation
lede: The power supply, the control board and the Orange Pi, each built on the bench and bolted onto the same frame. Build in this order.
permalink: /hardware/electronics/installation/
author: barthel
contributors: [spencer]
og_image: https://assets.basically.website/sorter-docs/electronics-component-layout-topdown-full-2d38b86c4b2e.jpg
tools_needed: ["Hex key, 3 mm for a button head or 4 mm for a socket head"]
warning: >-
  One of these pages (PSU box) involves wiring mains voltage. Read it fully before starting, and do
  not plug a cable into the IEC inlet until that box is complete and its wiring verified.
---

The machine's electronics are the power supply, the control board, and the Orange Pi that runs the machine, each on its own printed part bolted to the same frame. All three are closed in: the supply in a box, the control board and the Orange Pi each in a housing. "The control board" here means basically board v1.3, the basically Embedded Control Board.

**These pages cover where the hardware sits and what holds it there.** What plugs into what is the other half, and that is [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), with the [wire harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) page behind it as the reference for the cables themselves.

The Pico is bought with its header pins already fitted, so there is nothing to prepare before this list. If yours is a bare one, [solder its headers on]({{ '/hardware/helpers/pico-headers/' | relative_url }}) first, a one-time step under [Helpers]({{ '/hardware/helpers/' | relative_url }}); it won't seat in the control board without them. Then:

<ol class="numbered-steps">
  <li><strong><a href="{{ '/hardware/electronics/installation/psu-box/' | relative_url }}">PSU box</a></strong>. The printed enclosure around the Mean Well LRS-350-24, its mains inlet, and the wiring inside it.</li>
  <li><strong><a href="{{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}">Preparing the control board</a></strong>. The five stepper drivers, the Pico, and the ten jumpers that address the drivers. Done with the board loose.</li>
  <li><strong><a href="{{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}">Control board housing</a></strong>. The prepared board closed into its printed housing, with the 40 mm fan and the reset plunger in the cover.</li>
  <li><strong><a href="{{ '/hardware/electronics/installation/orange-pi-prep/' | relative_url }}">Preparing the Orange Pi</a></strong>. The heatsink fan, the WiFi module and the first boot that sets the network, all while the board is still loose on the bench.</li>
  <li><strong><a href="{{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}">Orange Pi housing</a></strong>. The Orange Pi 5 closed into its printed housing, with the USB hub and the buck converter clamped to its roof.</li>
</ol>

**Every one of those pages finishes on the bench.** Bolting the enclosure to the frame is one step, the same on all three, and it is on this page.

## Bolting the enclosures to the frame

Each of the three printed enclosures bolts to the 2020 frame with 2 M5 screws into 2 {% include fastener.html size="M5" variant="t-nut" text="T-nuts" %}, 6 of each in total. The holes in all three are clearance, so the screw passes through the plastic and pulls down onto the nut.

- **Orange Pi housing**: 2x {% include fastener.html size="M5" variant="socket-button" length="16" %}, each with an M5 washer under its head
- **PSU box**: 2x {% include fastener.html size="M5" variant="socket-button" length="16" %}, each with an M5 washer under its head
- **Control board housing**: 2x {% include fastener.html size="M5" variant="socket-button" length="16" %}, each with an M5 washer under its head

All three take the same screw, because every clamp boss is 10 mm deep.

The six T-nuts go into the hex frame while the top interface is built, at [step 13]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}#step-13) of that page.

<div class="callout">
  <p><b>No problem if you forgot them.</b> The {% include fastener.html size="M5" variant="t-nut" text="T-nut" %} this build specifies is the spring-loaded roll-in kind, which drops into the slot anywhere along its length, so it can still go in now without taking the frame apart. See <a href="{{ '/hardware/helpers/t-nuts/' | relative_url }}">Fitting T-nuts</a>.</p>
</div>

All three go on the same plane: the [hex frame]({{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}) that belongs to the top interface, the one lowered onto the interface assembly at [step 13]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}#step-13) of the top interface build. The render below is that frame seen from above, and the chute stepper is the landmark to place the three enclosures against.

**All three are bolted on from here**, each once it is built and closed on its own page. None of the five pages ends with a bolting step of its own. [What one looks like done](#the-finished-result) is at the foot of this page.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/electronics-component-layout-topdown-full-2d38b86c4b2e.jpg" alt="Top-down physical component layout on the machine, with the PSU, Pi, basically board, USB hub, Pico, chute stepper and ribbon run called out">
  <figcaption>Where everything sits, top-down. This render is the record of the placement; the chute stepper is drawn slightly further out than it really sits, to keep the callouts readable. <cite>Render: Spencer.</cite></figcaption>
</figure>

## What is not recorded yet

Collected here rather than left on the individual pages, because these are the things that block finishing them.

- **The PSU box and the Orange Pi housing have never been photographed bolted on.** The control board housing has a picture of it on the frame in the row below; the other two have renders there rather than builds.

## The finished result

All three enclosures bolted onto the hex frame, each one once its own page has finished it on the bench.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-on-the-extrusion-w1600-813fbb56a0d6.jpg" alt="The finished control board housing bolted down onto a 2020 aluminium extrusion under the machine's frame, with two socket head screws through its clamp bosses">
    <figcaption><a href="{{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}">Control board housing</a>, its two clamp bosses pulled down onto the extrusion. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-parts/meanwell-psu-housing-v2-render-full-f4b161896ea6.png" alt="Render of the closed PSU box bolted onto a 2020 extrusion by the clamp bosses at each end, its vented rear lid on top and its front panel carrying the mains inlet and the three output jacks">
    <figcaption><a href="{{ '/hardware/electronics/installation/psu-box/' | relative_url }}">PSU box</a>, bolted on. <cite>Render, not photographed on a build yet.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-parts/orange-pi-housing-with-hub-render-full-7d14589d8944.png" alt="Render of the Orange Pi housing with the USB hub and the buck converter clamped to its roof and the two WiFi antennas standing in their clamp on its long wall">
    <figcaption><a href="{{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}">Orange Pi housing</a>, with the hub and the buck converter on its roof. <cite>Render, not photographed on a build yet.</cite></figcaption>
  </figure>
</div>

With the three enclosures bolted to the frame, [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}) plugs them together: every cable between them, and the socket each end goes into. [Software setup]({{ '/hardware/software-setup/' | relative_url }}) comes after.
