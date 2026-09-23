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
og_image: https://assets.basically.website/sorter-docs/assembly-control-board-housing-on-the-extrusion-w1600-813fbb56a0d6.jpg
warning: >-
  One of these pages (PSU box) involves wiring mains voltage. Read it fully before starting, and do
  not plug a cable into the IEC inlet until that box is complete and its wiring verified.
---

The machine's electronics are three printed enclosures and the hardware that goes inside them: the power supply, the control board, and the Orange Pi that runs the machine. "The control board" here means basically board v1.3, the basically Embedded Control Board; the pages below call their enclosures a box, a housing and a mount, but they are the same kind of part, one per component.

**These pages cover where the hardware sits and what holds it there.** What plugs into what is the other half, and that is [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), with the [wire harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) page behind it as the reference for the cables themselves.

The Pico is bought with its header pins already fitted, so there is nothing to prepare before this list. If yours is a bare one, [solder its headers on]({{ '/hardware/helpers/pico-headers/' | relative_url }}) first, a one-time step under [Helpers]({{ '/hardware/helpers/' | relative_url }}); it won't seat in the control board without them. Then:

<ol class="numbered-steps">
  <li><strong><a href="{{ '/hardware/electronics/installation/psu-box/' | relative_url }}">PSU box</a></strong>. The printed enclosure around the Mean Well LRS-350-24, its mains inlet, and the wiring inside it.</li>
  <li><strong><a href="{{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}">Preparing the control board</a></strong>. The five stepper drivers, the Pico, and the ten jumpers that address the drivers. Done with the board loose.</li>
  <li><strong><a href="{{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}">Control board housing</a></strong>. The prepared board closed into its printed housing, with the 40 mm fan and the reset plunger in the cover.</li>
  <li><strong><a href="{{ '/hardware/electronics/installation/orange-pi-prep/' | relative_url }}">Preparing the Orange Pi</a></strong>. The heatsink fan, the WiFi module and the first boot that sets the network, all while the board is still loose on the bench.</li>
  <li><strong><a href="{{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}">Orange Pi mount</a></strong>. The Orange Pi 5 standing off its printed plate, with the 40 mm fan on the arm above it.</li>
</ol>

**Every one of those pages finishes on the bench.** Bolting the enclosure to the frame is one step, the same on all three, and it is on this page.

## Bolting the enclosures to the frame

Each of the three printed enclosures bolts to the 2020 frame with 2 M5 screws into 2 {% include fastener.html size="M5" variant="t-nut" text="T-nuts" %}, 6 of each in total. The holes in all three are clearance, so the screw passes through the plastic and pulls down onto the nut.

- **PSU box**: 2x {% include fastener.html size="M5" variant="socket-button" length="12" %}
- **Orange Pi mount**: 2x {% include fastener.html size="M5" variant="socket-button" length="12" %}
- **Control board housing**: 2x {% include fastener.html size="M5" variant="socket-button" length="16" %}, longer because its clamp boss is 10 mm deep against the other two at 8 mm

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

- **Cooling the Orange Pi.** The control board's fan is answered: it sits in the housing cover and runs off a GPIO-switched 24 V port on the board itself. The fan on the Pi's arm is a 24 V one too, and the Pi's heatsink fan runs off the Pi itself; where the arm fan's lead lands is still open (open item 1 on the [wire harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) page).
- **Nothing says how the USB hub attaches.** The render above is the only record of where it goes, and it records placement, not a method: there is no printed mount, no bracket and no fastener for it anywhere in the build. Its 24 V lead is `W2` on the [wire harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) page.
- **Two of the three enclosures have never been photographed bolted on.** The control board housing is the only one anybody has a picture of on the frame; the row below carries a described placeholder for the other two. The finished PSU box has no photo on the bench either, so its own page carries one as well.

## The finished result

All three enclosures bolted onto the hex frame, each one once its own page has finished it on the bench.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-on-the-extrusion-w1600-813fbb56a0d6.jpg" alt="The finished control board housing bolted down onto a 2020 aluminium extrusion under the machine's frame, with two socket head screws through its clamp bosses">
    <figcaption><a href="{{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}">Control board housing</a>, its two clamp bosses pulled down onto the extrusion. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
  <figure>
    <div class="img-placeholder">Image coming: the PSU box bolted onto the hex frame, both clamp bosses down on the extrusion, the inlet and the output jacks reachable</div>
    <figcaption><a href="{{ '/hardware/electronics/installation/psu-box/' | relative_url }}">PSU box</a>, bolted on. <cite>Not photographed on a build yet.</cite></figcaption>
  </figure>
  <figure>
    <div class="img-placeholder">Image coming: the Orange Pi mount bolted onto the hex frame, the Pi standing off the plate and the fan arm over it</div>
    <figcaption><a href="{{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}">Orange Pi mount</a>, bolted on. <cite>Not photographed on a build yet.</cite></figcaption>
  </figure>
</div>

With the three enclosures bolted to the frame, [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}) plugs them together: every cable between them, and the socket each end goes into. [Software setup]({{ '/hardware/software-setup/' | relative_url }}) comes after.
