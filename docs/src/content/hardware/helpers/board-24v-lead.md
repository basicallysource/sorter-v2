---
layout: default
title: Make the control board's 24 V lead
type: how-to
section: hardware
slug: helper-board-24v-lead
kicker: Helpers — Control board 24 V lead
lede: The lead that powers basically board v1.3, a barrel plug at the PSU end and a JST-VH housing crimped on at the board end. One per machine.
permalink: /hardware/helpers/board-24v-lead/
author: effreek
contributors: [spencer]
warning: >-
  **AI-generated first draft.** Written from the basically board v1.3 board files and the [wire
  harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) schedule, not from an actual build. The
  connector, the pin order and the socket come from the board itself and are real. Nobody has made
  this lead from these steps yet. The 914 mm (36 in) length is a **GUESS** in the harness notes and
  is longer than the run needs.
parts_needed:
  - part: dc-plug-5521-male
    qty: 1
  - part: wire-18awg-2c
    qty: 1
  - part: jst-vhr-2
    qty: 1
  - part: jst-svh-21t
    qty: 2
tools_needed: [Wire strippers, "Crimp tool for open-barrel contacts", Multimeter, "Soldering iron and adhesive-lined heat shrink"]
---

This is `W1` on the [harness drawings]({{ '/hardware/parts/harness-order/#board-power' | relative_url }}). It runs from one of the three jacks on the [PSU box]({{ '/hardware/electronics/installation/psu-box/' | relative_url }}) to `J1`, the 24 V input on the control board. **One per machine.**

<div class="callout">
  <p><b>This is the one 24 V lead you make yourself.</b> No supplier sells a barrel plug with a JST-VH housing on the other end, so buying one is not an option. The other two 24 V leads are bought ready made.</p>
</div>

## What the two ends are

<dl class="spec-list">
  <dt>PSU end</dt><dd>Male DC barrel plug, <b>5.5 mm outside and 2.1 mm inside</b>, centre-positive. A 2.5 mm plug looks the same and does not mate.</dd>
  <dt>Board end</dt><dd>JST <b>VH</b> housing, 2-pin (VHR-2), with a VH crimp contact on each conductor. VH pins are 3.96 mm apart, so the housing is much chunkier than the 2.0 mm PH housings the steppers use. The two do not interchange.</dd>
  <dt>Wire</dt><dd>18 AWG, two conductor, red and black. Cut it 914 mm (36 in) long.</dd>
</dl>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>A crimp kit will not have the VH housing.</b> The kit in the parts list runs 1 to 5 pin in Dupont, PH and XH only. Its crimper does take the VH contacts, so buy the VHR-2 and its contacts separately and crimp them with the kit's tool.</p>
</div>

## Build it

<ol class="numbered-steps">
  <li>Start from a moulded barrel plug on a short lead. Splice the 18 AWG pair onto it so the finished lead is 914 mm (36 in) end to end: solder each conductor, cover each one with adhesive-lined heat shrink, then sleeve both together.</li>
  <li>Find which conductor is the tip. Set the multimeter to continuity and hold one probe on the centre pin inside the plug. The conductor that beeps is <b>+24 V</b>. It is the red one on most moulded plugs, and this is the step where you find out.</li>
  <li>Strip 3 mm off the free end of each conductor.</li>
  <li>Crimp a VH contact onto each. Seat the bare strands fully in the barrel, crimp in the matching die, then pull on the wire to check it holds.</li>
  <li>Push each contact into the back of the VHR-2 housing until it clicks and will not pull out: <b>+24 V into position 1, ground into position 2</b>.</li>
</ol>

**Which position is 1.** `J1` on the board is a shrouded header, so the housing only goes on one way round. Hold the housing as it will go into that shroud: position 1 is the one over the **square pad**, and the round pad beside it is position 2. Every other pad on that footprint is round, so the square one is unambiguous.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Meter the finished lead before it goes anywhere near the PSU.</b> Continuity from the plug's centre pin to position 1 of the housing, and from the sleeve to position 2. Backwards on a 24 V input is not something the board recovers from.</p>
</div>

## Where it goes

Onto `J1` at [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 1. The PSU end goes into any of the three jacks on the PSU box; all three are the same.

## Reference

The drawing for this lead, its bill of materials and its downloads are on the [WireViz drawings]({{ '/hardware/parts/harness-order/#board-power' | relative_url }}) page.
