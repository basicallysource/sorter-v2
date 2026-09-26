---
layout: default
title: Make the channel stepper leads
type: how-to
section: hardware
slug: helper-channel-stepper-lead
kicker: Helpers — Channel stepper leads
lede: The four leads from the control board to the c-channel motors. Re-house the lead the motor came with, move four contacts into a 6-pin housing, or crimp the whole lead from wire. Four per machine.
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
  - part: jst-phr-4
    qty: 4
  - part: jst-sph-002t
    qty: 16
  - part: jst-ph-cable-4p-63cm
    qty: 4
  - part: jst-phr-6
    qty: 4
tools_needed: [Multimeter, Side cutters, "Only if you crimp: wire strippers and a crimp tool for open-barrel contacts", "Only if you move contacts: a fine pick or a sliver of shim"]
---

These are `S1` to `S4` on the [harness drawings]({{ '/hardware/parts/harness-order/#steppers' | relative_url }}), one for each of the four c-channel motors. **Four per machine**, all identical.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The lead that comes in the box with the motor is not usable as it comes.</b> Two of its four conductors are in the wrong order for this board, and it ends in a Dupont housing rather than a JST-PH. Both faults are in that one housing, so the first route below cuts it off and puts a JST-PH on instead; the other two build a new lead.</p>
</div>

## What is wrong with the end it comes with

The StepperOnline NEMA 17s arrive with a 1 m lead already plugged into the motor, ending in a 4-way Dupont housing. That housing does fit the row of 2.54 mm pins beside each stepper socket on the board, so it looks like it will work, and it will not.

<dl class="spec-list">
  <dt>The order is wrong</dt><dd>Two of the four conductors have to change places before the motor turns properly. Plugged in as it comes, the driver drives half of one coil against half of the other: the motor buzzes, jitters and barely turns.</dd>
  <dt>Dupont does not take side load</dt><dd>Pull a Dupont contact sideways and the spring lifts off the pin. Resistance goes up, the joint heats, and it gets worse from there. Two have failed that way on running machines, which is why the steppers were moved onto the JST-PH sockets in the first place.</dd>
</dl>

Both of those live in the Dupont end. **The motor's own end is fine**: it is a 6-position JST-PH socket on the can, the lead is already in it, and the crossover below is already made inside the cable. The wire is 26 AWG, which is inside the 24 to 28 AWG a PH contact takes. So cutting that one housing off and crimping a `PHR-4` on in the right order gives a correct lead, and that is the first route below.

## The two ends

<dl class="spec-list">
  <dt>Board end</dt><dd>JST <b>PH</b> housing, 4-pin (PHR-4), 2.0 mm pitch, into <code>J27</code>, <code>J31</code>, <code>J35</code> or <code>J39</code>. Positions 1 to 4 are <code>A2</code>, <code>A1</code>, <code>B1</code>, <code>B2</code>.</dd>
  <dt>Motor end</dt><dd>JST <b>PH</b> housing, 6-pin (PHR-6), into the socket on the motor can. Only four of the six positions carry a contact.</dd>
  <dt>Wire</dt><dd>24 AWG, four colours. The drawing says 1 m; see the note on length below.</dd>
</dl>

### The crossover

The board and the motor do not use the same positions, so this cable is not straight through.

<table style="max-width:460px">
  <thead><tr><th>Board position</th><th>Net</th><th>Motor position</th></tr></thead>
  <tbody>
    <tr><td>1</td><td><code>A2</code></td><td>1</td></tr>
    <tr><td>2</td><td><code>A1</code></td><td>4</td></tr>
    <tr><td>3</td><td><code>B1</code></td><td>3</td></tr>
    <tr><td>4</td><td><code>B2</code></td><td>6</td></tr>
    <tr><td colspan="2">not used</td><td>2 and 5 stay empty</td></tr>
  </tbody>
</table>

**Positions 1 and 2 on the board are one coil, 3 and 4 are the other.** Keeping each pair together is what matters. Swapping the two wires inside a coil only reverses which way the motor turns, and the direction is set in the software.

If you are re-housing the lead the motor came with, this crossover is already made: it sits between the 6-pin housing and the wires, and none of it changes when you replace the other end.

## Build it: re-house the lead the motor came with

