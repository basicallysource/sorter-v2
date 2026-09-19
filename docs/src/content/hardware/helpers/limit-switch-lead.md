---
layout: default
title: Make the chute limit switch lead
type: how-to
section: hardware
slug: helper-limit-switch-lead
kicker: Helpers — Chute limit switch lead
lede: The lead from the control board to the switch that tells the machine where the chute is. Push-on tabs at the switch, a keyed 3-pin housing at the board. One per machine.
permalink: /hardware/helpers/limit-switch-lead/
author: effreek
contributors: [daddyosbricksbill]
warning: >-
  **AI-generated first draft.** Written from the basically board v1.3 board files and the [wire
  harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) schedule, not from an actual build. Two
  things on this page are marked **GUESS** in the harness notes and nobody has checked either
  against a running machine: **which board pin is signal and which is ground**, and **which of the
  switch's three tabs the two conductors land on**. Meter both before you rely on them.
parts_needed:
  - part: wire-22awg-2c
    qty: 1
  - part: dupont-housing-3p
    qty: 1
  - part: terminal-qc-187
    qty: 2
tools_needed: [Wire strippers, "Crimp tool for open-barrel contacts", "Crimp tool for insulated terminals", Multimeter]
---

This is `LIM` on the [harness drawings]({{ '/hardware/parts/harness-order/#leds' | relative_url }}). It runs from `J5` on the control board to the roller-lever switch on the chute. **One per machine.**

Nothing on this lead is soldered. The switch end pushes on, and the board end is two crimps.

## The two ends

<dl class="spec-list">
  <dt>Board end</dt><dd>Dupont housing, <b>1x3 female, 2.54 mm</b>, with a contact in only two of its three positions. The empty position is what keys it: it lines up with the 3.3 V pin on <code>J5</code>, so the housing cannot go on backwards.</dd>
  <dt>Switch end</dt><dd>Two <b>#187</b> insulated quick-connect receptacles, for a 4.75 x 0.5 mm blade. They push straight onto the switch's tabs.</dd>
  <dt>Wire</dt><dd>22 AWG, two conductor. Cut it 610 mm (24 in) long.</dd>
</dl>

<div class="callout">
  <p><b>#187 is the small one.</b> The far more common #250 receptacle is 6.35 mm wide and will not grip these tabs. Check the size on the packet, not the picture.</p>
</div>

## Which position is which

Positions 1 to 3 of the Dupont housing, held as it goes onto `J5`:

<table style="max-width:420px">
  <thead><tr><th>Position</th><th>What it is</th><th>Switch tab</th></tr></thead>
  <tbody>
    <tr><td>1</td><td>Signal</td><td><code>COM</code></td></tr>
    <tr><td>2</td><td>Ground</td><td><code>NC</code></td></tr>
    <tr><td>3</td><td>Leave empty</td><td>none</td></tr>
  </tbody>
</table>

The switch is an SPDT with three tabs and the third one, `NO`, stays bare. Wired to `COM` and `NC` the circuit is closed while the lever is free and opens when the chute presses it, which is the way round the machine expects. If homing later runs the wrong way, that is a setting in the software rather than a rewire.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Both halves of that table are unverified.</b> The harness notes mark the board pin order and the choice of switch tabs as guesses, and no built machine has confirmed either. Before you crimp, meter the switch: continuity between two tabs with the lever free, and none with the lever pressed, identifies <code>COM</code> and <code>NC</code> whatever the printing says.</p>
</div>

## Build it

<ol class="numbered-steps">
  <li>Cut 610 mm (24 in) of the pair.</li>
  <li>Strip 3 mm off both conductors at the switch end. Crimp an insulated #187 receptacle onto each, in the die that matches the sleeve colour, then pull on the wire to check it holds.</li>
  <li>Strip 2 mm off both conductors at the board end. Crimp a Dupont contact onto each, seating the strands fully in the barrel.</li>
  <li>Push the two contacts into the housing until they click: <b>signal into position 1, ground into position 2</b>. Position 3 stays empty.</li>
  <li>Push the two receptacles onto <code>COM</code> and <code>NC</code>. They are a firm push; the switch does not need holding in anything to do it.</li>
</ol>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Meter the finished lead.</b> With the lever free, positions 1 and 2 of the housing read continuity. Press the lever and they read open circuit. If it is the other way round, the receptacles are on <code>COM</code> and <code>NO</code>: move one tab along.</p>
</div>

## Where it goes

Onto `J5` at [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 3. `J5` is the header the board prints `HALL_SW_0`; `J6` beside it is a spare input and is not this one.

## Reference

The drawing for this lead, its bill of materials and its downloads are on the [WireViz drawings]({{ '/hardware/parts/harness-order/#leds' | relative_url }}) page.
