---
layout: default
title: Make the chute stepper lead
type: how-to
section: hardware
slug: helper-chute-stepper-lead
kicker: Helpers — Chute stepper lead
lede: The only stepper cable you build. A 24 AWG (0.20 mm²) tail onto the motor's four bare leads, then a 4-pin housing in the right coil order. One per machine.
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
  - part: butt-connector-24-20
    qty: 4
  - part: wire-24awg
    qty: 1
tools_needed: ["Multimeter, to find the coils and to check the finished lead", "Side cutters, to cut the tail wire to length", "Wire strippers that take both 24 AWG (0.20 mm²) and 20 AWG (0.52 mm²) wire", "Insulated-terminal crimping pliers with a die marked for 24 to 20 AWG (0.2 to 0.6 mm²), for the four butt splices", "Crimping pliers for open-barrel contacts, with a die for 24 AWG (0.20 mm²) wire, for the four PH contacts", "A ruler or tape measure, to cut the tail to length", "Only if you solder the splices instead: soldering iron and solder, adhesive-lined heat shrink, and a heat gun to shrink it"]
---

The chute stepper is the NEMA 23 that drives the chute. It is the only motor on the machine with bare flying leads: the four channel steppers have their own 6-pin socket and take a bought cable. So this one lead gets built. **One per machine.**

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The motor's own leads are too thick for the connector, however long they are.</b> They are <b>20 AWG (0.52 mm²)</b> (UL1007 on the motor drawing) and a JST PH contact takes 24 to 28 AWG (0.08 to 0.20 mm²), so the board end of this lead is always a short 24 AWG (0.20 mm²) tail spliced onto them. Length decides how long that tail is, not whether you need one. A butt splice made for 24 to 20 AWG (0.2 to 0.6 mm²) holds both sizes, so the splice is crimped.</p>
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

**Position 1 is the pin on the square pad.** A PH housing has a small triangle moulded beside its position 1, so the PHR-4 goes on with its triangle end over that pad. A Dupont housing is not keyed and fits either way up, and nothing moulded on it tells you which end is 1, so go by the pad: the first wire goes over the square one. Turned half a turn it still goes on, with the wires in reverse order. Nothing is damaged, but the motor then turns the other way, so check the direction in the software.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/stepper-lead-pin1-end-full-22bee566ce1c.png" alt="Two rows. Top: a PHR-4 housing with cavities numbered 1 to 4 and a red triangle moulded at the left end beside cavity 1, an arrow from that end to the 4-pin board socket drawn from above, whose first pad is square and labelled A2, followed by A1, B1 and B2. Bottom: a plain 4-pin Dupont housing with no marking, beside the 2.54 mm pin row on the board, whose first pin is on a square pad labelled A2.">
  <figcaption>Position 1 is the end of the housing with the triangle, and the pin on the square pad on the board.</figcaption>
</figure>

**Positions 1 and 2 are one coil, 3 and 4 are the other.** Swapping the two wires inside a coil only reverses the direction the motor turns. Splitting a coil across the 2 and 3 boundary is what stops it working, so keep each pair together.

