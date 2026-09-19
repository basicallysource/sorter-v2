---
layout: default
title: Installing the electronics
type: landing
section: hardware
slug: electronics-installation
kicker: Electronics — Installation
lede: The power supply, the control board and the Orange Pi, each built on the bench, closed into its own printed enclosure and bolted onto the same frame. Build in this order.
permalink: /hardware/electronics/installation/
author: barthel
contributors: [spencer]
og_image: https://assets.basically.website/sorter-docs/electronics-component-layout-topdown-full-2d38b86c4b2e.jpg
warning: >-
  One of these pages (PSU box) involves wiring mains voltage. Read it fully before starting, and do
  not plug a cable into the IEC inlet until that box is complete and its wiring verified.
---

The machine's electronics are three printed enclosures and the hardware that goes inside them: the power supply, the control board, and the Orange Pi that runs the machine. "The control board" here means basically board v1.3, the basically Embedded Control Board; the pages below call their enclosures a box, a housing and a mount, but they are the same kind of part, one per component.

**These pages cover where the hardware sits and what holds it there.** What plugs into what is the other half, and that is [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), with the [wire harness]({{ '/hardware/electronics/' | relative_url }}) pages behind it as the reference for the cables themselves.

Solder the [Pico headers]({{ '/hardware/helpers/pico-headers/' | relative_url }}) first, a one-time prep step under [Helpers]({{ '/hardware/helpers/' | relative_url }}); the Pico won't seat in the control board without it. Then:

<ol class="numbered-steps">
  <li><strong><a href="{{ '/hardware/electronics/installation/psu-box/' | relative_url }}">PSU box</a></strong>. The printed enclosure around the Mean Well LRS-350-24, its mains inlet, and the wiring inside it.</li>
  <li><strong><a href="{{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}">Preparing the control board</a></strong>. The five stepper drivers, the Pico, and the ten jumpers that address the drivers. Done with the board loose.</li>
  <li><strong><a href="{{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}">Control board housing</a></strong>. The prepared board closed into its printed housing, with the 40 mm fan and the reset plunger in the cover.</li>
  <li><strong><a href="{{ '/hardware/electronics/installation/orange-pi-prep/' | relative_url }}">Preparing the Orange Pi</a></strong>. The heatsink fan, the WiFi module and the first boot that sets the network, all while the board is still loose on the bench.</li>
  <li><strong><a href="{{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}">Orange Pi mount</a></strong>. The Orange Pi 5 standing off its printed plate, with the 40 mm fan on the arm above it.</li>
</ol>

**Every one of those pages finishes on the bench.** Bolting the enclosure to the frame is one step, the same on all three, and it is on this page.

## Bolting the enclosures to the frame

Each of the three printed enclosures bolts to the 2020 frame with 2 M5 screws into 2 {% include fastener.html size="M5" variant="t-nut" text="T-nuts" %}, 6 of each in total. The holes in all three are clearance, so the screw passes through the plastic and pulls down onto the nut. PSU box: 2x {% include fastener.html size="M5" variant="socket-button" length="12" %}. Orange Pi mount: 2x {% include fastener.html size="M5" variant="socket-button" length="12" %}. Control board housing: 2x {% include fastener.html size="M5" variant="socket-button" length="16" %}, longer because its clamp boss is 10 mm deep against the other two at 8 mm.

The six T-nuts go into the hex frame while the top interface is built, at [step 13]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}#step-13) of that page.

<div class="callout">
  <p><b>No problem if you forgot them.</b> The {% include fastener.html size="M5" variant="t-nut" text="T-nut" %} this build specifies is the spring-loaded roll-in kind, which drops into the slot anywhere along its length, so it can still go in now without taking the frame apart. See <a href="{{ '/hardware/helpers/t-nuts/' | relative_url }}">Fitting T-nuts</a>.</p>
</div>

All three go on the same plane: the [hex frame]({{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}) that belongs to the top interface, the one lowered onto the interface assembly at [step 13]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}#step-13) of the top interface build. The render below is that frame seen from above, and the chute stepper is the landmark to place the three enclosures against.

**All three are bolted on from here**, each once it is built and closed on its own page. None of the five pages ends with a bolting step of its own.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/electronics-component-layout-topdown-full-2d38b86c4b2e.jpg" alt="Top-down physical component layout on the machine, with the PSU, Pi, basically board, USB hub, Pico, chute stepper and ribbon run called out">
  <figcaption>Where everything sits, top-down. This render is the record of the placement; the chute stepper is drawn slightly further out than it really sits, to keep the callouts readable. <cite>Render: Spencer.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-on-the-extrusion-w1600-813fbb56a0d6.jpg" alt="The finished control board housing bolted down onto a 2020 aluminium extrusion under the machine's frame, with two socket head screws through its clamp bosses">
  <figcaption>The control board housing bolted on, its two clamp bosses pulled down onto the extrusion. The PSU box and the Orange Pi mount go on the same way. <cite>Photo: Spencer.</cite></figcaption>
</figure>

## What is not recorded yet

Collected here rather than left on the individual pages, because these are the things that block finishing them.

- **Cooling the Orange Pi.** The control board's fan is answered: it sits in the housing cover and runs off a GPIO-switched 24 V port on the board itself. The fan on the Pi's arm is a 24 V one too, and the Pi's heatsink fan runs off the Pi itself; where the arm fan's lead lands is still open (open item 1 on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page).
- **The finished PSU box has never been photographed.** Its page and the row below both carry a described placeholder instead.

## The finished result

Each page ends in one of these.

<div class="img-row">
  <figure>
    <div class="img-placeholder">Image coming: the supply on the bench, both plates on, the inlet and the three jacks in the connections plate, cap off</div>
    <figcaption><a href="{{ '/hardware/electronics/installation/psu-box/' | relative_url }}">PSU box</a>. <cite>Not photographed on a build yet.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-prep-all-jumpers-fitted-w1600-f470f24a8913.jpg" alt="Top-down view of the fully populated control board, with five TMC2209 drivers, the Raspberry Pi Pico, and ten yellow jumpers fitted across the MS1 and MS2 headers">
    <figcaption><a href="{{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}">Preparing the control board</a>, jumpers fitted. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-housing-angled-w1600-d8c3ed33682d.jpg" alt="The finished housing at an angle, showing the honeycomb vent and basically logo on the lid, the plunger standing proud of the surface, and the slots along the right edge that expose the stepper connectors">
    <figcaption><a href="{{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}">Control board housing</a>, closed. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/wifi-module-bench-first-boot-w1600-c538b35694b3.jpg" alt="An Orange Pi 5 standing off its printed extrusion mount with the fan arm above it, powered up on a desk with the red LED lit, a USB-C lead in the power socket and two antenna leads running off the module fitted underneath">
    <figcaption><a href="{{ '/hardware/electronics/installation/orange-pi-prep/' | relative_url }}">Preparing the Orange Pi</a>, on the network. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/opi-mount-assembled-w1600-d65b122c4efc.jpg" alt="The finished mount on the bench: the Orange Pi standing on its standoffs over the plate, the printed fan arm bolted to the front edge and reaching back over the board, a 40 mm fan screwed to the top of the arm with its lead down through the slot">
    <figcaption><a href="{{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}">Orange Pi mount</a>, assembled. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

With the three enclosures bolted to the frame, [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}) plugs them together: every cable between them, and the socket each end goes into. [Software setup]({{ '/hardware/assembly/software-setup/' | relative_url }}) comes after.