This route uses the 1 m lead already plugged into the motor and replaces only its board end. It needs a crimp tool. **Per lead: one `PHR-4` and four contacts**, so sixteen contacts for the machine. The connector kit in the parts list carries the housings, the contacts and the crimper in one box; the housing and the contacts on their own are the same job if you already own a crimper.

<ol class="numbered-steps">
  <li>Cut the Dupont housing off close to the housing, so the cable keeps its length.</li>
  <li>Find the two coils <a href="{{ '/hardware/helpers/multimeter/' | relative_url }}#resistance-for-finding-a-steppers-coils">with the meter</a> before you crimp anything. Two of the four wires read a couple of ohms between them and open circuit to the other two: those two are one coil. On the motor in the parts list that reading is 2.3 Ω, and its colour key is black <code>A+</code>, blue <code>A-</code>, green <code>B+</code>, red <code>B-</code>, so it is usually black with blue and green with red. Meter it rather than trusting the colours.</li>
  <li>Strip about 2 mm off each conductor and crimp a contact onto it: the inner wings close on the bare strands, the outer wings on the insulation. Practise on a scrap first, the contacts are small and easy to spoil.</li>
  <li>Load the <code>PHR-4</code> with one coil in positions 1 and 2 and the other in 3 and 4, which for the colours above is black, blue, green, red. Each contact goes in from the back with its lance facing the slot in the housing, and clicks when it is home.</li>
  <li>Pull gently on each wire, then meter across positions 1 and 2 and across 3 and 4 with the motor plugged in. Both read a couple of ohms. If either reads open circuit, two contacts are in the wrong places.</li>
</ol>

The motor end needs nothing done to it, and the Dupont housing you cut off is scrap.

## Build it: move four contacts

This is the route with no crimping, and it leaves the shipped lead in the box. Start from a ready-made 4-pin PH cable with a PHR-4 on both ends. **Per lead: one cable and one `PHR-6`.**

<ol class="numbered-steps">
  <li>Leave one end alone. It plugs into the board as it comes.</li>
  <li>At the other end, get the four contacts out of the housing. Each one is held by a small lance inside the housing: press the lance back with a fine pick or a sliver of shim and the contact slides out of the back. Take your time. A bent lance will not hold in the new housing.</li>
  <li>Note which colour came out of which position before you move any of them. The colours are not the same on every cable, so meter them rather than trusting a photo.</li>
  <li>Push the four contacts into the PHR-6 until each one clicks: the wire from board position 1 into motor position 1, 2 into 4, 3 into 3, 4 into 6. Motor positions 2 and 5 stay empty.</li>
  <li>Pull gently on each wire. A contact that comes back out has a bent lance; straighten it or use one of the spares.</li>
</ol>

The PHR-4 the contacts came out of is now spare.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Check the coils on the finished lead.</b> Meter across board positions 1 and 2, then across 3 and 4, with the motor plugged in. Both read a few ohms. If either reads open circuit, two contacts are in the wrong places: a motor wired across its coils buzzes and barely turns.</p>
</div>

## Build it: crimp from wire

If you would rather make the whole lead, it is four conductors of 24 AWG with a `jst-phr-4` at the board end, a `jst-phr-6` at the motor end and eight `jst-sph-002t` contacts, which is twice the contact count of the first route. Crimp each contact, seat the strands fully in the barrel, then load both housings to the table above. Four colours are worth buying for this: the colour is how you keep the crossover straight over a metre of cable.

## How long

<div class="callout">
  <p><b>Two numbers are in circulation and neither is measured.</b> The harness drawing says 1 m. The ready-made cable in the parts list is 63 cm, which is the longest 4-pin PH-to-PH that supplier makes. The motors ship with 1 m of their own, which is the length you keep if you re-house that lead. The lengths were set while the c-channel positions were still moving, so check the run on your own frame before you cut or buy.</p>
</div>

Whatever the length, **anchor the cable above the connector**. Zip-tie it to the frame a short way back from the plug and leave a service loop, so that nothing hanging off the cable can lever the housing sideways. That is the failure the JST-PH socket was chosen to avoid, and a badly routed PH connector can still get there.

## Where it goes

Onto the four channel stepper sockets at [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 2, which is also where the socket decides which motor the software drives.

## Reference

The drawing for this cable, its bill of materials and its downloads are on the [WireViz drawings]({{ '/hardware/parts/harness-order/#steppers' | relative_url }}) page.