<figure class="harness-figure">
  <div class="diagram diagram-wide">
    <svg viewBox="0 0 930 347" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="The chute stepper lead: a 4-pin board connector on the left with positions A2, A1, B1 and B2, four wires running straight across to the NEMA 23's four bare flying leads on the right, with a splice marked in the middle where the thin tail you add meets the motor's thicker leads">
      <text x="0" y="20" font-size="17" font-weight="700" fill="var(--ink)">The chute stepper lead</text>
      <text x="0" y="41" font-size="12" fill="var(--muted)">basically board v1.3 to the chute motor. One per machine, and the only stepper lead you splice.</text>
      <line x1="0" y1="64" x2="26" y2="64" stroke="#1a1a1a" stroke-width="2.6" stroke-linecap="round"/>
      <text x="34" y="68" font-size="11" fill="var(--muted)">black</text>
      <line x1="91" y1="64" x2="117" y2="64" stroke="#1f8a45" stroke-width="2.6" stroke-linecap="round"/>
      <text x="125" y="68" font-size="11" fill="var(--muted)">green</text>
      <line x1="182" y1="64" x2="208" y2="64" stroke="#d01012" stroke-width="2.6" stroke-linecap="round"/>
      <text x="216" y="68" font-size="11" fill="var(--muted)">red</text>
      <line x1="259" y1="64" x2="285" y2="64" stroke="#1f63c8" stroke-width="2.6" stroke-linecap="round"/>
      <text x="293" y="68" font-size="11" fill="var(--muted)">blue</text>
      <rect x="0" y="92" width="250" height="203" rx="5" fill="var(--bg)" stroke="var(--ink)" stroke-width="1.5"/>
      <text x="14" y="116" font-size="13" font-weight="700" fill="var(--ink)">basically board v1.3</text>
      <text x="14" y="134" font-size="11" fill="var(--muted)">J23, or J24 beside it</text>
      <circle cx="250" cy="164" r="4.5" fill="var(--ink)"/>
      <text x="236" y="168" font-size="11" font-weight="700" fill="var(--muted)" text-anchor="end">1</text>
      <text x="218" y="168" font-size="12" font-weight="600" fill="var(--ink)" text-anchor="end">A2</text>
      <circle cx="250" cy="199" r="4.5" fill="var(--ink)"/>
      <text x="236" y="203" font-size="11" font-weight="700" fill="var(--muted)" text-anchor="end">2</text>
      <text x="218" y="203" font-size="12" font-weight="600" fill="var(--ink)" text-anchor="end">A1</text>
      <circle cx="250" cy="234" r="4.5" fill="var(--ink)"/>
      <text x="236" y="238" font-size="11" font-weight="700" fill="var(--muted)" text-anchor="end">3</text>
      <text x="218" y="238" font-size="12" font-weight="600" fill="var(--ink)" text-anchor="end">B1</text>
      <circle cx="250" cy="269" r="4.5" fill="var(--ink)"/>
      <text x="236" y="273" font-size="11" font-weight="700" fill="var(--muted)" text-anchor="end">4</text>
      <text x="218" y="273" font-size="12" font-weight="600" fill="var(--ink)" text-anchor="end">B2</text>
      <path d="M 132 164 h 10 v 35 h -10" fill="none" stroke="var(--muted)" stroke-width="1.4"/>
      <text x="148" y="185.5" font-size="11" font-weight="600" fill="var(--muted)">coil A</text>
      <path d="M 132 234 h 10 v 35 h -10" fill="none" stroke="var(--muted)" stroke-width="1.4"/>
      <text x="148" y="255.5" font-size="11" font-weight="600" fill="var(--muted)">coil B</text>
      <rect x="680" y="92" width="250" height="203" rx="5" fill="var(--bg)" stroke="var(--ink)" stroke-width="1.5"/>
      <text x="694" y="116" font-size="13" font-weight="700" fill="var(--ink)">NEMA 23 motor</text>
      <text x="694" y="134" font-size="11" fill="var(--muted)">four bare flying leads</text>
      <circle cx="680" cy="164" r="4.5" fill="var(--ink)"/>
      <text x="694" y="168" font-size="11" font-weight="700" fill="var(--muted)"></text>
      <text x="712" y="168" font-size="12" font-weight="600" fill="var(--ink)">coil A</text>
      <circle cx="680" cy="199" r="4.5" fill="var(--ink)"/>
      <text x="694" y="203" font-size="11" font-weight="700" fill="var(--muted)"></text>
      <text x="712" y="203" font-size="12" font-weight="600" fill="var(--ink)">coil A</text>
      <circle cx="680" cy="234" r="4.5" fill="var(--ink)"/>
      <text x="694" y="238" font-size="11" font-weight="700" fill="var(--muted)"></text>
      <text x="712" y="238" font-size="12" font-weight="600" fill="var(--ink)">coil B</text>
      <circle cx="680" cy="269" r="4.5" fill="var(--ink)"/>
      <text x="694" y="273" font-size="11" font-weight="700" fill="var(--muted)"></text>
      <text x="712" y="273" font-size="12" font-weight="600" fill="var(--ink)">coil B</text>
      <line x1="256" y1="164" x2="412" y2="164" stroke="#1a1a1a" stroke-width="2.6" stroke-linecap="round"/>
      <line x1="468" y1="164" x2="674" y2="164" stroke="#1a1a1a" stroke-width="5.4" stroke-linecap="round"/>
      <rect x="412" y="156" width="56" height="16" rx="8" fill="var(--surface)" stroke="var(--muted)" stroke-width="1.5"/>
      <line x1="256" y1="199" x2="412" y2="199" stroke="#1f8a45" stroke-width="2.6" stroke-linecap="round"/>
      <line x1="468" y1="199" x2="674" y2="199" stroke="#1f8a45" stroke-width="5.4" stroke-linecap="round"/>
      <rect x="412" y="191" width="56" height="16" rx="8" fill="var(--surface)" stroke="var(--muted)" stroke-width="1.5"/>
      <line x1="256" y1="234" x2="412" y2="234" stroke="#d01012" stroke-width="2.6" stroke-linecap="round"/>
      <line x1="468" y1="234" x2="674" y2="234" stroke="#d01012" stroke-width="5.4" stroke-linecap="round"/>
      <rect x="412" y="226" width="56" height="16" rx="8" fill="var(--surface)" stroke="var(--muted)" stroke-width="1.5"/>
      <line x1="256" y1="269" x2="412" y2="269" stroke="#1f63c8" stroke-width="2.6" stroke-linecap="round"/>
      <line x1="468" y1="269" x2="674" y2="269" stroke="#1f63c8" stroke-width="5.4" stroke-linecap="round"/>
      <rect x="412" y="261" width="56" height="16" rx="8" fill="var(--surface)" stroke="var(--muted)" stroke-width="1.5"/>
      <text x="440" y="126" font-size="12" font-weight="700" fill="var(--ink)" text-anchor="middle">splice</text>
      <text x="440" y="142" font-size="11" fill="var(--muted)" text-anchor="middle">crimped butt splice, 24 to 20 AWG (0.2 to 0.6 mm²)</text>
      <text x="345.0" y="301" font-size="11" fill="var(--muted)" text-anchor="middle">24 AWG (0.20 mm²) tail you add</text>
      <text x="570.0" y="301" font-size="11" fill="var(--muted)" text-anchor="middle">the motor's own 20 AWG (0.52 mm²) leads</text>
      <text x="465" y="331" font-size="12" fill="var(--muted)" text-anchor="middle">The motor's leads are too thick for a JST-PH contact, so the last stretch to the board is a thinner tail. Find the coil pairs with a meter first.</text>
    </svg>
  </div>  <figcaption>One lead end to end, with the splice that makes it the only stepper lead you build.</figcaption>
