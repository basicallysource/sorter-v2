---
layout: default
title: Control board housing
type: how-to
section: hardware
slug: electronics-control-board-housing
kicker: Electronics — Control board housing
lede: Closing the control board into its printed housing, with the 40 mm fan on a GPIO-controlled port and the reset plunger in its lid.
permalink: /hardware/electronics/installation/control-board-housing/
author: spencer
og_image: https://assets.basically.website/sorter-docs/assembly-control-board-housing-housing-angled-w1600-d8c3ed33682d.jpg
tools_needed: ["Hex keys, 2 mm and 2.5 mm", "Soldering iron or heat-set insert press"]
parts_needed:
  - part: ctrl-board-housing-base
    qty: 1
  - part: ctrl-board-housing-cover
    qty: 1
  - part: ctrl-board-housing-plunger
    qty: 1
  - part: ctrl-board-housing-plunger-retainer
    qty: 1
  - part: ctrl-board-housing-fan-retainer
    qty: 2
  - part: ctrl-board-basically
    qty: 1
  - part: fan-40mm-24v
    qty: 1
  - part: hsi-m3
    qty: 8
  - part: scr-m3-6-bhcs
    qty: 4
  - part: scr-m3-12-cs
    qty: 4
  - part: scr-m3-8-cs
    qty: 6
---

The board needs its drivers, Pico and jumpers in first: see [preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}).

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-parts-laid-out-w1600-ce307f40e5fe.jpg" alt="All the housing parts laid out on a bench: the black printed cover on the left, the populated green control board in the middle, the black printed base with brass inserts on the right, and above them the 40 mm fan, four groups of screws, the plunger retainer and the plunger">
    <figcaption>Cover left, board centre, base right. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

Eight screws go into the base: four hold the board down, four close the cover over it.

{% include step.html n="1" title="Preparation" %}

Press 8 M3 inserts into the base while it is loose: four on the inner bosses for the board, four at the corners for the cover. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}). Nothing else takes one.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Control Board Housing base:</strong> 8 × M3</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-base-inserts-w1600-b45ee1e919a8.jpg" alt="The printed housing base seen from above, showing the large honeycomb vent in its floor and eight brass M3 heat inserts, four on raised bosses inside and four at the outer corners">
    <figcaption>Four inside, four at the corners. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

{% include step.html n="2" title="Screw the board to the base" %}

Sit the board on the four inner bosses and fix it with 4 {% include fastener.html size="M3" variant="button" length="6" %} screws. No standoffs: the bosses are the standoffs.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-board-on-base-w1600-481484d82b53.jpg" alt="Left, the populated control board screwed flat onto the printed base with its two extrusion clamp bosses at the bottom. Right, the printed cover upside down with the 40 mm fan and the plunger retainer already fitted inside it">
    <figcaption><cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

{% include step.html n="3" title="Fit the fan inside the cover" %}

With the cover upside down, lay the fan in over the vent, label facing into the enclosure so it blows inwards. The two fan retainers hold it: lay one across each of the fan's two edges, its two pegs down in the fan's corner holes, and screw each to the cover with 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} screws, self-tapping into the posts beside the fan. Route the lead to the corner cutout.

Take these four by hand and stop as soon as the retainer is down on its post. They cut their own thread in the plastic.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-fan-in-cover-w1600-73bbe941cbdb.jpg" alt="The inside of the printed cover with the 40 mm WINSINN fan screwed down over its vent opening on four screws, its red and black lead running off to the left, and the rectangular plunger slot beside it">
    <figcaption>The earlier cover, where the fan screwed straight into the plastic through its own corners. The current one holds it with the two retainers. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

{% include step.html n="4" title="Fit the plunger and its retainer" %}

The plunger lands on the board's reset button, so the button can be pressed with the housing shut. Drop it through the slot from the outside of the cover, then hold it in with the retainer on 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} self-tapping screws. It should slide freely and fall back on its own.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-retainer-fitted-w1600-c7677da6c247.jpg" alt="Inside the cover, the retainer screwed down on two countersunk screws over the plunger, capturing it so it can slide but not fall out, with the fan behind">
    <figcaption><cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

