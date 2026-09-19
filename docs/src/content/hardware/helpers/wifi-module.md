---
layout: default
title: Fitting the WiFi module
type: how-to
section: hardware
slug: helper-wifi-module
kicker: Helpers — WiFi module
lede: Seating the M.2 WiFi module in the Orange Pi 5, and why it goes in while the board is still loose on the bench.
permalink: /hardware/helpers/wifi-module/
last_verified: 2026-09-19
author: brickcyclealice
contributors: [spencer]
warning: >-
  The module seated in its slot is not photographed on a build yet. The procedure is the one from
  the [Orange Pi 5]({{ '/hardware/orange-pi-5/' | relative_url }}) page; only the sequencing is new.
parts_needed:
  - part: wifi-module-opi5
    qty: 1
tools_needed: [Small Phillips screwdriver]
---

The original Orange Pi 5 has no WiFi on the board. If the machine is not staying on Ethernet, it needs either a Linux-compatible USB adapter or the M.2 module in the parts list, and this page is about the M.2 one. It is an optional part: pick it on the [Orange Pi 5]({{ '/hardware/orange-pi-5/' | relative_url }}) page before buying, because the module that fits the original Orange Pi 5 does not fit a 5 Plus.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/wifi-module-opi5-full-8ab3a6417605.jpg" alt="The AP6275P M.2 WiFi module seen from above: a small blue card with a shielded can across the middle marked AP6275P, two round antenna sockets at the top corners, and a row of gold contacts along the bottom edge with a keying notch cut into it">
  <figcaption>The AP6275P, with its keying notch cut into the row of gold contacts along the bottom edge. <cite>Supplier listing photo from the parts catalog; who took it isn't recorded.</cite></figcaption>
</figure>

## Do this before the board goes on its mount

The M.2 slot is on the **underside** of the board, and so are the retention screw and the antenna leads. Fit the module at the same bench stage as the Pi's heatsink fan, in [Orange Pi mount]({{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}) step 1, while both faces of the board are still reachable. Once the Pi is standing off the mount there is a printed plate directly under it.

Fit it before the first boot as well. The WiFi section of the Sorter UI can only offer networks for an adapter that was present when the machine started, so a module fitted afterwards costs another shutdown and another boot.

{% include step.html n="1" title="Check the module matches the board" %}

The M.2 formats used across the Orange Pi family are the same size and differ only in where the keying notch is cut into the row of gold contacts, so a module only seats in the slot it is keyed for. Which module goes with which board, and how to tell the two slots apart by eye, is on the [Orange Pi 5]({{ '/hardware/orange-pi-5/#wifi' | relative_url }}) page.

Hold the module against the slot and check the notches line up before pushing. **If it does not want to go in, stop.** A module that will not seat is the wrong one for the board, not one that needs more force.

{% include step.html n="2" title="Seat it in the slot" %}

With the board unplugged, turn it over and find the M.2 slot on the underside.

Slide the module in at a shallow angle, roughly 30°, gold contacts first, until it is fully home. Press the free end down and secure it with the small retention screw.

**The washer goes between the board and the module**, under the free end, not on top of it. The slot holds the contact end of the module up off the board, so the washer is what keeps the other end at the same height. Without it the screw pulls that end down and the module ends up bent and unevenly tensioned rather than sitting flat.

Both the washer and the screw come in the box with the module, so there is nothing to buy for this and nothing to substitute.

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Connect the antennas" %}

The antenna leads end in small round push-fit connectors. Line one up squarely over its socket on the module and press straight down until it clicks. They seat with very little force and the sockets are delicate, so do not rock or lever them on at an angle.

{% include step.html n="4" title="Confirm the OS sees it" %}

Nothing else is needed to install it: the driver is in the official Orange Pi Ubuntu image that SorterOS is built on, so a SorterOS machine picks the module up on its own. Third-party OS images may not have the driver at all.

After the machine has booted, the adapter shows up in the Sorter UI under **Settings → WiFi**, which is where the network and password go in. Over SSH, `nmcli device wifi list` lists what it can see.

## On the bench for first setup

The network is set on a running machine, so a board that is going on WiFi does its first boot on its own, off the machine: the USB-C supply in the socket marked `PWR IN`, Ethernet to a router for that boot alone, and the antennas on. [Install SorterOS]({{ '/sorter/installation/sorter-os/' | relative_url }}) covers flashing the card and where the UI is.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/wifi-module-bench-first-boot-w1600-c538b35694b3.jpg" alt="An Orange Pi 5 standing off its printed extrusion mount with the fan arm above it, powered up on a desk with the red LED lit, a USB-C lead in the power socket and two antenna leads running off the module fitted underneath">
    <figcaption>Powered on the bench, red LED lit, with the antenna leads coming off the module underneath the board. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/wifi-module-bench-top-w1600-cc4b7edb44fd.jpg" alt="The same board from above, the 40 mm fan on its arm covering most of the board, with a blue Ethernet cable and the USB-C power lead plugged in along the top edge and the two antennas lying beside it">
    <figcaption>The same board from above, Ethernet in for the first boot. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

Neither photo has the Pi's own heatsink fan on the chip. That is fitted in [Orange Pi mount]({{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}) step 1 and this board is running without it on a desk, not a reason to leave it off.

The board is now ready to go on its mount: carry on with [Orange Pi mount]({{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}).
