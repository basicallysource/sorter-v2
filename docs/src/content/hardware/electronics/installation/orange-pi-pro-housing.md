---
layout: default
title: Orange Pi 5 Pro housing
type: how-to
section: hardware
slug: electronics-orange-pi-pro-housing
kicker: Electronics — Orange Pi 5 Pro housing
lede: The Orange Pi 5 Pro, Max or Ultra closed into its printed housing, with the USB hub and the buck converter clamped to its roof.
permalink: /hardware/electronics/installation/orange-pi-pro-housing/
author: zed0
og_image: https://assets.basically.website/sorter-docs/orange-pi-pro-housing-finished-full-d762cdbaba34.png
tools_needed: ["Hex key, 2 mm", "Soldering iron or heat-set insert press"]
warning: >-
  **Written from the part files, not from a build.** Nobody has built this housing from these
  steps yet. Every picture on this page is a render of the part files, and each will be replaced by
  a photo once someone has built one.
parts_needed:
  - part: orange-pi-pro-housing-base
    qty: 1
  - part: orange-pi-pro-housing-wall-west
    qty: 1
  - part: orange-pi-pro-housing-wall-east
    qty: 1
  - part: orange-pi-pro-housing-wall-north
    qty: 1
  - part: orange-pi-pro-housing-wall-south
    qty: 1
  - part: orange-pi-pro-housing-roof
    qty: 1
  - part: orange-pi-pro-housing-plunger
    qty: 1
  - part: orange-pi-pro-housing-plunger-cap
    qty: 1
  - part: orange-pi-pro-housing-antenna-clamp-cap
    qty: 1
  - part: orange-pi-pro-housing-hub-clamp
    qty: 1
  - part: orange-pi-pro-housing-buck-clamp
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
    qty: 14
  - part: scr-m3-8-cs
    qty: 1
---

<div class="callout">
  <p><b>This is the housing for the Orange Pi 5 Pro, Max and Ultra.</b> If your board is the plain Orange Pi 5, build the <a href="{{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}">Orange Pi housing</a> instead: its posts are drilled for that board's hole pattern, and these are not. Build one or the other, not both. The steps are the same, apart from the plunger's retainer being part of the base here and the antenna holder taking one antenna.</p>
</div>

**Prepare the board before you start.** Anything that goes on or under the board, such as a heatsink or an antenna lead, goes on while it is loose on the bench, because the housing closes around it. [Preparing the Orange Pi]({{ '/hardware/electronics/installation/orange-pi-prep/' | relative_url }}) is written for the plain Orange Pi 5, so check what your board needs against it. Not covered here.

The fasteners and quantities are in the parts list above and are called out inline at each step. The pictures on this page are renders of the part files, not photos of a build.

{% include fastener-legend.html %}

{% include step.html n="1" title="Preparation" %}

Press 8 M3 inserts into the base while it is loose: four in the low posts the board sits on, and four in the tall corner posts the roof screws into. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}). Nothing else takes one.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/orange-pi-pro-housing-step1-inserts-full-61fa0f2315d4.png" alt="Render of the housing base seen from above and one side, with a red ring round each of the four low board posts and each of the four tall corner posts, and the plunger's retainer standing at one end of the floor">
    <figcaption>The eight insert bores: four in the low posts, four at the corners.</figcaption>
  </figure>
</div>

