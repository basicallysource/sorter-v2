---
layout: default
title: Make the chute limit switch lead (LIM1)
type: how-to
section: hardware
slug: helper-limit-switch-lead
kicker: Helpers — Chute limit switch lead (LIM1)
lede: The lead (LIM1) from the control board to the switch that tells the machine where the chute is. Push-on receptacles at the switch, a 3-pin housing with two contacts at the board. One per machine.
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
    qty: 4
  - part: dupont-contact-female
    qty: 4
  - part: sleeving-braided-6mm
    qty: 1
    note: Optional. About 600 mm (24 in) over the pair.
tools_needed: ["Side cutters, to cut the wire to length", "A ruler or tape measure, to measure 610 mm (24 in)", "Wire strippers that take 22 AWG (0.33 mm²) wire", "Insulated-terminal crimping pliers with a die marked for 22 to 18 AWG (0.33 to 0.82 mm²), for the two #187 receptacles", "Crimping pliers for open-barrel contacts, with a die for 22 AWG (0.33 mm²) wire, for the two Dupont contacts", "Multimeter, to check the finished lead and the switch", "Optional, for the sleeving: scissors and tape, or a hot knife"]
---

This is the chute limit switch lead (`LIM1`) on the [harness drawings]({{ '/hardware/parts/harness-order/#limit-switch' | relative_url }}). It runs from `J5` on the control board to the roller-lever switch on the chute. **One per machine.**

Nothing on this lead is soldered. The switch end pushes on, and the board end is two crimps into a housing. The parts list has four receptacles and four contacts, two more of each than the lead uses: the first crimps on a new part are easy to spoil. General help with crimping is at [Crimping connectors]({{ '/hardware/helpers/crimping/' | relative_url }}).

## The two ends

<dl class="spec-list">
  <dt>Board end</dt><dd>Dupont housing, <b>1x3 female, 2.54 mm (0.1 in)</b>, with a contact in two of its three positions. The empty position goes over the pin the board prints <code>3.3V</code>.</dd>
  <dt>Switch end</dt><dd>Two <b>#187</b> insulated quick-connect receptacles, for a 4.75 x 0.5 mm (0.187 x 0.02 in) blade. They push straight onto the switch's tabs.</dd>
  <dt>Wire</dt><dd>22 AWG (0.33 mm²), two conductor. Cut it 610 mm (24 in) long. Use black for the ground wire and white for the signal wire.</dd>
</dl>

<figure class="harness-figure">
  <div class="diagram diagram-wide">
    <svg viewBox="0 0 930 352" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="The chute limit switch lead (LIM1): a 3-pin board housing on the left with position 1 ground, position 2 signal and position 3 empty over the 3.3 V pin, two wires running to the switch on the right where they land on the COM and NC tabs, the third tab NO left bare">
      <text x="0" y="20" font-size="17" font-weight="700" fill="var(--ink)">The chute limit switch lead (LIM1)</text>
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
      <line x1="0" y1="64" x2="26" y2="64" stroke="#d01012" stroke-width="2.6" stroke-linecap="round"/>
      <text x="34" y="68" font-size="11" fill="var(--muted)">red</text>
      <line x1="91" y1="64" x2="117" y2="64" stroke="#1a1a1a" stroke-width="2.6" stroke-linecap="round"/>
      <text x="125" y="68" font-size="11" fill="var(--muted)">black</text>
      <path d="M 271 164 C 465.0 164, 465.0 164, 659 164" fill="none" stroke="#1a1a1a" stroke-width="2.8" stroke-linecap="round"/>
      <path d="M 271 208 C 465.0 208, 465.0 208, 659 208" fill="none" stroke="#d01012" stroke-width="2.8" stroke-linecap="round"/>
      <line x1="271" y1="252" x2="659" y2="252" stroke="var(--muted)" stroke-width="1.5" stroke-dasharray="3 5"/>
      <text x="465" y="242" font-size="11" fill="var(--muted)" text-anchor="middle">neither end carries a contact</text>
      <text x="465" y="308" font-size="12" font-weight="600" fill="var(--ink)" text-anchor="middle">Position 3 is empty and sits over the board's 3.3 V pin. The board prints 3.3V beside that pin.</text>
      <text x="465" y="334" font-size="12" fill="var(--muted)" text-anchor="middle">The switch only closes the circuit between the two, so it does not matter which conductor takes which tab. Colours are only a guide.</text>
    </svg>
  </div>  <figcaption>One lead (<code>LIM1</code>) end to end. The empty third position goes over the board's 3.3 V pin.</figcaption>
</figure>

<div class="callout">
  <p><b>#187 is the small one.</b> The far more common #250 receptacle is 6.35 mm (0.25 in) wide and will not grip these tabs. Check the size on the packet, not the picture.</p>
