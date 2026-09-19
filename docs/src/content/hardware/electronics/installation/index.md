---
layout: default
title: Installing the electronics
type: landing
section: hardware
slug: electronics-installation
kicker: Electronics — Installation
lede: Where the PSU, the control board and the Orange Pi mount on the machine. Build in this order.
permalink: /hardware/electronics/installation/
author: barthel
contributors: [spencer]
warning: >-
  One of these pages (PSU box) involves wiring mains voltage. Read it fully before starting, and do
  not plug a cable into the IEC inlet until that box is complete and its wiring verified.
---

The [wire harness]({{ '/hardware/electronics/' | relative_url }}) pages cover what connects to what. These cover the other half: where the hardware physically sits and what holds it there. "The control board" here means basically board v1.3, the basically Embedded Control Board; the three sections below call their own printed enclosure a housing, a box, and a mount, but they're the same kind of part, one per component, bolted to the frame.

## Bolting the enclosures to the frame

Each of the three printed enclosures bolts to the 2020 frame with 2 M5 screws into 2 {% include fastener.html size="M5" variant="t-nut" text="T-nuts" %}, 6 of each in total. The holes in all three are clearance, so the screw passes through the plastic and pulls down onto the nut. PSU box: 2x {% include fastener.html size="M5" variant="socket-button" length="12" %}. Orange Pi mount: 2x {% include fastener.html size="M5" variant="socket-button" length="12" %}. Control board housing: 2x {% include fastener.html size="M5" variant="socket-button" length="16" %}, longer because its clamp boss is 10 mm deep against the other two at 8 mm.

The six T-nuts go into the hex frame while the top interface is built, at [step 13]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}#step-13) of that page.

<div class="callout">
  <p><b>No problem if you forgot them.</b> The {% include fastener.html size="M5" variant="t-nut" text="T-nut" %} this build specifies is the spring-loaded roll-in kind, which drops into the slot anywhere along its length, so it can still go in now without taking the frame apart. See <a href="{{ '/hardware/helpers/t-nuts/' | relative_url }}">Fitting T-nuts</a>.</p>
</div>

All three go on the same plane: the [hex frame]({{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}) that belongs to the top interface, the one lowered onto the interface assembly at [step 13]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}#step-13) of the top interface build. The render below is that frame seen from above, and the chute stepper is the landmark to place the three enclosures against.

**All three are bolted on from here**, each once it is built and closed on its own page. None of the three pages ends with a bolting step of its own.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/electronics-component-layout-topdown-full-2d38b86c4b2e.jpg" alt="Top-down physical component layout on the machine, with the PSU, Pi, basically board, USB hub, Pico, chute stepper and ribbon run called out">
  <figcaption>Where everything sits, top-down. This render is the record of the placement; the chute stepper is drawn slightly further out than it really sits, to keep the callouts readable. <cite>Render: Spencer.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-on-the-extrusion-w1600-813fbb56a0d6.jpg" alt="The finished control board housing bolted down onto a 2020 aluminium extrusion under the machine's frame, with two socket head screws through its clamp bosses">
  <figcaption>The control board housing bolted on, its two clamp bosses pulled down onto the extrusion. The PSU box and the Orange Pi mount go on the same way. <cite>Photo: Spencer.</cite></figcaption>
</figure>

Solder the [Pico headers]({{ '/hardware/helpers/pico-headers/' | relative_url }}) first, a one-time prep step under [Helpers]({{ '/hardware/helpers/' | relative_url }}); the Pico won't seat in the control board without it. Then:

1. **[PSU box]({{ '/hardware/electronics/installation/psu-box/' | relative_url }})**: the printed enclosure around the Mean Well LRS-350-24.
2. **[Preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }})**: the five stepper drivers, the Pico, and the jumpers that address the drivers.
3. **[Control board housing]({{ '/hardware/electronics/installation/control-board-housing/' | relative_url }})**: the printed housing the board closes into, with its fan.
4. **[Orange Pi mount]({{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }})**: Orange Pi 5 on standoffs.

With all four bolted to the frame, [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}) plugs them together: every cable between them, and the socket each end goes into. The [wire harness]({{ '/hardware/electronics/' | relative_url }}) page is the reference for what those cables are made of. [Software setup]({{ '/hardware/software-setup/' | relative_url }}) comes after.

## What is not recorded yet

Collected here rather than left on the individual pages, because these are the things that block finishing them.

- **Cooling the Orange Pi.** The control board's fan is answered: it sits in the housing cover and runs off a GPIO-switched 24 V port on the board itself. The fan on the Pi's arm is a 24 V one too, and the Pi's heatsink fan runs off the Pi itself; where the arm fan's lead lands is still open (open item 1 on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page).
