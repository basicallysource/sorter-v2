---
layout: default
title: Make the channel stepper leads
type: how-to
section: hardware
slug: helper-channel-stepper-lead
kicker: Helpers — Channel stepper leads
lede: The four leads from the control board to the c-channel motors. Four per machine, all identical, and three ways to make one.
permalink: /hardware/helpers/channel-stepper-lead/
author: effreek
contributors: [daddyosbricksbill, spencer, brickcyclealice]
warning: >-
  **AI-generated first draft.** Written from the basically board v1.3 board files and the [wire
  harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) schedule, not from an actual build. The
  sockets, the pin order and the crossover are read off the board and the motor and are real.
  Nobody has made a lead from these steps yet. **The length is unsettled**: the harness drawing
  says 1 m, the ready-made cable below is 63 cm, and nobody has measured the run on a finished
  machine.
parts_needed:
  - part: jst-ph-cable-4p-63cm
    qty: 4
  - part: jst-phr-6
    qty: 4
tools_needed: [Multimeter, "A fine pick or a sliver of shim", Side cutters, "Only if you crimp instead: wire strippers and a crimp tool for open-barrel contacts"]
---

These are `S1` to `S4` on the [harness drawings]({{ '/hardware/parts/harness-order/#channel-stepper' | relative_url }}), one for each of the four c-channel motors. **Four per machine**, all identical.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The lead that comes in the box with the motor is not usable as it comes.</b> Two of its four conductors are in the wrong order for this board, so the driver drives half of one coil against half of the other and the motor buzzes and barely turns. It also ends in a Dupont housing, which does fit the 2.54 mm pins beside each stepper socket, so it looks right. Pull a Dupont contact sideways and its spring lifts off the pin: resistance rises, the joint heats, and it gets worse from there. Two have cooked on running machines.</p>
</div>

**Both faults are in that one housing.** So there are three ways to get a correct lead, and the parts above are for the first of them, which needs no crimp tool. The other two say what they need instead.

## The two ends

<dl class="spec-list">
  <dt>Board end</dt><dd>JST <b>PH</b> housing, 4-pin (PHR-4), 2.0 mm pitch, into <code>J27</code>, <code>J31</code>, <code>J35</code> or <code>J39</code>. Positions 1 to 4 are <code>A2</code>, <code>A1</code>, <code>B1</code>, <code>B2</code>.</dd>
  <dt>Motor end</dt><dd>JST <b>PH</b> housing, 6-pin (PHR-6), into the socket on the motor can. Only four of the six positions carry a contact.</dd>
  <dt>Wire</dt><dd>24 AWG, four colours. The drawing says 1 m; see the note on length below.</dd>
</dl>

### The crossover

The board and the motor do not use the same positions, so this cable is not straight through.
Board 1 goes to motor 1, 2 to 4, 3 to 3 and 4 to 6, which is the crossing pair in the middle of
the drawing. Motor positions 2 and 5 stay empty.

<figure class="harness-figure">
  <a href="https://assets.basically.website/sorter-harness/channel-stepper-full-c66a1f4a3f06.png" target="_blank" rel="noopener">
    <img src="https://assets.basically.website/sorter-harness/channel-stepper-full-c66a1f4a3f06.png" alt="WireViz drawing of one channel stepper lead: a 4-pin PHR-4 at the board with positions A2, A1, B1 and B2, four coloured conductors, and a 6-pin PHR-6 at the motor, with the middle two wires crossing so board 2 lands on motor 4 and board 3 on motor 3">
  </a>
  <figcaption>One lead end to end. The green and red conductors cross in the middle: that is the whole difference between this cable and a straight-through one. Click for full size. <cite>WireViz-generated drawing, not a photo.</cite></figcaption>
</figure>

**Positions 1 and 2 on the board are one coil, 3 and 4 are the other.** Keeping each pair together is what matters. Swapping the two wires inside a coil only reverses which way the motor turns, and the direction is set in the software.

## Build it: move four contacts

**This is what the parts list above buys**, and it needs no crimp tool. Start from a ready-made 4-pin PH cable with a PHR-4 on both ends, and leave the shipped lead in its box. **Per lead: one cable and one `PHR-6`.**

