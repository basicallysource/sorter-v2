---
layout: default
title: Preparing the 3D printed cable cage plates
type: how-to
section: hardware
slug: helper-cable-cage-plates
kicker: Helpers — Cable cage plates
lede: Gluing the printed cable cage pieces into the two hexagonal plates, as an alternative to laser-cut ones.
permalink: /hardware/helpers/cable-cage-plates/
author: barthel
contributors: [zed0]
og_image: https://assets.basically.website/sorter-docs/cable-cage-printed-plates-layout-full-de9f8dfcc872.png
parts_needed:
  - part: cage-top-hex-corner
    qty: 10
  - part: cage-top-motor-piece
    qty: 1
  - part: scr-m3-12-bhcs
    qty: 12
    temporary: true
    note: Only a temporary clamp while the glue sets. They come out again.
  - part: nut-m3
    qty: 12
    temporary: true
    note: Only a temporary clamp while the glue sets. They come out again.
tools_needed: ["Superglue (cyanoacrylate)", "A flat surface to build the plate on", "A 2.5 mm hex key, for the M3 bolts", "A file or sandpaper, for any hard glue"]
---

<div class="callout">
  <p><b>This page is optional.</b> The standard build has both cable cage plates laser-cut, or cut by hand from the <a href="https://parts-calculator.basically.website/lasercut">parts calculator's laser-cut page</a>. If you would rather print them, this page turns the printed pieces into the same two plates, and the <a href="{{ '/hardware/assembly/distribution/top-interface/' | relative_url }}">top interface</a> page takes it from there.</p>
</div>

Each plate is made of several flat pieces. Where two pieces meet, each has a half-thickness step, and the two steps overlap. Two M3 holes go through every overlap. **Ten hex corners and one motor piece make both plates:**

- **The plate with the plain round centre hole** is **six hex corners**. It is the one that goes on at step 10 of the top interface page.
- **The plate with the keyed cutout** is **four hex corners and the one motor piece**. The motor piece is the one with the pocket in its edge. It goes on at step 12.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/cable-cage-printed-plates-layout-full-de9f8dfcc872.png" alt="Two hexagonal plates drawn from above. Left: six identical corner pieces around a plain round hole, alternate pieces shaded dark and light, each joint a narrow overlap strip with two red M3 holes. Right: four of the same corner pieces and one orange motor piece that carries the keyed pocket on the left of the hole, five overlap strips with two red M3 holes each.">
  <figcaption>The two plates and which piece goes where. Each overlap strip is one joint. <cite>Drawing: Balloon, from the STL files.</cite></figcaption>
</figure>

Print the pieces in PLA, with the **Print settings** at the top of the [parts calculator](https://parts-calculator.basically.website/). Print every piece flat on the bed, the way the file comes.

{% include step.html n="1" title="Dry-fit the plate" %}

Lay the pieces on a flat surface in the order in the drawing above, **with every other corner piece turned upside down**. At each overlap one piece has its step on the underside and the next has its step on the top. If an overlap does not lie flat, turn one of the two pieces over.

{% include step.html n="2" title="Clamp the joints with M3 bolts" %}

Put an {% include fastener.html size="M3" variant="socket-button" length="12" %} bolt through each of the two M3 holes in every joint, with an {% include fastener.html size="M3" variant="nut" %} on the back, and tighten them by hand until the pieces lie flat. That is two bolts per joint, so **12 for the six-piece plate and 10 for the five-piece one**, and the same bolts go on the second plate once the first is done.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The bolts are only a clamp.</b> They come out again in step 4. Do not overtighten them: the plate must stay flat.</p>
</div>

{% include step.html n="3" title="Glue every joint" %}

With the plate flat and the bolts in, put superglue between the two steps of every overlap, then press them together. Keep the plate flat on the table. Leave it for the full curing time on the glue's label before you lift it.

{% include step.html n="4" title="Take the M3 hardware out" %}

Once the glue has cured, take every bolt and nut out. **Leave nothing in the plate:** the ribbon cable runs through the cage, and a bolt or nut left on the plate catches it as the chute turns. Run a fingertip over both faces of every overlap, and file or sand any hard glue flat.

Do the other plate the same way.

## Check the plate before it goes on

Look at the central hole of the finished plate. The edge must be smooth all the way round, with no step or lump of glue at any overlap, because the chute turns inside it.

## Where it goes

The plate with the plain round hole goes on at [step 10]({{ '/hardware/assembly/distribution/top-interface/#step-10' | relative_url }}) of the top interface page, and the plate with the keyed cutout at [step 12]({{ '/hardware/assembly/distribution/top-interface/#step-12' | relative_url }}). Nothing else about the cage changes.
