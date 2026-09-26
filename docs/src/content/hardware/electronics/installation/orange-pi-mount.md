---
layout: default
title: Orange Pi housing
type: how-to
section: hardware
slug: electronics-orange-pi-mount
kicker: Electronics — Orange Pi housing
lede: The Orange Pi 5 closed into its printed housing, with the USB hub and the buck converter clamped to its roof.
permalink: /hardware/electronics/installation/orange-pi-mount/
author: spencer
contributors: [barthel]
og_image: https://assets.basically.website/sorter-parts/orange-pi-housing-with-hub-render-full-7d14589d8944.png
warning: >-
  **AI-generated first draft.** These steps are written from the models, not from a build, so nobody
  has put this housing together from this page yet. The parts and the screws come from the CAD
  assembly.
tools_needed: ["Hex key, 2 mm", "Soldering iron or heat-set insert press"]
parts_needed:
  - part: orange-pi-housing-base
    qty: 1
  - part: orange-pi-housing-wall-west
    qty: 1
  - part: orange-pi-housing-wall-east
    qty: 1
  - part: orange-pi-housing-wall-north
    qty: 1
  - part: orange-pi-housing-wall-south
    qty: 1
  - part: orange-pi-housing-roof
    qty: 1
  - part: orange-pi-housing-plunger
    qty: 1
  - part: orange-pi-housing-plunger-retainer
    qty: 1
  - part: orange-pi-housing-plunger-cap
    qty: 1
  - part: orange-pi-housing-antenna-clamp
    qty: 1
  - part: orange-pi-housing-hub-clamp
    qty: 1
  - part: orange-pi-housing-buck-clamp
    qty: 1
  - part: sbc-orange-pi-5
    qty: 1
  - part: usb-hub-powered-24v
    qty: 1
  - part: buck-24v-5v-usbc
    qty: 1
  - part: hsi-m3
    qty: 8
  - part: scr-m3-6-bhcs
    qty: 4
  - part: scr-m3-12-cs
    qty: 15
  - part: scr-m3-8-cs
    qty: 1
---

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

One per machine. Which Orange Pi 5 to buy, how much RAM and storage it needs, the WiFi module, the USB hub and cooling are all on the [Orange Pi 5]({{ '/hardware/orange-pi-5/' | relative_url }}) page. This page is the build on the bench: the Pi screws down into the base, four walls drop in around it, the roof screws down over them, and the USB hub and the buck converter that powers the Pi clamp onto the roof.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong><a href="{{ '/hardware/electronics/installation/orange-pi-prep/' | relative_url }}">Prepare the Orange Pi</a> before you start.</strong> The heatsink fan, the WiFi module and the first boot that sets the network all need both faces of the board reachable, and the housing closes around it. Not covered here.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/orange-pi-5-heatsink-fan-fitted-full-6f0bb3b7ada4.jpg" alt="An Orange Pi 5 v1.3.2 seen from above with the heatsink fan already fitted over the SoC in the middle of the board, a white spring pin clipped through the board at opposite corners of the finned block, and the red and black lead running from the fan to a small white 2-pin socket silkscreened FAN">
    <figcaption>A prepared Orange Pi: the fan on, and the module on the face you cannot see. <cite>Manufacturer photo (Orange Pi), not a Basically photo; the pale highlights are theirs.</cite></figcaption>
  </figure>
</div>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/orange-pi-housing-render-full-1f26a3ba6570.png" alt="Render of the closed Orange Pi housing: a light blue printed box with a vented roof carrying two empty rectangular clamps, the WiFi antennas standing in a clamp on one long wall, and openings in the end wall for the Pi's USB and Ethernet ports">
  <figcaption>The housing closed, with the hub and the buck converter left off the roof so their clamps show. <cite>Rendered from the CAD, not from a build.</cite></figcaption>
</figure>

**The parts come in the position they sit in the box, not the way they print.** Lay the four walls flat on the bed, and print the roof upside down, top face on the bed.

{% include step.html n="1" title="Preparation" %}

Press 8 M3 inserts into the base while it is loose: four in the posts the Pi sits on, and four in the corner posts the roof screws into. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}). Nothing else takes one.

{% include step.html n="2" title="Screw the Pi down" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Static caution: the Orange Pi is ESD-sensitive like any other bare board. Touch a grounded metal surface before handling it, and avoid doing this on carpet in dry weather.</p>
</div>

Sit the Pi on the four posts and fasten it with 4 {% include fastener.html size="M3" variant="socket-button" length="6" %} screws into their inserts. The posts are the standoffs, so there are none to fit.

{% include step.html n="3" title="Drop the walls in" %}

Each wall drops into its own groove in the base, and each one only fits one side, because its openings line up with the ports on that side of the Pi:

- **West**, the short wall with a small square window for the power button plunger and a larger window onto the microSD card.
- **East**, the short wall with the openings for the USB-A and Ethernet ports.
- **North**, the long wall with the opening for the USB-C and HDMI ports and a block on its outside for the WiFi antennas. Feed the antennas out through the slot at the bottom of the wall, under that block, as it goes in.
- **South**, the long wall with the hex vent, and an opening at the bottom for a cable off the GPIO header.

Nothing screws the walls in. The roof holds them down in step 6.

{% include step.html n="4" title="Fit the power button plunger" %}

The plunger reaches the Pi's power key from outside the west wall, so the Pi can be switched on with the housing shut.

Screw the plunger retainer onto its landing beside the west wall with 1 {% include fastener.html size="M3" variant="countersunk" length="12" %} from underneath the base. Lay the plunger in it with its square face out through the small window in the west wall, and close the plunger cap over it with 1 {% include fastener.html size="M3" variant="countersunk" length="8" %}. Both screws cut their own thread in the plastic, so take them by hand. Press the face from outside and check that it reaches the power key.

{% include step.html n="5" title="Clamp the antennas" %}

Sit the two WiFi antennas in their saddles on the north wall's block, and screw the antenna clamp over them with 2 {% include fastener.html size="M3" variant="countersunk" length="12" %}, self-tapping into the wall. Skip this step if the Pi has no WiFi module.

{% include step.html n="6" title="Put the roof on" %}

Lower the roof onto the walls, recessed side down, and fix it with 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} into the inserts in the corner posts.

**The microSD card stays reachable with the roof on**, through the window in the west wall and the opening in the floor under it.

{% include step.html n="7" title="Clamp the hub and the buck converter to the roof" %}

The powered USB hub sits on the roof under the hub clamp, and the 24 V to 5 V buck converter under the buck clamp. Each clamp takes 4 {% include fastener.html size="M3" variant="countersunk" length="12" %}, self-tapping into the pilots in the roof: take them by hand and stop as soon as the clamp is down.

The hub clamp is drawn around the Waveshare USB3.2-Gen1-HUB-4U. The cables into the hub and the converter are on [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}).

## The finished result

The housing closed on the bench, with the hub and the buck converter clamped to the roof.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/orange-pi-housing-with-hub-render-full-7d14589d8944.png" alt="Render of the Orange Pi housing with the USB hub clamped on one side of its roof and the buck converter on the other, their cables and the Pi's USB leads running off the box, and the two WiFi antennas standing in their clamp on the long wall">
  <figcaption>The assembled housing, off the machine. <cite>Rendered from the CAD, not from a build.</cite></figcaption>
</figure>

**Bolting it to the frame is on the [installation overview]({{ '/hardware/electronics/installation/' | relative_url }})**, with the other two enclosures. Its power comes from the buck converter on its roof, fed 24 V from the PSU box rather than from the control board, and that, the USB hub and the cameras are all on [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), which is the next page.
