---
layout: default
title: Fitting the WiFi module
type: how-to
section: hardware
slug: helper-wifi-module
kicker: Helpers — WiFi module
lede: Seating the M.2 WiFi module in the Orange Pi 5, and why it goes in while the board is still loose on the bench.
permalink: /hardware/helpers/wifi-module/
last_verified: 2026-09-18
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

Both M.2 formats used across the Orange Pi family are the same width and length, and they are told apart by where the keying notch is cut into the row of gold contacts. The original Orange Pi 5 takes the AP6275P, whose notch sits close to one end. The 5 Plus takes a different module, notched nearer the middle, and the two do not interchange.

Hold the module against the slot and check the notches line up before pushing. **If it does not want to go in, stop.** A module that will not seat is the wrong one for the board, not one that needs more force.

{% include step.html n="2" title="Seat it in the slot" %}

With the board unplugged, turn it over and find the M.2 slot on the underside.

Slide the module in at a shallow angle, roughly 30°, gold contacts first, until it is fully home. Press the free end down flat against the board and secure it with the small retention screw the module ships with.

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Connect the antennas" %}

The antenna leads end in small round push-fit connectors. Line one up squarely over its socket on the module and press straight down until it clicks. They seat with very little force and the sockets are delicate, so do not rock or lever them on at an angle.

{% include step.html n="4" title="Confirm the OS sees it" %}

Nothing else is needed to install it: the driver is in the official Orange Pi Ubuntu image that SorterOS is built on, so a SorterOS machine picks the module up on its own. Third-party OS images may not have the driver at all.

After the machine has booted, the adapter shows up in the Sorter UI under **Settings → WiFi**, which is where the network and password go in. Over SSH, `nmcli device wifi list` lists what it can see.

The board is now ready to go on its mount: carry on with [Orange Pi mount]({{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}).