</figure>

The full pinout and the board-side footprint are on the [wire harness]({{ '/hardware/electronics/wire-harness/#21--stepper-pinout-and-polarity' | relative_url }}) page.

## Find the coils first

The motor's four leads are coloured, and the colours do not tell you which pair is which coil on every motor.

<ol class="numbered-steps">
  <li>Set the <a href="{{ '/hardware/helpers/multimeter/' | relative_url }}#resistance-for-finding-a-steppers-coils">multimeter to resistance</a>, the <b>&Omega;</b> position on its dial.</li>
  <li>Put a probe on two of the four leads. <b>A pair from the same coil reads well under an ohm</b> on this motor, 0.65 &Omega; at the winding plus whatever your probe leads add. Two leads from different coils read open circuit, which most meters show as <code>OL</code> or a lone <code>1</code>.</li>
  <li>Work through the leads until you have both pairs. Write down which colour goes with which.</li>
</ol>

## Build it

<ol class="numbered-steps">
  <li>Hold the motor where it will sit and see how far its own leads get you. They come out of the motor at 300 to 500 mm depending on the batch, and the harness notes put the finished lead at about 1 m (40 in).</li>
  <li>Cut four pieces of 24 AWG (0.20 mm²) wire, one in each colour of the motor's four leads, long enough to make the length up and <b>at least 100 mm</b> even when the motor's own leads already reach.</li>
  <li>Splice each one onto the motor lead of the same colour with a 24 to 20 AWG (0.2 to 0.6 mm²) butt splice, as under <b>Splicing a tail onto a motor lead</b>, below. Or solder them, as under <b>Or solder the splices</b>.</li>
  <li>Crimp a PH contact onto the free end of each of the four tails, as under <b>Crimping a PH contact</b>, below.</li>
  <li>Push the contacts into the housing until each one clicks: <b>one coil into positions 1 and 2, the other coil into positions 3 and 4</b>. Which coil goes in which pair does not matter. Nor does which lead of a pair goes in which position: that only reverses the direction the motor turns, and the direction is set in the software.</li>