What that buys you is easier to see in section, once the cover is on: the plunger's head sits just below the lid's surface, the retainer holds it in the slot, and its foot sits over the button on the board. The renders below are of the earlier plunger, which stood proud of the lid.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/ctrl-board-housing-assembly-render-full-6f4acadd3ffc.png" alt="Onshape render of the control board housing, closed, standing on a length of 2020 extrusion, with the honeycomb fan vent and the square plunger head in the cover">
    <figcaption>The housing closed. <cite>Rendered from the part geometry, not from a build. Render: Spencer.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/ctrl-board-housing-plunger-section-full-a5319da2b902.png" alt="Section through the closed housing at the plunger: the plunger passes down through the cover, the retainer holds it in the slot, and its foot stands over the reset button on the board below">
    <figcaption>The same housing cut at the plunger: through the cover, held by the retainer, standing over the board. <cite>Rendered from the part geometry, not from a build. Render: Spencer.</cite></figcaption>
  </figure>
</div>

{% include step.html n="5" title="Plug the fan into a GPIO-controlled port" %}

The fan runs off one of the board's four LED ports. The red wire goes to `+V`.

<dl class="spec-list">
  <dt>LED_0_1, LED_0_2</dt><dd>GPIO1 (output channel 0)</dd>
  <dt>LED_1_1, LED_1_2</dt><dd>GPIO6 (output channel 1)</dd>
</dl>

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-fan-into-led-port-w1600-cfd2665dc48e.jpg" alt="Looking down through the cover's corner cutout at the board below, where the fan's red and black lead is plugged into the two-pin connector silkscreened LED_1_2, with Controlled by GPIO6 printed beside it">
    <figcaption>Into LED_1_2, driven by GPIO6. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Double check the port's bypass jumper is bridged.</b> Each port feeds +V through a 180 Ω resistor meant for a COB LED board, and with it still in circuit the fan will barely turn, if it turns at all, because most of the 24 V drops across the resistor instead of reaching the fan. All four are bridged in <a href="{{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}">preparing the control board</a>, step 4; look for solder across the two pads marked <b>Bypass R21</b>, <b>R22</b>, <b>R27</b> or <b>R28</b> beside the port you used, and do it now if it is missing, before the board goes in.</p>
</div>

{% include step.html n="6" title="Close the housing" %}

Lower the cover on, keeping the fan lead clear of the board, and fix it with 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws into the corner inserts. The stepper connectors stay reachable through the slots in the wall.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-cover-on-base-w1600-a77ec49b9e64.jpg" alt="The cover set down on the base with the housing closed, the fan's lead emerging through the corner cutout, and four countersunk screws lying on the bench beside it ready to go in">
    <figcaption><cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

{% include step.html n="7" title="Check the reset plunger" %}

Press the plunger on the lid. Its head sits just below the surface, so it takes a fingertip pressed into the recess. You should hear the button click.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-plunger-outside-w1600-737114636bdb.jpg" alt="Close-up of the lid surface showing the small square head of the plunger standing proud of the textured black plastic, with the honeycomb vent and basically logo nearby">
    <figcaption>The earlier plunger, which stood proud of the lid. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

<figure class="video-figure">
  <div class="video-embed-self">
    <video controls preload="none" playsinline
      poster="https://assets.basically.website/sorter-docs/pressing-the-plunger-poster-6e2ab26816a2.jpg"
      width="1280" height="2275"
    >
      <source src="https://assets.basically.website/sorter-docs/pressing-the-plunger-w960-0383f6a741bb.mp4" type="video/mp4">
      <source src="https://assets.basically.website/sorter-docs/pressing-the-plunger-w1920-7d9064396d9c.mp4" type="video/mp4">
    </video>
  </div>
  <figcaption><cite>Video: Spencer.</cite></figcaption>
</figure>

## The finished result

The housing closed, with the fan and the reset plunger in the cover and the stepper connectors still reachable through the slots in the wall.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-control-board-housing-housing-angled-w1600-d8c3ed33682d.jpg" alt="The finished housing at an angle, showing the honeycomb vent and basically logo on the lid, the plunger standing proud of the surface, and the slots along the right edge that expose the stepper connectors">
  <figcaption>The closed housing, from above and to one side. <cite>Photo: Spencer.</cite></figcaption>
</figure>

**Bolting it to the frame is on the [installation overview]({{ '/hardware/electronics/installation/' | relative_url }})**, once all three enclosures are built.

Next: [preparing the Orange Pi]({{ '/hardware/electronics/installation/orange-pi-prep/' | relative_url }}).
