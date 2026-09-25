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
contributors: [daddyosbricksbill, brickcyclealice]
og_image: https://assets.basically.website/sorter-docs/harness-limit-switch-terminals-w1600-49cf87cbb757.jpg
warning: >-
  **The photographs are from a real build; one number is still a guess.** Which of the switch's
  three tabs the two conductors land on is marked as a guess in the harness notes, and no running
  machine has confirmed it. The build shown below is wired the way this page says. Meter the
  switch before you crimp.
parts_needed:
  - part: wire-22awg-2c
    qty: 1
  - part: dupont-housing-3p
    qty: 1
  - part: terminal-qc-187
    qty: 2
  - part: connector-kit-crimp
    qty: 1
tools_needed: [Wire strippers, "Crimp tool for open-barrel contacts", "Crimp tool for insulated terminals", Multimeter]
---

This is `LIM` on the [harness drawings]({{ '/hardware/parts/harness-order/#limit-switch' | relative_url }}). It runs from `J5` on the control board to the roller-lever switch on the chute. **One per machine.**

Nothing on this lead is soldered. The switch end pushes on, and the board end is two crimps.

## The two ends

<dl class="spec-list">
  <dt>Board end</dt><dd>Dupont housing, <b>1x3 female, 2.54 mm</b>, with a contact in only two of its three positions. The empty position is what keys it: it lines up with the 3.3 V pin on <code>J5</code>, so the housing cannot go on backwards.</dd>
  <dt>Which way round</dt><dd>It does not matter. <code>J5</code> position 1 is ground and position 2 is the signal, and the switch simply closes the circuit between them, so either conductor can take either one.</dd>
  <dt>Switch end</dt><dd>Two <b>#187</b> insulated quick-connect receptacles, for a 4.75 x 0.5 mm blade. They push straight onto the switch's tabs.</dd>
  <dt>Wire</dt><dd>22 AWG, two conductor. Cut it 610 mm (24 in) long.</dd>
</dl>

<figure class="harness-figure">
  <div class="diagram diagram-wide">
    <svg viewBox="0 0 930 352" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="The chute limit switch lead: a keyed 3-pin board housing on the left with position 1 ground, position 2 signal and position 3 empty over the 3.3 V pin, two wires running to the switch on the right where they land on the COM and NC tabs, the third tab NO left bare">
      <text x="0" y="20" font-size="17" font-weight="700" fill="var(--ink)">The chute limit switch lead</text>
      <text x="0" y="41" font-size="12" fill="var(--muted)">basically board v1.3 to the switch on the chute. One per machine. Nothing on it is soldered.</text>
      <rect x="0" y="92" width="265" height="186" rx="5" fill="var(--bg)" stroke="var(--ink)" stroke-width="1.5"/>
      <text x="14" y="116" font-size="13" font-weight="700" fill="var(--ink)">basically board v1.3</text>
      <text x="14" y="134" font-size="11" fill="var(--muted)">J5, printed HALL_SW_0</text>
      <circle cx="265" cy="164" r="4.5" fill="var(--ink)"/>
      <text x="251" y="168" font-size="11" font-weight="700" fill="var(--muted)" text-anchor="end">1</text>
      <text x="233" y="168" font-size="12" font-weight="600" fill="var(--ink)" text-anchor="end">GND</text>
      <circle cx="265" cy="208" r="4.5" fill="var(--ink)"/>
      <text x="251" y="212" font-size="11" font-weight="700" fill="var(--muted)" text-anchor="end">2</text>
      <text x="233" y="212" font-size="12" font-weight="600" fill="var(--ink)" text-anchor="end">SIG</text>
      <circle cx="265" cy="252" r="4.5" fill="var(--surface)" stroke="var(--muted)" stroke-width="1.5"/>
      <text x="251" y="256" font-size="11" font-weight="700" fill="var(--muted)" text-anchor="end">3</text>
      <text x="233" y="256" font-size="12" fill="var(--muted)" text-anchor="end">+3.3 V</text>
      <rect x="665" y="92" width="265" height="186" rx="5" fill="var(--bg)" stroke="var(--ink)" stroke-width="1.5"/>
      <text x="679" y="116" font-size="13" font-weight="700" fill="var(--ink)">Roller-lever switch</text>
      <text x="679" y="134" font-size="11" fill="var(--muted)">Omron V-155-1C25</text>
      <circle cx="665" cy="164" r="4.5" fill="var(--ink)"/>
      <text x="679" y="168" font-size="11" font-weight="700" fill="var(--muted)"></text>
      <text x="697" y="168" font-size="12" font-weight="600" fill="var(--ink)">NC</text>
      <circle cx="665" cy="208" r="4.5" fill="var(--ink)"/>
      <text x="679" y="212" font-size="11" font-weight="700" fill="var(--muted)"></text>
      <text x="697" y="212" font-size="12" font-weight="600" fill="var(--ink)">COM</text>
      <circle cx="665" cy="252" r="4.5" fill="var(--surface)" stroke="var(--muted)" stroke-width="1.5"/>
      <text x="679" y="256" font-size="11" font-weight="700" fill="var(--muted)"></text>
      <text x="697" y="256" font-size="12" fill="var(--muted)">NO</text>
      <line x1="0" y1="64" x2="26" y2="64" stroke="#1a1a1a" stroke-width="2.6" stroke-linecap="round"/>
      <text x="34" y="68" font-size="11" fill="var(--muted)">black</text>
      <line x1="91" y1="64" x2="117" y2="64" stroke="var(--muted)" stroke-width="5" stroke-linecap="round"/>
      <line x1="91" y1="64" x2="117" y2="64" stroke="#ffffff" stroke-width="2.6" stroke-linecap="round"/>
      <text x="125" y="68" font-size="11" fill="var(--muted)">white</text>
      <path d="M 271 164 C 465.0 164, 465.0 164, 659 164" fill="none" stroke="#1a1a1a" stroke-width="2.8" stroke-linecap="round"/>
      <path d="M 271 208 C 465.0 208, 465.0 208, 659 208" fill="none" stroke="var(--muted)" stroke-width="4.8" stroke-linecap="round"/>
      <path d="M 271 208 C 465.0 208, 465.0 208, 659 208" fill="none" stroke="#ffffff" stroke-width="2.8" stroke-linecap="round"/>
      <line x1="271" y1="252" x2="659" y2="252" stroke="var(--muted)" stroke-width="1.5" stroke-dasharray="3 5"/>
      <text x="465" y="242" font-size="11" fill="var(--muted)" text-anchor="middle">neither end carries a contact</text>
      <text x="465" y="308" font-size="12" font-weight="600" fill="var(--ink)" text-anchor="middle">Position 3 is empty and sits over the board's 3.3 V pin. That is what stops the plug going on backwards.</text>
      <text x="465" y="334" font-size="12" fill="var(--muted)" text-anchor="middle">The switch only closes the circuit between the two, so it does not matter which conductor takes which tab.</text>
    </svg>
  </div>  <figcaption>One lead end to end. The empty third position is what keys the plug.</figcaption>