</div>

## The connections

Three positions on the housing, three tabs on the switch. Two wires join them:

<dl class="spec-list">
  <dt>Wire 1</dt><dd>Housing <b>position 1</b>, which is ground, to <code>COM</code> or <code>NC</code> on the switch.</dd>
  <dt>Wire 2</dt><dd>Housing <b>position 2</b>, which is the signal, to the other of <code>COM</code> and <code>NC</code>.</dd>
  <dt>Position 3</dt><dd>Nothing. It stays empty and sits over the board's 3.3 V pin.</dd>
  <dt><code>NO</code></dt><dd>Nothing. This tab on the switch stays bare.</dd>
</dl>

Which wire goes to <code>COM</code> and which to <code>NC</code> does not matter. The switch only closes the circuit between the two, so the two wires can swap ends. What does matter is that one wire is in position 1 and the other in position 2.

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
  <p><b>The choice of tabs is unverified.</b> The harness notes mark it as a guess and no built machine has confirmed it. Before you crimp, <a href="{{ '/hardware/helpers/multimeter/' | relative_url }}#continuity-for-a-switch">meter the switch</a>: continuity between two tabs with the lever free, and none with the lever pressed, is what confirms the pair the printing names.</p>
</div>

## Build it

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/harness-limit-switch-parts-w1600-661badd2af06.jpg" alt="Laid out on a bench: the red roller-lever switch with its three bare tabs, two insulated quick-connect receptacles already crimped onto short leads, and the stripped end of a red and black 22 AWG (0.33 mm²) pair">
  <figcaption>What the switch end takes: two #187 receptacles and the pair. Nothing here is soldered. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

<ol class="numbered-steps">
  <li>Cut 610 mm (24 in) of the pair.</li>
  <li><b>Optional:</b> if you will sleeve the lead, slide a 600 mm (24 in) length of braided sleeving over the pair now, before you crimp anything onto either end. A finished receptacle or housing may not go through it, so it goes on first. Leave it bunched up on the pair for now; <a href="#sleeving-optional">Sleeving (optional)</a> says how to cut and finish it.</li>
  <li>At the switch end, crimp a #187 receptacle onto each of the two conductors, as under <b>Crimping a #187 receptacle</b>, below.</li>
  <li>At the board end, crimp a Dupont contact onto each of the two conductors, as under <b>Crimping a Dupont contact</b>, below.</li>
  <li>Push the two contacts into the housing from the back until each one clicks: the black wire into position 1, the cavity next to the moulded arrow, and the white wire into position 2. <b>Position 3 stays empty.</b></li>
  <li>Check the lead, as under <b>Check the lead</b>, below.</li>
  <li>Push the two receptacles onto <code>COM</code> and <code>NC</code>. They are a firm push; the switch does not need holding in anything to do it.</li>
</ol>

## Crimping a #187 receptacle

A #187 receptacle is a metal barrel inside a plastic sleeve. It takes 22 to 18 AWG (0.33 to 0.82 mm²) wire, so your 22 AWG (0.33 mm²) wire is at the thin end.

<ol class="numbered-steps">
  <li>Strip about 5 mm (0.2 in) off the end. Hold the wire against the receptacle to judge it: the bare strands should fill the metal barrel, and the insulation should reach the end of the barrel.</li>
  <li>Twist the strands tight and push them into the barrel as far as they go.</li>
  <li>Close the barrel in the die of the insulated-terminal pliers marked for 22 to 18 AWG (0.33 to 0.82 mm²), with the metal part in the die. Choose the die by the size marked on it, not by the colour of the sleeve.</li>
  <li>Pull on the wire to check it holds. Do the same on the other conductor.</li>
</ol>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/limit-switch-lead-receptacle-crimp-steps-full-e8bd2dc9788e.png" alt="Three stages: a wire with about 5 mm of bare strands; the wire pushed into the metal barrel of a #187 receptacle, the insulation at the end of the barrel; the barrel held between the jaws of a crimping die marked 22 to 18 AWG (0.33 to 0.82 mm²).">
  <figcaption>Strip, push in, crimp in the marked die.</figcaption>
</figure>

<div class="callout">
  <p><b>#187 is the small one.</b> The far more common #250 receptacle is 6.35 mm (0.25 in) wide and will not grip these tabs. Check the size on the packet, not the picture.</p>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>This is not the die for the Dupont contacts.</b> Pliers made for open-barrel contacts do not close an insulated receptacle properly. The Dupont contacts take their own die, below.</p>
</div>

## Crimping a Dupont contact

A Dupont contact takes 22 to 28 AWG (0.08 to 0.33 mm²) wire, so your 22 AWG (0.33 mm²) wire is at the thick end of what it takes.