{% include step.html n="2" title="Screw the board down" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Static caution: the Orange Pi is ESD-sensitive like any other bare board. Touch a grounded metal surface before handling it, and avoid doing this on carpet in dry weather.</p>
</div>

Sit the board on the four posts with its Ethernet and USB-A ports at the end furthest from the large opening in the base's floor, and fasten it with 4 {% include fastener.html size="M3" variant="socket-button" length="6" %} screws into their inserts. The holes are symmetrical, so the board fits the posts either way round, and only this way puts its ports behind the openings in the walls.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/orange-pi-pro-housing-step2-board-full-0fee2b2222a8.png" alt="Exploded render of a green board lifted above the base, with a dashed line from each of its four corner screws down to a low post">
    <figcaption>The board's four screws go into the four low posts. The green plate stands for the board.</figcaption>
  </figure>
</div>

{% include step.html n="3" title="Drop the walls in" %}

Each wall drops into its own groove in the base, and each one only fits one side, because its openings line up with the ports on that side of the board:

- **West**, the short wall with a small square window for the power button plunger and a larger window onto the microSD card.
- **East**, the short wall with the three openings for the Ethernet and USB-A ports.
- **North**, the long wall with the one long opening for the HDMI, audio and USB-C ports and a block on its outside that carries the WiFi antenna. Feed the antenna's lead out through the slot at the bottom of the wall, under that block, as it goes in.
- **South**, the long wall with the hex vent, and an opening at the bottom for a cable off the GPIO header.

Nothing screws the walls in. The roof holds them down in step 6.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/orange-pi-pro-housing-step3-walls-full-aacf9cbe667f.png" alt="Exploded render of the four walls lifted clear of the base, each a different colour, with a dashed line from each one down into its groove: blue with two windows, teal with a long opening and a block on its outside, orange with three openings, purple with a hex vent pattern">
    <figcaption>Each wall drops straight down into its own groove. Blue is west (the plunger and microSD windows), teal north (HDMI, audio and USB-C), orange east (Ethernet and USB-A), purple south (the hex vent).</figcaption>
  </figure>
</div>

{% include step.html n="4" title="Fit the power button plunger" %}

The plunger reaches the board's power key from outside the west wall, so the board can be switched on with the housing shut. Its retainer is the U-shaped block at the west end of the base, so there is nothing to fit first.

Lay the plunger in the retainer with its square face out through the small window in the west wall, and close the plunger cap over it with 1 {% include fastener.html size="M3" variant="countersunk" length="8" %}. The screw cuts its own thread in the retainer, so take it by hand. Press the face from outside and check that it reaches the power key.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/orange-pi-pro-housing-step4-plunger-full-d311631a3fc8.png" alt="Close-up render of the west end of the base with its walls fitted, the plunger in blue lifted above the retainer and the plunger cap in orange lifted above that, a dashed line running down through the cap's screw hole into the retainer">
    <figcaption>The plunger (blue) lies in the retainer, and the cap (orange) closes over it on one screw. The north wall is on, so the plunger's square face is the part that goes out through the west wall.</figcaption>
  </figure>
</div>

{% include step.html n="5" title="Clamp the antenna" %}

Sit the WiFi antenna in the channel in the north wall's block, and screw the antenna cap over it with 2 {% include fastener.html size="M3" variant="countersunk" length="12" %}, self-tapping into the block. Skip this step if your board has no antenna fitted.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/orange-pi-pro-housing-step5-antenna-cap-full-7e84de0893e7.png" alt="Render of the block on the outside of the north wall with the antenna cap in blue lifted away from it along the line of its two screws, a half-round channel in each face where they meet">
    <figcaption>The cap closes over the channel in the block, and its two screws go into the block.</figcaption>
  </figure>
</div>

{% include step.html n="6" title="Put the roof on" %}

Lower the roof onto the walls grooved side down. The groove runs all the way round the underside and the tops of the four walls sit in it; on the face that ends up outside, the four corner screw holes are countersunk. Fix it with 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} into the inserts in the corner posts.

**The microSD card stays reachable with the roof on**, through the window in the west wall and the opening in the floor under it.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/orange-pi-pro-housing-step6-roof-full-b31e81aab910.png" alt="Exploded render of the roof in blue lifted above the closed walls, with a dashed line from each of its four corners down to a corner post">
    <figcaption>The roof lowers onto the four walls, and a screw at each corner goes into the corner posts.</figcaption>
  </figure>
</div>

{% include step.html n="7" title="Clamp the hub and the buck converter to the roof" %}

The powered USB hub sits on the roof under the hub clamp, the closed rectangular frame, and the 24 V to 5 V buck converter under the buck clamp, the open U. Each clamp takes 4 {% include fastener.html size="M3" variant="countersunk" length="12" %}, self-tapping into the pilots in the roof: take them by hand and stop as soon as the clamp is down.

The hub clamp is drawn around the Waveshare USB3.2-Gen1-HUB-4U. The cables into the hub and the converter (`PWR2`, `PWR3`, `USB5`, `USB6`) are on [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}).

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/orange-pi-pro-housing-step7-roof-clamps-full-f4c9126058f4.png" alt="Exploded render of the two clamps lifted off the roof of the closed housing, a closed rectangular frame in blue and an open U-shaped one in orange, each with dashed lines down to its pilot holes">
    <figcaption>Blue is the hub clamp, orange the buck clamp. Each takes four screws into the pilots in the roof.</figcaption>
  </figure>
</div>

## The finished result

The housing closed on the bench, with the hub and the buck converter's clamps on the roof.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/orange-pi-pro-housing-finished-full-d762cdbaba34.png" alt="Render of the closed Orange Pi 5 Pro housing with its hub clamp and buck clamp on the roof, the three port openings in the east wall and the block that holds the antenna on the north wall">
  <figcaption>The assembled housing, off the machine. The hub and the converter are not drawn. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

**Bolting it to the frame is on the [installation overview]({{ '/hardware/electronics/installation/' | relative_url }})**, with the other two enclosures. Its power comes from the buck converter on its roof, fed 24 V from the PSU box rather than from the control board.

Next: [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}).