<ol class="numbered-steps">
  <li>Leave one end alone. It plugs into the board as it comes.</li>
  <li>Note which colour is in which position at the other end, before you move any of them. The colours are not the same on every cable.</li>
  <li>Get the four contacts out of that housing. Each one is held by a small lance inside the housing: press the lance back with the pick and the contact slides out of the back. Take your time, a bent lance will not hold in the new housing.</li>
  <li>Push the four contacts into the PHR-6 until each one clicks: the wire from board position 1 into motor position 1, 2 into 4, 3 into 3, 4 into 6. Motor positions 2 and 5 stay empty.</li>
  <li>Pull gently on each wire. A contact that comes back out has a bent lance; straighten it or use one of the spares.</li>
</ol>

The PHR-4 the contacts came out of is now spare.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Check the coils on the finished lead.</b> Meter across board positions 1 and 2, then across 3 and 4, with the motor plugged in. Both read a few ohms. If either reads open circuit, two contacts are in the wrong places: a motor wired across its coils buzzes and barely turns.</p>
</div>

## Or: re-house the lead the motor came with

This keeps the 1 m lead already plugged into the motor and replaces only its board end, so it is the route that costs nothing extra if you own a crimp tool. **Per lead: one `jst-phr-4` and four `jst-sph-002t` contacts**, so sixteen contacts for the machine, plus the [crimp and connector kit](https://parts-calculator.basically.website/hardware?hw=connector-kit-crimp) if you do not have a crimper. Buy neither the ready-made cable nor the PHR-6 for this route.

**The motor's own end is already right.** It is a 6-position JST-PH socket on the can, the lead is in it, the crossover above is already made inside the cable, and its 26 AWG is inside the 24 to 28 AWG a PH contact takes. Only the Dupont end is wrong.

<ol class="numbered-steps">
  <li>Cut the Dupont housing off close to the housing, so the cable keeps its length.</li>
  <li>Find the two coils with the meter before you crimp anything. Two of the four wires read a couple of ohms between them and open circuit to the other two: those two are one coil. On the motor in the parts list that reading is 2.3 &Omega;, and its colour key is black <code>A+</code>, blue <code>A-</code>, green <code>B+</code>, red <code>B-</code>, so it is usually black with blue and green with red. Meter it rather than trusting the colours.</li>
  <li>Strip about 2 mm off each conductor and crimp a contact onto it: the inner wings close on the bare strands, the outer wings on the insulation. Practise on a scrap first, the contacts are small and easy to spoil.</li>
  <li>Load the <code>PHR-4</code> with one coil in positions 1 and 2 and the other in 3 and 4, which for the colours above is black, blue, green, red. Each contact goes in from the back with its lance facing the slot in the housing, and clicks when it is home.</li>
  <li>Pull gently on each wire, then meter across positions 1 and 2 and across 3 and 4 with the motor plugged in. Both read a couple of ohms. If either reads open circuit, two contacts are in the wrong places.</li>
</ol>

The Dupont housing you cut off is scrap.

## Or: crimp the whole lead from wire

**Per lead: four conductors of `wire-24awg`, one `jst-phr-4`, one `jst-phr-6` and eight `jst-sph-002t` contacts**, so thirty-two contacts for the machine, twice the route above. Crimp each contact, seat the strands fully in the barrel, then load both housings to the crossover table above. Buy four colours of wire: the colour is how you keep the crossover straight over a metre of cable.

## How long

<div class="callout">
  <p><b>Two numbers are in circulation and neither is measured.</b> The harness drawing says 1 m. The ready-made cable in the parts list is 63 cm, which is the longest 4-pin PH-to-PH that supplier makes. The motors ship with 1 m of their own, which is the length you keep if you re-house that lead. The lengths were set while the c-channel positions were still moving, so check the run on your own frame before you cut or buy.</p>
</div>

Whatever the length, **anchor the cable above the connector**. Zip-tie it to the frame a short way back from the plug and leave a service loop, so that nothing hanging off the cable can lever the housing sideways.

## The finished result

Four leads, each with a 4-pin PHR-4 at the board end and a 6-pin PHR-6 at the motor end with two of its six positions empty.

<div class="img-placeholder">Image coming: one finished lead laid out straight, both housings in the frame, the motor end close enough to show the two empty positions</div>

## Where it goes

Onto the four channel stepper sockets at [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 2, which is also where the socket decides which motor the software drives.

## Reference

The drawing above with its bill of materials and its downloads, and the whole stepper harness it
is part of, are on the [WireViz drawings]({{ '/hardware/parts/harness-order/#channel-stepper' | relative_url }}) page.