<ol class="numbered-steps">
  <li>Strip about 2 mm (0.08 in) off the end and twist the strands tight.</li>
  <li>Close the contact's inner wings on the bare strands and its outer wings on the insulation, in the die of the crimping pliers marked for 22 AWG (0.33 mm²) wire. No strands should stick out past the inner wings.</li>
  <li>Pull on the wire to check it holds, then push the contact into the housing from the back until it clicks.</li>
</ol>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/limit-switch-lead-dupont-crimp-steps-full-de00ea9168c9.png" alt="Three stages: a wire with 2 mm of bare strands; a Dupont contact with its inner and outer wings open, then crimped onto the wire; two contacts pushed into positions 1 and 2 of a 3-position housing, position 3 empty.">
  <figcaption>Strip, crimp, push in until it clicks.</figcaption>
</figure>

Choose the die by the size marked on it, not by its colour.

## Check the lead

Do this before the receptacles go on the switch. Set the <a href="{{ '/hardware/helpers/multimeter/' | relative_url }}#continuity-for-tracing-a-cable">multimeter to continuity</a>.

<ol class="numbered-steps">
  <li>Touch one probe to the contact in position 1 and the other to one of the two receptacles. It beeps for one of them. That receptacle is wire 1.</li>
  <li>Touch the probe on position 1 to the other receptacle. It does not beep.</li>
  <li>Touch the two contacts in the housing to each other. They do not beep.</li>
</ol>

If the second test beeps, or the third does, something is shorting: strands are crossing at a crimp. If the first never beeps, a crimp has not gripped.

Then push the receptacles onto the switch and meter the housing again. With the lever free, positions 1 and 2 read continuity. Press the lever and they read open circuit. If it is the other way round, the receptacles are on <code>COM</code> and <code>NO</code>: move one tab along.

## Putting the housing on the board

**The housing is not keyed, so it can go on `J5` either way round.** Turned over, the two wires land on the 3.3 V pin and the signal pin: nothing is damaged, but the machine never sees the switch change.

The board prints `3.3V` and `SIG` beside `J5`. Push the housing on with the empty position over the pin marked `3.3V`. Ground is the pin at the other end, on the square pad, and that is where the moulded arrow ends up: the arrow always marks ground.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/limit-switch-lead-board-end-orientation-full-ae6132915534.png" alt="Two drawings of the 3-pin header J5 with its pins labelled 3.3V at the top, SIG in the middle and GND on a square pad at the bottom, and the housing beside it. Right way: the empty position is over the 3.3V pin and the two wires are on SIG and GND. Wrong way: the housing is turned over, the empty position is over GND and the two wires are on 3.3V and SIG.">
  <figcaption>Empty position over <code>3.3V</code>. The same housing turned over is wrong.</figcaption>
</figure>

## Sleeving (optional)

<div class="callout">
  <p><b>You can skip this and the lead works the same.</b> The sleeving is on the parts list as optional. It keeps the wires together as one tidy cable and protects them where the lead runs along the frame, and it is another way of securing the cables.</p>
</div>

**Where:** over the pair, from just short of the two receptacles to just short of the Dupont housing. About 600 mm (24 in).

**How:**

<ol class="numbered-steps">
  <li>Push the braid together lengthwise to open it: it widens as it shortens. Feed all the wires into it together, so none of them is left outside.</li>
  <li>Cut it to length with a hot knife or a soldering iron with a blade tip, so the cut melts shut. Plain scissors leave the braid fraying. With no hot tool, wrap a turn of tape around the braid where you will cut, cut through the middle of the tape with scissors, and leave the tape on.</li>
  <li>Stop the sleeving 5 to 10 mm (0.2 to 0.4 in) short of the receptacles and short of the housing, so the two receptacles can pull apart to go on their tabs and the sleeving never crowds into the housing.</li>
  <li>Hold each end with a small piece of heat shrink or a turn of tape, so that the braid cannot creep back along the wires.</li>
</ol>

Leave the sleeving loose enough to bend, and do not tie it down so tightly that it crushes the braid.


## The finished result

One lead (`LIM1`), 610 mm (24 in), with a #187 receptacle on each conductor at the switch end and a 3-pin Dupont housing at the board end whose third position is empty.

<div class="img-placeholder">Image coming: the finished lead laid out straight, the two receptacles at one end and the 3-pin housing at the other, close enough to see the empty position</div>

## Where it goes

Onto `J5` at [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 3. `J5` is the header the board prints `HALL_SW_0`; `J6` beside it is a spare input and is not this one.

## Reference

The vendor drawing for this lead (`LIM1`), its bill of materials and its downloads are on the [WireViz
drawings]({{ '/hardware/parts/harness-order/#limit-switch' | relative_url }}) page. It shows the same lead in the form a cable supplier quotes from.
