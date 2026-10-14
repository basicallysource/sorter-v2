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
contributors: [barthel, brickcyclealice]
og_image: https://assets.basically.website/sorter-parts/orange-pi-housing-with-hub-render-full-7d14589d8944.png
last_verified: 2026-10-14
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

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong><a href="{{ '/hardware/electronics/installation/orange-pi-prep/' | relative_url }}">Prepare the Orange Pi</a> before you start.</strong> The heatsink fan and the WiFi module both need both faces of the board reachable, and the housing closes around it. Not covered here.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/orange-pi-5-heatsink-fan-fitted-full-6f0bb3b7ada4.jpg" alt="An Orange Pi 5 v1.3.2 seen from above with the heatsink fan already fitted over the SoC in the middle of the board, a white spring pin clipped through the board at opposite corners of the finned block, and the red and black lead running from the fan to a small white 2-pin socket silkscreened FAN">
    <figcaption>A prepared Orange Pi: the fan on, and the module on the face you cannot see. <cite>Manufacturer photo (Orange Pi), not a Basically photo; the pale highlights are theirs.</cite></figcaption>
  </figure>
</div>

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

{% include step.html n="1" title="Preparation" %}

Press 8 M3 inserts into the base while it is loose: four in the low posts the Pi sits on, and four in the tall corner posts the roof screws into. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}). Nothing else takes one.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Orange Pi Housing base:</strong> 8 × M3</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-orange-pi-housing-base-inserts-w1600-b8755e5b2ba0.jpg" alt="The housing base seen from above with a brass heat-set insert pressed into each of the four low board posts and each of the four tall corner posts, the plunger retainer sitting at the right-hand end beside the large opening in the floor">
    <figcaption>Four in the board posts, four at the corners. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

**Fit the plunger retainer now, while the base is loose.** Its screw goes in from underneath, and once the walls are in you cannot turn the base over without dropping them out.

Sit the retainer on its landing, at the end of the base with the large opening in its floor, and fix it with 1 {% include fastener.html size="M3" variant="countersunk" length="12" %} up through the base from below. It cuts its own thread in the plastic, so take it by hand.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/orange-pi-housing-step1-plunger-retainer-full-8ab6ba8049dc.png" alt="Render of the west end of the housing base seen from below and to one side, with the plunger retainer lifted above its landing, the countersunk screw below the base's floor, and a dashed line running from the screw up through the floor into the retainer">
    <figcaption>The retainer on its landing at the west end of the base, and the screw that holds it coming up through the floor from underneath.</figcaption>
  </figure>
</div>

{% include step.html n="2" title="Screw the Pi down" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Static caution: the Orange Pi is ESD-sensitive like any other bare board. Touch a grounded metal surface before handling it, and avoid doing this on carpet in dry weather.</p>
</div>

Sit the Pi on the four posts with its Ethernet and USB-A ports at the end furthest from the large opening in the base's floor, and fasten it with 4 {% include fastener.html size="M3" variant="socket-button" length="6" %} screws into their inserts. It fits the posts either way round, and only this way puts its ports behind the openings in the walls.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-orange-pi-housing-board-on-base-w1600-ca5c3fdcec19.jpg" alt="The Orange Pi screwed down onto the four posts in the base, seen from above, its USB and Ethernet ports at the right-hand end and the large opening in the floor at the left, with the two WiFi antennas lying loose below it">
    <figcaption>The Pi on its four posts, ports at the end furthest from the large floor opening. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="3" title="Drop the walls in" %}

Each wall drops into its own groove in the base, and each one only fits one side, because its openings line up with the ports on that side of the Pi:

- **West**, the short wall with a small square window for the power button plunger and a larger window onto the microSD card.
- **East**, the short wall with the openings for the USB-A and Ethernet ports.
- **North**, the long wall with the opening for the USB-C and HDMI ports and a block on its outside that carries the WiFi antennas. The two antennas came with the WiFi module and are already plugged into it from [preparing the Orange Pi]({{ '/hardware/electronics/installation/orange-pi-prep/' | relative_url }}); feed them out through the slot at the bottom of the wall, under that block, as it goes in.
- **South**, the long wall with the hex vent, and an opening at the bottom for a cable off the GPIO header.

Nothing screws the walls in. The roof holds them down in step 6.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/orange-pi-housing-step3-walls-full-b22020fed729.png" alt="Exploded render of the four walls lifted clear of the base, each a different colour, with a dashed line from each one down into its groove: blue with a rounded window, teal with a long slot, orange with two square openings, purple with a hex vent pattern">
    <figcaption>Each wall drops straight down into its own groove. Blue is west (the microSD window), teal north (USB-C and HDMI), orange east (USB-A and Ethernet), purple south (the hex vent).</figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-orange-pi-housing-walls-fitted-w1600-7d1a9892715d.jpg" alt="The housing with all four walls dropped into the base, seen from above and one end, the Pi screwed to its posts inside and the vent wall nearest the camera">
    <figcaption>The four walls in. Nothing holds them yet. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="4" title="Fit the power button plunger" %}

