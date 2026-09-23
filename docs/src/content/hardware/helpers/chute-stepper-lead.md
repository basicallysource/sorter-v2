---
layout: default
title: Make the chute stepper lead
type: how-to
section: hardware
slug: helper-chute-stepper-lead
kicker: Helpers — Chute stepper lead
lede: The only stepper cable you build. A 24 AWG tail onto the motor's four bare leads, then a 4-pin housing in the right coil order. One per machine.
permalink: /hardware/helpers/chute-stepper-lead/
author: effreek
contributors: [spencer, brickcyclealice]
warning: >-
  **AI-generated first draft.** Written from the basically board v1.3 board files and the [wire
  harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) schedule, not from an actual build. The
  pin order and the sockets are read off the board and are real. The cable length is a **GUESS**,
  copied from the channel stepper cables, and no harness drawing covers this cable. The motor's own
  leads have been measured on one build at 500 mm against the drawing's 300 mm, so check yours.
parts_needed:
  - part: jst-phr-4
    qty: 1
  - part: jst-sph-002t
    qty: 4
  - part: wire-24awg
    qty: 1
tools_needed: [Wire strippers, "Crimp tool for open-barrel contacts", "Soldering iron and adhesive-lined heat shrink", Multimeter]
---

The chute stepper is the NEMA 23 that drives the chute. It is the only motor on the machine with bare flying leads: the four channel steppers have their own 6-pin socket and take a bought cable. So this one lead gets built. **One per machine.**

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The motor's own leads are too thick for the connector, however long they are.</b> They are <b>20 AWG</b> (UL1007 on the motor drawing) and a JST PH contact takes 24 to 28 AWG, so the board end of this lead is always a short 24 AWG tail spliced onto them. Length decides how long that tail is, not whether you need one.</p>
</div>

## The pin order

All five stepper outputs on the board have the same pinout, pin 1 to pin 4:

<table style="max-width:420px">
  <thead><tr><th>Position</th><th>Net</th><th>Coil</th></tr></thead>
  <tbody>
    <tr><td>1</td><td><code>A2</code></td><td rowspan="2">coil A</td></tr>
    <tr><td>2</td><td><code>A1</code></td></tr>
    <tr><td>3</td><td><code>B1</code></td><td rowspan="2">coil B</td></tr>
    <tr><td>4</td><td><code>B2</code></td></tr>
  </tbody>
</table>

**Positions 1 and 2 are one coil, 3 and 4 are the other.** Swapping the two wires inside a coil only reverses the direction the motor turns. Splitting a coil across the 2 and 3 boundary is what stops it working, so keep each pair together.

The full pinout and the board-side footprint are on the [wire harness]({{ '/hardware/electronics/#31--stepper-pinout-and-polarity' | relative_url }}) page.

## Find the coils first

The motor's four leads are coloured, and the colours do not tell you which pair is which coil on every motor.

<ol class="numbered-steps">
  <li>Set the multimeter to resistance, the <b>&Omega;</b> position on its dial.</li>
  <li>Put a probe on two of the four leads. <b>A pair from the same coil reads well under an ohm</b> on this motor, 0.65 &Omega; at the winding plus whatever your probe leads add. Two leads from different coils read open circuit, which most meters show as <code>OL</code> or a lone <code>1</code>.</li>
  <li>Work through the leads until you have both pairs. Write down which colour goes with which.</li>
</ol>

## Build it

<ol class="numbered-steps">
  <li>Hold the motor where it will sit and see how far its own leads get you. They come out of the motor at 300 to 500 mm depending on the batch, and the harness notes put the finished lead at about 1 m (40 in).</li>
  <li>Splice 24 AWG of the matching colour onto each of the four, long enough to make the length up and at least 100 mm even when the motor's own leads already reach: solder each conductor, cover it with adhesive-lined heat shrink, and sleeve the four together. The thin ends are what the contacts crimp onto.</li>
  <li>Strip 2 mm off the end of each of the four <b>24 AWG</b> conductors.</li>
  <li>Crimp a PH contact onto each. Seat the strands fully in the barrel, crimp in the matching die, then pull on the wire to check it holds.</li>
  <li>Push the contacts into the housing until each one clicks: <b>one coil into positions 1 and 2, the other coil into positions 3 and 4</b>. Which coil goes in which pair does not matter. Nor does which lead of a pair goes in which position: that only reverses the direction the motor turns, and the direction is set in the software.</li>
</ol>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Check the coils again on the finished lead.</b> Meter across positions 1 and 2, then across 3 and 4. Both read the same fraction of an ohm you measured at the leads. If either reads open circuit, a contact has gone into the wrong position: pull the two out and swap them. A motor wired across the coils buzzes and barely turns.</p>
</div>

## Either socket on the board takes it

The board gives the chute two sockets side by side and they are wired to the same four nets, so the lead can end in either one:

<dl class="spec-list">
  <dt><code>J23</code></dt><dd>JST-PH 4-pin, the housing in the parts list above.</dd>
  <dt><code>J24</code></dt><dd>A row of 2.54 mm pins, which takes a 4-pin Dupont housing instead. Use this one if you have Dupont parts and no PH contacts; the crimp kit carries Dupont housings and the PH ones are a separate buy.</dd>
</dl>

Both carry `A2`, `A1`, `B1`, `B2` on positions 1 to 4, and the board prints the coil name beside each pin, so the names can be read off the board rather than counted.

## Where it goes

Onto the chute socket at [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 2, which is also where the socket decides which motor the software drives.
