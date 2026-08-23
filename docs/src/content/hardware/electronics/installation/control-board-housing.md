---
layout: default
title: Control board housing
type: how-to
section: hardware
slug: electronics-control-board-housing
kicker: Electronics — Control board housing
lede: Closing the control board into its printed housing, with the 40 mm fan on a GPIO-controlled port, and bolting it to the frame.
permalink: /hardware/electronics/installation/control-board-housing/
author: spencer
og_image: https://img.basically.website/web/assembly/control-board-housing/housing-angled.c67cd89578b97f5f.jpg
parts_needed:
  - part: ctrl-board-housing-base
    qty: 1
  - part: ctrl-board-housing-cover
    qty: 1
  - part: ctrl-board-housing-plunger
    qty: 1
  - part: ctrl-board-housing-plunger-retainer
    qty: 1
  - part: ctrl-board-basically
    qty: 1
  - part: fan-40mm-24v
    qty: 1
  - part: hsi-m3
    qty: 8
  - part: scr-m3-6-bhcs
    qty: 4
  - part: scr-m3-12-bhcs
    qty: 4
  - part: scr-m3-12-cs
    qty: 4
  - part: scr-m3-8-cs
    qty: 2
  - part: scr-m5-shcs-tbd
    qty: 2
---

The board needs its drivers, Pico and jumpers in first: see [preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}).

{% include fastener-legend.html %}

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/control-board-housing/parts-laid-out.ed286d04e3a094ca.jpg" alt="All the housing parts laid out on a bench: the black printed cover on the left, the populated green control board in the middle, the black printed base with brass inserts on the right, and above them the 40 mm fan, four groups of screws, the plunger retainer and the plunger">
    <figcaption>Cover left, board centre, base right.</figcaption>
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
    <img class="doc-figure" src="https://img.basically.website/web/assembly/control-board-housing/base-inserts.2e555ad4361b5ff9.jpg" alt="The printed housing base seen from above, showing the large honeycomb vent in its floor and eight brass M3 heat inserts, four on raised bosses inside and four at the outer corners">
    <figcaption>Four inside, four at the corners.</figcaption>
  </figure>
</div>

{% include step.html n="2" title="Screw the board to the base" %}

Sit the board on the four inner bosses and fix it with 4 {% include fastener.html size="M3" variant="button" length="6" %} screws. No standoffs: the bosses are the standoffs.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/control-board-housing/board-on-base.cec346b931c22df7.jpg" alt="Left, the populated control board screwed flat onto the printed base with its two extrusion clamp bosses at the bottom. Right, the printed cover upside down with the 40 mm fan and the plunger retainer already fitted inside it">
  </figure>
</div>

{% include step.html n="3" title="Fit the fan inside the cover" %}

Fan on the inside of the cover, over the vent, label facing into the enclosure so it blows inwards. 4 {% include fastener.html size="M3" variant="button" length="12" %} screws, self-tapping into the plastic. Route the lead to the corner cutout.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/control-board-housing/fan-in-cover.c945a84566cafed1.jpg" alt="The inside of the printed cover with the 40 mm WINSINN fan screwed down over its vent opening on four screws, its red and black lead running off to the left, and the rectangular plunger slot beside it">
  </figure>
</div>

{% include step.html n="4" title="Fit the plunger and its retainer" %}

The plunger lands on the board's reset button, so the button can be pressed with the housing shut. Drop it through the slot from the outside of the cover, then hold it in with the retainer on 2 {% include fastener.html size="M3" variant="countersunk" length="8" %} self-tapping screws. It should slide freely and fall back on its own.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/control-board-housing/retainer-fitted.9b5186fe6c45a466.jpg" alt="Inside the cover, the retainer screwed down on two countersunk screws over the plunger, capturing it so it can slide but not fall out, with the fan behind">
  </figure>
</div>

{% include step.html n="5" title="Plug the fan into a GPIO-controlled port" %}

The fan runs off one of the board's four LED ports, which are 24 V switched to ground by a MOSFET the Pico drives, so the firmware can turn it on and off. Red wire to +V.

<dl class="spec-list">
  <dt>LED_0_1, LED_0_2</dt><dd>GPIO1 (output channel 0)</dd>
  <dt>LED_1_1, LED_1_2</dt><dd>GPIO6 (output channel 1)</dd>
</dl>

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/control-board-housing/fan-into-led-port.74abe08742b086c0.jpg" alt="Looking down through the cover's corner cutout at the board below, where the fan's red and black lead is plugged into the two-pin connector silkscreened LED_1_2, with Controlled by GPIO6 printed beside it">
    <figcaption>Into LED_1_2, driven by GPIO6.</figcaption>
  </figure>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Bridge the port's bypass jumper.</b> Each port feeds +V through a 180 Ω resistor meant for an LED strip, which drops most of the supply across itself. Bridge the solder jumper marked <b>Bypass R21</b>, <b>R22</b>, <b>R27</b> or <b>R28</b> for the port you used to give the fan the full 24 V.</p>
</div>

{% include step.html n="6" title="Close the housing" %}

Lower the cover on, keeping the fan lead clear of the board, and fix it with 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws into the corner inserts. The stepper connectors stay reachable through the slots in the wall.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/control-board-housing/cover-on-base.8c6a304677a0aff3.jpg" alt="The cover set down on the base with the housing closed, the fan's lead emerging through the corner cutout, and four countersunk screws lying on the bench beside it ready to go in">
  </figure>
  <figure>
    <img src="https://img.basically.website/web/assembly/control-board-housing/housing-angled.c67cd89578b97f5f.jpg" alt="The finished housing at an angle, showing the honeycomb vent and basically logo on the lid, the plunger standing proud of the surface, and the slots along the right edge that expose the stepper connectors">
  </figure>
</div>

{% include step.html n="7" title="Check the reset plunger" %}

Press the plunger on the lid. You should hear the button click.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/control-board-housing/plunger-outside.2bf22968c23a6de8.jpg" alt="Close-up of the lid surface showing the small square head of the plunger standing proud of the textured black plastic, with the honeycomb vent and basically logo nearby">
  </figure>
</div>

<div class="video-embed-self">
  <video controls preload="none" playsinline
    poster="https://assets.basically.website/sorter-docs/pressing-the-plunger-poster-6e2ab26816a2.jpg"
    width="1280" height="2275"
  >
    <source src="https://assets.basically.website/sorter-docs/pressing-the-plunger-w960-0383f6a741bb.mp4" type="video/mp4">
    <source src="https://assets.basically.website/sorter-docs/pressing-the-plunger-w1920-7d9064396d9c.mp4" type="video/mp4">
  </video>
</div>

{% include step.html n="8" title="Bolt it to the frame" %}

The two clamp bosses go onto the 2020 extrusion on 2 <span class="fastener-todo">M5, length not recorded</span> screws. Which extrusion and which orientation is not written down; the layout photo on the [installation overview]({{ '/hardware/electronics/installation/' | relative_url }}) is the only record.

<div class="img-row">
  <figure>
    <img src="https://img.basically.website/web/assembly/control-board-housing/on-the-extrusion.e931ee126522ca7a.jpg" alt="The finished housing bolted down onto a 2020 aluminium extrusion under the machine's frame, with two socket head screws through its clamp bosses">
  </figure>
</div>

Wiring next, on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page.