</ol>

## Splicing a tail onto a motor lead

Four joints, one per lead, each in its own butt splice. A butt splice is a clear tube with a metal barrel inside that you crimp onto a wire at each end. Use the 24 to 20 AWG (0.2 to 0.6 mm²) one in the parts list: a splice made for thicker wire does not grip a 24 AWG (0.20 mm²) tail, and one made for thinner wire does not take the motor's leads.

<ol class="numbered-steps">
  <li>Strip the end of the tail and the end of the motor lead. Hold each wire against the splice to judge how much insulation to take off, then check it in the next step and adjust.</li>
  <li>Push the motor lead into one end of the splice until it stops. <b>The insulation should sit against the end of the metal barrel, and the bare strands should reach the stop in the middle.</b> The plastic is clear, so you can see both through it. Strip a little more or less until they do.</li>
  <li>Crimp that end in the die of the insulated-terminal pliers marked for 24 to 20 AWG (0.2 to 0.6 mm²), with the metal barrel in the die. Choose the die by the size marked on it, not by its colour.</li>
  <li>Push the tail into the other end in the same way and crimp that end.</li>
  <li>Pull on both wires to check the joint holds.</li>
  <li>Make the other three joints the same way, <b>staggered along the cable</b> so no two sit side by side.</li>
</ol>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-stepper-lead-butt-splice-diagram-full-03ca94566783.png" alt="Four panels. 1: the stripped end of a motor lead, 20 AWG (0.52 mm²), and of a 24 AWG (0.20 mm²) tail. 2: one wire in each end of a clear butt splice, the insulation against the barrel and the stripped ends reaching the wire stop in the centre. 3: the splice between the two jaws of a crimping die marked 24 to 20 AWG (0.2 to 0.6 mm²), crimped one end and then the other. 4: four wires, black, green, red and blue, each with its splice at a different distance along the cable.">
  <figcaption>Strip, one wire in each end, crimp each end in the marked die, then repeat staggered.</figcaption>
</figure>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>This is not the die for the PH contacts.</b> Pliers made for open-barrel contacts, the kind that crimp the PH and Dupont contacts, do not close this splice properly. The PH contacts take their own die, below.</p>
</div>

## Or solder the splices

You can solder each joint instead of crimping it. The harness spec is a solder splice with adhesive-lined heat shrink, one sleeve per conductor and one over all four, and no twist-and-tape. You then need the soldering iron, solder, heat shrink and heat gun from the tools list, and you do not need the butt splices.

