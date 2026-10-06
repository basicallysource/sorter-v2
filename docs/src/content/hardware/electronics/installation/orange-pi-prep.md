---
layout: default
title: Preparing the Orange Pi
type: how-to
section: hardware
slug: electronics-orange-pi-prep
kicker: Electronics — Preparing the Orange Pi
lede: The WiFi module and the heatsink fan, both fitted while the board is still loose on the bench.
permalink: /hardware/electronics/installation/orange-pi-prep/
og_image: https://assets.basically.website/sorter-docs/orange-pi-5-heatsink-fan-fitted-bench-full-de5a6f92b341.jpg
last_verified: 2026-10-06
author: barthel
contributors: [brickcyclealice, reveryx, spencer]
parts_needed:
  - part: sbc-orange-pi-5
    qty: 1
  - part: fan-orange-pi-5-heatsink
    qty: 1
  - part: wifi-module-opi5
    qty: 1
tools_needed: [Small Phillips screwdriver]
---

Everything here is done to the board itself, before it goes anywhere near the machine, and that is the point of the page: the WiFi module lives on its underside and the heatsink fan clips through the board, so both want a board you can pick up and turn over. Once the Pi is in the [Orange Pi housing]({{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}) there is a printed floor directly underneath it.

Which board to buy, how much memory and storage it needs, and which WiFi module fits which variant are all on the [Orange Pi 5]({{ '/hardware/orange-pi-5/' | relative_url }}) page. This page assumes you have the parts.

**The WiFi module is optional.** A machine staying on Ethernet does not need it, and steps 1 and 2 are skipped, leaving only the heatsink fan. The original Orange Pi 5 has no WiFi on the board, so a machine going wireless needs either this M.2 module or a Linux-compatible USB adapter.

{% include step.html n="1" title="Check the WiFi module (optional) matches the board" %}

The M.2 formats used across the Orange Pi family are the same size and differ only in where the keying notch is cut into the row of gold contacts, so a module only seats in the slot it is keyed for. Which module goes with which board, and how to tell the two slots apart by eye, is on the [Orange Pi 5]({{ '/hardware/orange-pi-5/#wifi' | relative_url }}) page.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/wifi-module-opi5-full-8ab3a6417605.jpg" alt="The AP6275P M.2 WiFi module seen from above: a small blue card with a shielded can across the middle marked AP6275P, two round antenna sockets at the top corners, and a row of gold contacts along the bottom edge with a keying notch cut into it">
  <figcaption>The AP6275P, with its keying notch cut into the row of gold contacts along the bottom edge. <cite>Supplier listing photo from the parts catalog; who took it isn't recorded.</cite></figcaption>
</figure>

Hold the module against the slot and check the notches line up before pushing. **If it does not want to go in, stop.** A module that will not seat is the wrong one for the board, not one that needs more force.

When buying, check the position of the notch: the green modules have two notches at different positions, and they do not fit.

The two antennas are already connected to the module when it arrives. If they are not, attach them now, before the module is mounted, which is easier than doing it afterwards. Line one up squarely over its socket on the module and press straight down until it clicks. They seat with very little force and the sockets are delicate, so do not rock or lever them on at an angle.

{% include step.html n="2" title="Seat the module (optional) in the slot" %}

With the board unplugged, turn it over and find the M.2 slot on the underside.

Slide the module in at a shallow angle, roughly 30°, gold contacts first, until the contacts are home and the far end is still raised. The free end is held down by a screw, a plastic washer and a nut, which are the three loose parts in the photo below.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/orange-pi-5-wifi-module-screw-washer-nut-full-593bcc1ed0ac.jpg" alt="The underside of an Orange Pi 5 with the AP6275P module seated in the M.2 slot and its two antenna leads clipped on, a round hole through the module's free end, and below the board three loose parts in a row: a black dome nut, a black plastic washer and a short black screw">
  <figcaption>The module in its slot, and the three loose parts below: the nut, the plastic washer and the screw. The antennas are already clipped on. <cite>Photo: ReveryX.</cite></figcaption>
</figure>

**The screw goes in from the other side of the board.** Push it through the hole from the top face, the one with the SoC, so its thread comes out on the module side. Then:

<ol class="numbered-steps">
  <li>Put the plastic washer on the screw, <strong>between the board and the module</strong>.</li>
  <li>Lower the free end of the module onto the screw.</li>
  <li>Put the nut on the screw, <strong>over the module</strong>, and tighten it.</li>
</ol>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/orange-pi-5-wifi-module-screw-from-top-full-855673dffe4c.jpg" alt="An Orange Pi 5 seen from its top face, with the heatsink fan not yet fitted and lying below the board, and the head of a screw with a cross slot sitting in the board beside the SoC, which is the screw holding the WiFi module on the other face">
  <figcaption>The top face, where the screw head sits. The heatsink fan is still off in this photo because it will cover the screw when it is mounted; it is step 3. <cite>Photo: ReveryX.</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/orange-pi-5-wifi-module-nut-fitted-full-cdfcdcd1601d.jpg" alt="A close-up of the module's face on the underside of the board: the shielded can marked AP6275P, a black dome nut standing on the module just below it, and a gold antenna socket with a lead clipped on at each side">
  <figcaption>The nut over the module, with the washer under it. <cite>Photo: ReveryX.</cite></figcaption>
</figure>

**The washer goes between the board and the module**, under the free end, not on top of it. The slot holds the contact end of the module up off the board, so the washer is what keeps the other end at the same height. Without it the nut pulls that end down and the module ends up bent and unevenly tensioned rather than sitting flat.

The screw, washer and nut come in the box with the Orange Pi 5, two sets of each, so there is nothing to buy for this.

{% include step.html n="3" title="Fit the heatsink fan" %}

Its two pins clip underneath the board, so you want to be able to reach both faces.

The official heatsink fan sits on the SoC, the large chip in the middle of the board. Check the revision printed on the board before you start: it fits the Orange Pi 5 v1.3.2 and the 5 Plus, and the mounting holes are not in the same place on earlier revisions.

Peel the films off from both sides of the thermal pad that comes in the box and lay it on the SoC.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/orange-pi-5-heatsink-thermal-pad-laid-full-de92db3b6a7f.jpg" alt="An Orange Pi 5 seen from above with a square blue thermal pad laid on the SoC in the middle of the board, the two peeled-off films above it, and the fan heatsink waiting upside down below the board with its lead already in the FAN socket">
  <figcaption>The pad on the SoC, with the two films it came between peeled off above. <cite>Photo: ReveryX.</cite></figcaption>
</figure>

Sit the heatsink squarely on top with its two tabs over the holes either side, press both spring pins down until they click, and plug the 2-pin lead into the socket marked FAN, which on a v1.3.2 board is between the CAM1 connector and the USB 2.0 port. The pins hold it on, so there are no screws here and nothing to tighten.

This is the Pi's only cooling. Its housing's roof and floor are vented, and nothing else sits over the board inside it.

## The finished result

A board that has been prepared: fan on, module in if you are using one, and ready to go into its housing.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/orange-pi-5-heatsink-fan-fitted-bench-full-de5a6f92b341.jpg" alt="An Orange Pi 5 seen from above with the finned heatsink fan fitted over the SoC in the middle of the board, a white spring pin clipped through the board at opposite corners of the heatsink, the red and black fan lead running to the small white FAN socket below it, and two antenna leads trailing off the right-hand edge of the board">
  <figcaption>The prepared board from above: the heatsink over the SoC, a spring pin through the board at each of two opposite corners, and the fan lead in the socket marked FAN. The module is on the face you cannot see, its antenna leads running out past the edge. <cite>Photo: ReveryX.</cite></figcaption>
</figure>

Carry on with [Orange Pi housing]({{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}), which closes it into its printed box.
