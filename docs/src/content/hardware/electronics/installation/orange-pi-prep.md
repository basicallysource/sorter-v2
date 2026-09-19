---
layout: default
title: Preparing the Orange Pi
type: how-to
section: hardware
slug: electronics-orange-pi-prep
kicker: Electronics — Preparing the Orange Pi
lede: The heatsink fan, the WiFi module, and the first boot that sets the network, all done while the board is still loose on the bench.
permalink: /hardware/electronics/installation/orange-pi-prep/
og_image: https://assets.basically.website/sorter-docs/wifi-module-bench-first-boot-w1600-c538b35694b3.jpg
last_verified: 2026-09-19
author: barthel
contributors: [brickcyclealice, spencer]
warning: >-
  The WiFi module seated in its slot is not photographed on a build yet.
parts_needed:
  - part: sbc-orange-pi-5
    qty: 1
  - part: fan-orange-pi-5-heatsink
    qty: 1
  - part: wifi-module-opi5
    qty: 1
tools_needed: [Small Phillips screwdriver]
---

Everything here is done to the board itself, before it goes anywhere near the machine, and that is the point of the page: the heatsink fan clips through the board and the WiFi module lives on its underside, so both want a board you can pick up and turn over. Once the Pi is standing off the [Orange Pi mount]({{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}) there is a printed plate directly underneath it.

Which board to buy, how much memory and storage it needs, and which WiFi module fits which variant are all on the [Orange Pi 5]({{ '/hardware/orange-pi-5/' | relative_url }}) page. This page assumes you have the parts.

**The WiFi module is optional.** A machine staying on Ethernet does not need it, and steps 2 to 5 are then only the first boot. The original Orange Pi 5 has no WiFi on the board, so a machine going wireless needs either this M.2 module or a Linux-compatible USB adapter.

{% include step.html n="1" title="Fit the heatsink fan" %}

Its two pins clip underneath the board, so you want to be able to reach both faces.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Orange Pi 5:</strong> the official heatsink fan sits on the SoC, the large chip in the middle of the board. Check the revision printed on the board before you start: it fits the Orange Pi 5 v1.3.2 and the 5 Plus, and the mounting holes are not in the same place on earlier revisions.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/orange-pi-5-heatsink-fan-fitted-full-6f0bb3b7ada4.jpg" alt="An Orange Pi 5 v1.3.2 seen from above with the heatsink fan already fitted over the SoC in the middle of the board, a white spring pin clipped through the board at opposite corners of the finned block, and the red and black lead running from the fan to a small white 2-pin socket silkscreened FAN, between the CAM1 connector and the USB 2.0 port">
    <figcaption>An Orange Pi 5 v1.3.2 with the fan fitted: the heatsink over the SoC, a spring pin through the board at each of two opposite corners, and the lead in the socket marked FAN. <cite>Manufacturer photo (Orange Pi), not a Basically photo; the pale highlights are theirs.</cite></figcaption>
  </figure>
</div>

Peel the film off the thermal pad that comes in the box and lay it on the SoC. Sit the heatsink squarely on top with its two tabs over the holes either side, press both spring pins down until they click, and plug the 2-pin lead into the socket marked FAN, which on a v1.3.2 board is between the CAM1 connector and the USB 2.0 port. The pins hold it on, so there are no screws here and nothing to tighten.

This is a second fan, not a replacement for the 40 mm one that ends up on the mount's arm: the heatsink fan sits on the chip, and the arm fan blows down over the whole board from above.

{% include step.html n="2" title="Check the WiFi module matches the board" %}

The M.2 formats used across the Orange Pi family are the same size and differ only in where the keying notch is cut into the row of gold contacts, so a module only seats in the slot it is keyed for. Which module goes with which board, and how to tell the two slots apart by eye, is on the [Orange Pi 5]({{ '/hardware/orange-pi-5/#wifi' | relative_url }}) page.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/wifi-module-opi5-full-8ab3a6417605.jpg" alt="The AP6275P M.2 WiFi module seen from above: a small blue card with a shielded can across the middle marked AP6275P, two round antenna sockets at the top corners, and a row of gold contacts along the bottom edge with a keying notch cut into it">
  <figcaption>The AP6275P, with its keying notch cut into the row of gold contacts along the bottom edge. <cite>Supplier listing photo from the parts catalog; who took it isn't recorded.</cite></figcaption>
</figure>

Hold the module against the slot and check the notches line up before pushing. **If it does not want to go in, stop.** A module that will not seat is the wrong one for the board, not one that needs more force.

{% include step.html n="3" title="Seat the module in the slot" %}

With the board unplugged, turn it over and find the M.2 slot on the underside.

Slide the module in at a shallow angle, roughly 30°, gold contacts first, until it is fully home. Press the free end down and secure it with the small retention screw.

**The washer goes between the board and the module**, under the free end, not on top of it. The slot holds the contact end of the module up off the board, so the washer is what keeps the other end at the same height. Without it the screw pulls that end down and the module ends up bent and unevenly tensioned rather than sitting flat.

Both the washer and the screw come in the box with the module, so there is nothing to buy for this and nothing to substitute.

<div class="img-placeholder">Image coming</div>

{% include step.html n="4" title="Connect the antennas" %}

The antenna leads end in small round push-fit connectors. Line one up squarely over its socket on the module and press straight down until it clicks. They seat with very little force and the sockets are delicate, so do not rock or lever them on at an angle.

{% include step.html n="5" title="First boot, and the network" %}

The network is set on a running machine, so the board does its first boot here, on the bench, before it is on anything: the USB-C supply in the socket marked `PWR IN`, Ethernet to a router for that boot alone, and the antennas on. [Install SorterOS]({{ '/sorter/installation/sorter-os/' | relative_url }}) covers flashing the card, how long first boot takes and where the UI is.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/wifi-module-bench-top-w1600-cc4b7edb44fd.jpg" alt="An Orange Pi 5 from above on a desk, the 40 mm fan on its arm covering most of the board, with a blue Ethernet cable and the USB-C power lead plugged in along the top edge and the two antennas lying beside it">
  <figcaption>Booting on the bench with Ethernet in. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

Nothing needs installing for the module itself: the driver is in the official Orange Pi Ubuntu image that SorterOS is built on, so a SorterOS machine picks it up on its own. Third-party OS images may not have the driver at all.

Once the UI is up, the adapter shows under **Settings → WiFi**, which is where the network and password go in. Over SSH, `nmcli device wifi list` lists what it can see.

**Take the adapter's address before you unplug the Ethernet.** Joining a network gets the machine a second address, different from the one it has been answering on, and once connected the adapter's row on that same WiFi page shows what it is. Write it down, then pull the Ethernet and browse to it. Doing it the other way round leaves you hunting for the machine, because the page you were reading goes with the cable.

{% include step.html n="6" title="Shut it down before it moves" %}

**Never cut the power to a running board.** It writes files continuously, and pulling the plug mid-write can corrupt the card you just flashed.

Press the small black button on the side of the Orange Pi once and leave it alone. Shutdown takes about a minute and a half, and it has finished when the red and green LEDs stop blinking. Only then unplug it. The button is a shutdown button, not a power switch: the board starts again the moment it has power, with no press needed.

[Shutting down the machine]({{ '/sorter/safe-shutdown/' | relative_url }}) covers the same from the UI, which is the route once the board is in the machine and the button is harder to reach.

## The finished result

A board that has been prepared: fan on, module in, network set, powered down and ready to bolt down.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/wifi-module-bench-first-boot-w1600-c538b35694b3.jpg" alt="An Orange Pi 5 standing off its printed extrusion mount with the fan arm above it, powered up on a desk with the red LED lit, a USB-C lead in the power socket and two antenna leads running off the module fitted underneath">
  <figcaption>Prepared and on the network, still on the bench. This board is running without the heatsink fan from step 1, which is not a reason to leave it off. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

Carry on with [Orange Pi mount]({{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}), which bolts it to the frame.
