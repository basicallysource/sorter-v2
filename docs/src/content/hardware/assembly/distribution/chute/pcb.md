---
layout: default
title: Layer adapter board
type: how-to
section: hardware
slug: assembly-pcb
kicker: Chute — Layer adapter board
lede: The board that drives the servo.
permalink: /hardware/assembly/distribution/chute/pcb/
author: spencer
contributors: [barthel]
last_verified: 2026-09-07
tools_needed: ["Hex key, 2 mm for a button head or 2.5 mm for a socket head"]
parts_needed:
  - part: layer-adapter-board-basically
    qty: 1
  - part: cable-idc-2x8-short
    qty: 1
  - part: scr-m3-6-bhcs
    qty: 4
---

Each layer carries one basically Layer Adapter Board, the in-house board that breaks out the control board's ribbon connectors for that distribution layer and drives the layer's servo. One per layer.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

- The 4 M3 inserts the board sits on are part of the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }})'s 18, not extra ones.
- The board is the only thing on the chute that uses a {% include fastener.html size="M3" variant="socket-button" length="6" %} screw.

{% include step.html n="1" title="Screw the board onto the chute core" %}

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Static caution: this is a bare board. Touch a grounded metal surface before handling it, and handle it by its edges, avoiding the connectors and components.</p>
</div>

Seat it over the four inserts and fasten it with 4 {% include fastener.html size="M3" variant="socket-button" length="6" %} screws. Do not overtighten.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/chute-core-inserts-v3-rear-full-ad4c2cc7869c.png" alt="Close render of the rear end of the chute core with the four heat inserts the layer adapter board screws into circled in red">
  <figcaption>The four inserts the board sits on, all on the panel at the top end of the chute core's rear face. <cite>Render: Balloon.</cite></figcaption>
</figure>

{% include step.html n="2" title="Connect the ribbon cables (RIB1, RIB2)" %}

Do this now, while the chute is still on the bench. Once it is in the frame the ribbon sockets are hard to reach.

The board has two identical 16-pin sockets. **`J3` is the ribbon coming in (`RIB1` or `RIB2`) and `J4` is the ribbon going on down to the next layer (`RIB2`).** Nothing but the designator printed on the board tells them apart.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>A board fed on <code>J4</code> gets no signal at all, and every layer below it moves the wrong flap.</p>
</div>

Put the 300 mm (12 in) ribbon (`RIB2`) from the parts list into `J4` now and leave its far end loose. It only reaches the board below once the chutes are in the frame, so it is joined up there, at the same time as the [layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}).

`J3` takes the ribbon (`RIB2`) coming down from the board above. On the topmost chute that is the long ribbon from the control board (`RIB1`) instead, at [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 5.

Full harness routing is covered in the [harness drawings]({{ '/hardware/parts/harness-order/' | relative_url }}).

{% include step.html n="3" title="Plug the door servo into J5" %}

Do this now too, while the chute is still on the bench. `J5` is hard to reach once the chute is in the frame.

The door servo is the MG995 you fitted in the [door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}). Its lead is fixed to the servo. The lead is 300 mm (12 in) long and ends in a 3-pin plug. It hangs out of the servo bracket.

`J5` is a row of three pins beside the two ribbon sockets. The pins lie flat along the board. The board prints `GND`, `V+` and `PWM` beside them. The `PWM` pin has a square pad.

<figure class="harness-figure">
  <div class="diagram diagram-wide">
    <svg viewBox="0 0 700 225" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Close view of header J5 on the layer adapter board, seen from above. Three pins lie flat along the board, printed GND at the top, V+ in the middle and PWM at the bottom, where the pad is square. The servo's 3-pin plug is pushed onto the pins from the left: its brown wire is on GND, its red wire on V+ and its orange wire on PWM.">
      <rect x="250" y="20" width="390" height="170" rx="10" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.5"/>
      <path d="M270 70 L520 70" stroke="var(--ink)" stroke-width="3"/>
      <circle cx="529" cy="70" r="9" fill="var(--bg)" stroke="var(--ink)" stroke-width="1.5"/>
      <text x="556" y="75" font-size="13" font-weight="700" fill="var(--ink)">GND</text>
      <path d="M270 110 L520 110" stroke="var(--ink)" stroke-width="3"/>
      <circle cx="529" cy="110" r="9" fill="var(--bg)" stroke="var(--ink)" stroke-width="1.5"/>
      <text x="556" y="115" font-size="13" font-weight="700" fill="var(--ink)">V+</text>
      <path d="M270 150 L520 150" stroke="var(--ink)" stroke-width="3"/>
      <rect x="520" y="141" width="18" height="18" fill="var(--bg)" stroke="var(--ink)" stroke-width="1.5"/>
      <text x="556" y="155" font-size="13" font-weight="700" fill="var(--ink)">PWM</text>
      <rect x="210" y="45" width="90" height="125" rx="6" fill="var(--bg)" stroke="var(--primary)" stroke-width="2"/>
      <path d="M210 70 L90 70" stroke="#6b4423" stroke-width="7" stroke-linecap="round"/>
      <text x="80" y="75" font-size="12" text-anchor="end" fill="var(--ink)">brown wire</text>
      <path d="M210 110 L90 110" stroke="#d01012" stroke-width="7" stroke-linecap="round"/>
      <text x="80" y="115" font-size="12" text-anchor="end" fill="var(--ink)">red wire</text>
      <path d="M210 150 L90 150" stroke="#f08a00" stroke-width="7" stroke-linecap="round"/>
      <text x="80" y="155" font-size="12" text-anchor="end" fill="var(--ink)">orange wire</text>
      <text x="255" y="212" font-size="11" text-anchor="middle" fill="var(--muted)">the servo's 3-pin plug</text>
      <text x="580" y="190" font-size="11" text-anchor="start" fill="var(--muted)"></text>
      <path d="M538 155 L600 155" stroke="none"/>
      <text x="556" y="167" font-size="11" fill="var(--muted)">square pad</text>
      <path d="M230 75 L230 75" stroke="none"/>
      <text x="445" y="212" font-size="11" text-anchor="middle" fill="var(--muted)">the layer adapter board</text>
      <path d="M350 100 L350 100" stroke="none"/>
    </svg>
  </div>
  <figcaption>Header <code>J5</code> from above, with the servo's plug on it. Brown goes on <code>GND</code>, red on <code>V+</code> and orange on <code>PWM</code>.</figcaption>
</figure>

The pins have no key, so the plug fits either way round. You must match the wire colours to the print.

<ol class="numbered-steps">
  <li>Hold the plug so that the brown wire is at the <code>GND</code> pin, the red wire at the <code>V+</code> pin and the orange wire at the <code>PWM</code> pin.</li>
  <li>Push the plug onto the pins from the side away from the ribbon sockets. Push until it stops.</li>
  <li>Look at it again. Brown is at <code>GND</code>, red at <code>V+</code> and orange at <code>PWM</code>.</li>
</ol>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>A plug the wrong way round swaps the brown and the orange wire. The servo then does not work. Check the colours before you let go of the plug.</p>
</div>

All the cables of the layer boards are drawn together at [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 5.

## The finished result

The board screwed down on its four inserts, the 300 mm (12 in) ribbon (`RIB2`) in `J4` with its far end loose, and the door servo's plug on `J5`. `J3` is fed once the chute is in the frame.

<div class="img-placeholder">Photo of the layer adapter board screwed to the chute core, with the ribbon cable and the servo lead plugged in.</div>

The [Chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}) page carries the other three sub-assemblies that go on the same core, and is where you should return once you're done here.