<ol class="numbered-steps">
  <li>Slide a piece of adhesive-lined heat shrink onto the 24 AWG (0.20 mm²) tail, well back from the end. It cannot go on once the joint is soldered.</li>
  <li>Strip the same length off the end of the tail and off the end of the motor lead.</li>
  <li>Lay the two bare ends side by side, overlapping, and solder them together until the solder has run through both sets of strands.</li>
  <li>Slide the heat shrink over the joint, so it covers the bare metal and a little insulation either side, and shrink it with the heat gun until it grips the wire.</li>
  <li>Make the other three joints the same way, <b>staggered along the cable</b> so no two sit side by side.</li>
  <li>Slide one more piece of heat shrink over all four and shrink it, so the four leave the motor as one cable.</li>
</ol>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-stepper-lead-splice-diagram-full-7394cb74d6af.png" alt="Four panels. 1: a 24 AWG tail with a piece of heat shrink already slid on, facing the stripped end of the motor's thicker lead. 2: the two bare ends overlapped side by side and covered in solder. 3: the heat shrink slid over the joint. 4: four wires, black, green, red and blue, each with its own joint at a different distance along the cable, and one more sleeve over all four.">
  <figcaption>Heat shrink on first, solder, shrink, then repeat staggered and sleeve the four.</figcaption>
</figure>

## Crimping a PH contact

A PH contact takes 24 to 28 AWG (0.08 to 0.20 mm²) wire only, which is why it goes on the tail and not on the motor's own leads.

<ol class="numbered-steps">
  <li>Strip about 2 mm off the end of the tail.</li>
  <li>Close the contact's inner wings on the bare strands and its outer wings on the insulation, in the die of the crimping pliers marked for 24 AWG (0.20 mm²) wire.</li>
  <li>Pull on the wire to check it holds, then push the contact into the housing from the back, with its lance facing the slot in the housing, until it clicks.</li>
</ol>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/ph-contact-crimp-steps-full-985dd5dc580a.png" alt="Three stages: a wire with about 2 mm of bare strands; a contact crimped on, its outer wings on the insulation and its inner wings on the bare strands; the contact pushed into the back of a housing until it clicks.">
  <figcaption>Strip, crimp, push in until it clicks.</figcaption>
</figure>

Choose the die by the size marked on it, not by its colour.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Check the coils again on the finished lead.</b> Meter across positions 1 and 2, then across 3 and 4. Both read the same fraction of an ohm you measured at the leads. If either reads open circuit, a contact has gone into the wrong position: pull the two out and swap them. A motor wired across the coils buzzes and barely turns.</p>
</div>

## Either socket on the board takes it

The board gives the chute two sockets side by side and they are wired to the same four nets, so the lead can end in either one:

<dl class="spec-list">
  <dt><code>J23</code></dt><dd>JST-PH 4-pin, the housing in the parts list above.</dd>
  <dt><code>J24</code></dt><dd>A row of 2.54 mm pins, which takes a 4-pin Dupont housing instead. Use this one if you have Dupont housings and no PH contacts.</dd>
</dl>

Both carry `A2`, `A1`, `B1`, `B2` on positions 1 to 4, and the board prints the coil name beside each pin, so the names can be read off the board rather than counted.

## The finished result

One lead: the motor with a 24 AWG (0.20 mm²) tail spliced onto its four thick leads, ending in a 4-pin PHR-4 with each coil on one pair of positions.

<div class="img-placeholder">Image coming: the finished lead, the four splices staggered along the cable and the PHR-4 at the end of the thin tail, with the motor in frame at the other end</div>

## Reference

The vendor drawing for this lead, its bill of materials and its downloads are on the [WireViz
drawings]({{ '/hardware/parts/harness-order/#chute-stepper' | relative_url }}) page. It shows the same lead in the form a cable supplier quotes from.

## Where it goes

Onto the chute socket at [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 2, which is also where the socket decides which motor the software drives.