The plunger reaches the Pi's power key from outside the west wall, so the Pi can be switched on with the housing shut.

Lay the plunger in its retainer with its square face out through the small window in the west wall, and close the plunger cap over it with 1 {% include fastener.html size="M3" variant="countersunk" length="8" %}. The screw cuts its own thread in the plastic, so take it by hand. Press the face from outside and check that it reaches the power key.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-orange-pi-housing-plunger-in-retainer-w1600-6b2edec8df12.jpg" alt="Close-up of the west end of the housing, the plunger lying in its retainer with its square face against the west wall and its other end pointing at the Pi's power key">
    <figcaption>The plunger in its retainer, its far end reaching the Pi's power key. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-orange-pi-housing-plunger-cap-fitted-w1600-27149fa9538b.jpg" alt="The housing from above with the plunger cap screwed down over the plunger at the west end">
    <figcaption>The cap closed over it. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="5" title="Clamp the antennas" %}

Sit the two WiFi antennas in the two channels in the north wall's block, and screw the antenna clamp over them with 2 {% include fastener.html size="M3" variant="countersunk" length="12" %}, self-tapping into the wall. Skip this step if the Pi has no WiFi module.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-orange-pi-housing-antenna-clamp-fitted-w1600-fbbe73d961bd.jpg" alt="The north wall of the housing seen from outside and above, two antennas standing in the two channels of the block on the wall with the antenna clamp screwed down over them">
    <figcaption>The antennas in their two channels with the clamp screwed down over them. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="6" title="Put the roof on" %}

Lower the roof onto the walls grooved side down. The groove runs all the way round the underside and the tops of the four walls sit in it; on the face that ends up outside, the four corner screw holes are countersunk. Fix it with 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} into the inserts in the corner posts.

**The microSD card stays reachable with the roof on**, through the window in the west wall and the opening in the floor under it.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-orange-pi-housing-roof-fitted-w1600-0520c0d3d2e1.jpg" alt="The roof screwed onto the housing, seen from directly above: a screw in each corner, the hex vent in the middle and two groups of four small pilot holes either side of it">
    <figcaption>The roof on, a screw in each corner. The two sets of pilot holes are for the clamps in step 7. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/orange-pi-housing-roof-underside-full-0770afc1f53f.png" alt="Render of the roof seen from underneath: a groove runs all the way round the inside of its rim, with four round bosses standing inside it and the hex vent showing through the middle">
    <figcaption>The underside, and the groove round it that the wall tops sit in. The hex vent goes right through, so it shows on both faces and does not tell them apart.</figcaption>
  </figure>
</div>

{% include step.html n="7" title="Clamp the hub and the buck converter to the roof" %}

The powered USB hub sits on the roof under the hub clamp, the closed rectangular frame, and the 24 V to 5 V buck converter under the buck clamp, the open U. Each clamp takes 4 {% include fastener.html size="M3" variant="countersunk" length="12" %}, self-tapping into the pilots in the roof: take them by hand and stop as soon as the clamp is down.

The hub clamp is drawn around the Waveshare USB3.2-Gen1-HUB-4U. The cables into the hub and the converter (`PWR2`, `PWR3`, `USB5`, `USB6`) are on [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}).

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/orange-pi-housing-step7-roof-clamps-full-cccfa381b135.png" alt="Exploded render of the two clamps lifted off the roof of the closed housing, a closed rectangular frame in blue and an open U-shaped one in orange, each with dashed lines down to its pilot holes">
    <figcaption>Blue is the hub clamp, orange the buck clamp. Each takes four screws into the pilots in the roof.</figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-orange-pi-housing-buck-clamp-fitted-w1600-b800f34f3fbb.jpg" alt="The roof of the housing seen from above with the 24 V to 5 V buck converter held down by its clamp at one corner, its USB-C lead looping down into the opening in the north wall and the other four pilot holes left empty">
    <figcaption>The buck converter under its clamp, its USB-C lead into the Pi. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

## The finished result

The housing closed on the bench, with the hub and the buck converter clamped to the roof.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/orange-pi-housing-with-hub-render-full-7d14589d8944.png" alt="Render of the Orange Pi housing with the USB hub clamped on one side of its roof and the buck converter on the other, their cables and the Pi's USB leads running off the box, and the two WiFi antennas standing in their clamp on the long wall">
  <figcaption>The assembled housing, off the machine. <cite>Rendered from the CAD, not from a build.</cite></figcaption>
</figure>

**Bolting it to the frame is on the [installation overview]({{ '/hardware/electronics/installation/' | relative_url }})**, with the other two enclosures. Its power comes from the buck converter on its roof, fed 24 V from the PSU box rather than from the control board.

Next: [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}).