</figure>

<div class="callout">
  <p><b>#187 is the small one.</b> The far more common #250 receptacle is 6.35 mm wide and will not grip these tabs. Check the size on the packet, not the picture.</p>
</div>

## Which position is which

Positions 1 to 3 of the Dupont housing, held as it goes onto `J5`:

<table style="max-width:420px">
  <thead><tr><th>Position</th><th>What it is</th></tr></thead>
  <tbody>
    <tr><td>1</td><td>Ground</td></tr>
    <tr><td>2</td><td>Signal</td></tr>
    <tr><td>3</td><td>Leave empty</td></tr>
  </tbody>
</table>

At the switch the two go on <code>COM</code> and <code>NC</code>, and which conductor takes which
of those does not matter.

**The switch prints its own tab names.** The body carries a little schematic with `NC` and `NO` against the two tabs on its side and `COM` against the one on its bottom edge, so you can read the three off the switch in your hand rather than counting positions.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/harness-limit-switch-terminals-w1600-49cf87cbb757.jpg" alt="The red roller-lever switch on a bench with its printed schematic visible, NC and NO labelled against the two tabs on its side and COM against the tab on its bottom edge, an insulated receptacle pushed onto the NC tab and another onto the COM tab, and the middle NO tab left bare">
    <figcaption>The two receptacles on <code>COM</code> and <code>NC</code>. The bare blade between them is <code>NO</code>, which stays empty. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/harness-limit-switch-mounted-w1600-c579aa172b70.jpg" alt="The same switch mounted under the machine's top plate in its printed housing, both insulated receptacles pushed on and the red and black pair leaving them and running away under the plate">
    <figcaption>The same two tabs once the switch is in its housing under the top plate. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

The switch is an SPDT with three tabs and the third one, `NO`, stays bare. Wired to `COM` and `NC` the circuit is closed while the lever is free and opens when the chute presses it, which is the way round the machine expects. If homing later runs the wrong way, that is a setting in the software rather than a rewire.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The choice of tabs is unverified.</b> The harness notes mark it as a guess and no built machine has confirmed it. Before you crimp, meter the switch: continuity between two tabs with the lever free, and none with the lever pressed, is what confirms the pair the printing names.</p>
</div>

## Build it

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/harness-limit-switch-parts-w1600-661badd2af06.jpg" alt="Laid out on a bench: the red roller-lever switch with its three bare tabs, two insulated quick-connect receptacles already crimped onto short leads, and the stripped end of a red and black 22 AWG pair">
  <figcaption>What the switch end takes: two #187 receptacles and the pair. Nothing here is soldered. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<ol class="numbered-steps">
  <li>Cut 610 mm (24 in) of the pair.</li>
  <li>Strip 3 mm off both conductors at the switch end. Crimp an insulated #187 receptacle onto each, in the die that matches the sleeve colour, then pull on the wire to check it holds.</li>
  <li>Strip 2 mm off both conductors at the board end. Crimp a Dupont contact onto each, seating the strands fully in the barrel.</li>
  <li>Push the two contacts into the housing until they click, one into position 1 and one into position 2. <b>Position 3 stays empty</b>, and that is what keys the plug.</li>
  <li>Push the two receptacles onto <code>COM</code> and <code>NC</code>. They are a firm push; the switch does not need holding in anything to do it.</li>
</ol>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Meter the finished lead.</b> With the lever free, positions 1 and 2 of the housing read continuity. Press the lever and they read open circuit. If it is the other way round, the receptacles are on <code>COM</code> and <code>NO</code>: move one tab along.</p>
</div>

## The finished result

One lead, 610 mm, with a #187 receptacle on each conductor at the switch end and a 3-pin Dupont housing at the board end whose middle position is empty.

<div class="img-placeholder">Image coming: the finished lead laid out straight, the two receptacles at one end and the keyed 3-pin housing at the other, close enough to see the empty position</div>

## Where it goes

Onto `J5` at [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 3. `J5` is the header the board prints `HALL_SW_0`; `J6` beside it is a spare input and is not this one.

## Reference

The vendor drawing for this lead, its bill of materials and its downloads are on the [WireViz
drawings]({{ '/hardware/parts/harness-order/#limit-switch' | relative_url }}) page. It shows the same lead in the form a cable supplier quotes from.
