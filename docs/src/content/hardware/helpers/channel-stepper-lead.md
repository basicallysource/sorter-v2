---
layout: default
title: Make the channel stepper leads (S1 to S4)
type: how-to
section: hardware
slug: helper-channel-stepper-lead
kicker: Helpers — Channel stepper leads (S1 to S4)
lede: The four leads (S1 to S4) from the control board to the c-channel motors. Four per machine, all identical, each made by replacing the Dupont plug on the motor's own lead with a 4-pin JST connector.
permalink: /hardware/helpers/channel-stepper-lead/
author: effreek
contributors: [daddyosbricksbill, spencer, brickcyclealice, barthel]
last_verified: 2026-10-01
parts_needed:
  - part: jst-phr-4
    qty: 4
  - part: jst-sph-002t
    qty: 20
  - part: sleeving-braided-6mm
    qty: 1
    note: Optional. 1 m (39 in) per lead, 4 m (13 ft) for the four.
tools_needed: ["Multimeter, to check the finished lead", "Side cutters, to cut the Dupont housing off", "Wire strippers, for 26 AWG (0.13 mm²) wire", "Crimping pliers for open-barrel contacts, with a die for 24 AWG (0.20 mm²) wire", "Optional, for the sleeving: scissors and tape, or a hot knife"]
---

These are the channel stepper leads (`S1` to `S4`) on the [harness drawings]({{ '/hardware/parts/harness-order/#channel-stepper' | relative_url }}), one for each of the four c-channel motors. **Four per machine**, all identical. The crossover has been built on a motor's own lead by swapping the two middle contacts in its Dupont plug; this page makes the same lead with a PH housing instead of the plug.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The lead that comes in the box with the motor is not usable as it comes.</b> Two of its four conductors are in the wrong order for this board, so the driver drives half of one coil against half of the other and the motor buzzes and barely turns. It also ends in a Dupont housing, which does fit the 2.54 mm (0.1 in) pins beside each stepper socket, so it looks right. Pull a Dupont contact sideways and its spring lifts off the pin: resistance rises, the joint heats, and it gets worse from there. Two have cooked on running machines.</p>
</div>

**Both faults are in that one housing.** So the fix is to replace it: cut the plug off the motor's own lead, crimp a contact onto each of the four wires and load them into a 4-pin PHR-4 in the order below. The motor end of the lead is already right and stays as it is. **Per lead: one `jst-phr-4` and four `jst-sph-002t` contacts**, so sixteen contacts for the machine. The parts list says twenty: four spares, because the first crimps on a contact this small are easy to spoil. You also need a crimp tool for open-barrel contacts. You do not need a ready-made cable or a PHR-6.

## The two ends

<dl class="spec-list">
  <dt>Board end</dt><dd>JST <b>PH</b> housing, 4-pin (PHR-4), 2.0 mm (0.079 in) pitch, into <code>J27</code>, <code>J31</code>, <code>J35</code> or <code>J39</code>. Positions 1 to 4 are <code>A2</code>, <code>A1</code>, <code>B1</code>, <code>B2</code>.</dd>
  <dt>Motor end</dt><dd>The 6-pin JST <b>PH</b> housing the motor's lead already ends in, plugged into the socket on the motor can. Only four of the six positions carry a contact. Leave it alone.</dd>
  <dt>Wire</dt><dd>The motor's own lead, four conductors of 26 AWG (0.13 mm²). The harness drawing says 1 m (39 in); see the note on length below.</dd>
</dl>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/stepper-lead-pin1-plug-shape-full-ac4c5740e493.png" alt="Two rows. Top: a PHR-4 housing drawn in the datasheet plug shape (flange at the wire side, a lane at each end, a window between) with positions numbered 1 to 4 and a note that it is keyed and plugs in one way round only, an arrow from the position 1 end to the 4-pin board socket drawn from above, whose first pad is square and labelled A2, followed by A1, B1 and B2. Bottom: a plain 4-pin Dupont housing with no marking, beside the 2.54 mm pin row on the board, whose first pin is on a square pad labelled A2.">
  <figcaption>Position 1 is the end of the housing that goes over the pin on the square pad on the board.</figcaption>
</figure>

### The crossover

The board and the motor do not use the same positions, so this cable is not straight through.
Board 1 goes to motor 1, 2 to 4, 3 to 3 and 4 to 6, which is why two wires cross in the drawing
under <b>Re-house the lead</b>, below. Motor positions 2 and 5 stay empty.

**On the motor, pin 1 is the right end of the socket** when you look at the motor from the shaft end with the socket at the top edge. Reading left to right the positions are 6, empty, 4, 3, empty, 1. Positions 1 and 4 are one coil and 3 and 6 are the other, whatever colour the wires are.

**Positions 1 and 2 on the board are one coil, 3 and 4 are the other.** Keeping each pair together is what matters. Swapping the two wires inside a coil only reverses which way the motor turns, and the direction is set in the software.

## Re-house the lead the motor came with

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Check the wire diagram that came with your motor before you cut anything.</b> StepperOnline supplies a small wire diagram with the motor that names the wire in every position of the 6-pin housing, with its colour and its coil (A+, A-, B+, B-). Lay the motor's own drawing next to the figure below: positions 1 and 4 must be the same coil, and positions 3 and 6 the other. If your drawing differs, follow it.</p>
</div>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/channel-stepper-lead-rehouse-plug-shape-both-png-full-afd12ce6e219.png" alt="A line drawing in the style of the StepperOnline cable drawing. On the left the 6-pin PHR-6 housing at the motor end, drawn to the shape in that drawing: a lane down the mating side, two blocks with a rectangular window between them, and a flange on the wire side with chamfered corners. Positions 6 at the top down to 1 at the bottom are labelled RED B-, empty, BLU A-, GRN B+, empty and BLK A+. On the right the 4-pin PHR-4 at the board end, the same outline mirrored and scaled to four positions with its flange on the wire side, positions 4 at the top down to 1 at the bottom, labelled coil B from motor 6, coil B from motor 3, coil A from motor 4 and coil A from motor 1. Four wires join them: motor 6 to PHR-4 position 4, motor 4 to position 2, motor 3 to position 3 and motor 1 to position 1, so the wires from motor positions 4 and 3 cross."">
  <figcaption>Follow the position, not the colour. Each wire goes from the motor-end position on the left to the PHR-4 position on the right.</figcaption>
</figure>

**Position 1 is the end that lands on pin 1.** Both housings are keyed and only plug in one way round, so the end that goes over pin 1 of the socket is position 1 and the positions count away from it. On the motor it is the end described under <b>The crossover</b>, above, and on the board it is the square pad. The wire colours on the drawing are an example: your wires may be other colours, and the drawing still works because each wire is named by the motor-end position it sits in.

<ol class="numbered-steps">
  <li>Look at the back of the 6-pin housing at the motor end while it is still plugged into the motor, with the shaft towards you: position 1 is the right-hand end and the positions count 1 to 6 from right to left. Four wires sit in positions 1, 3, 4 and 6, and 2 and 5 are empty. Write down which colour is in which position, or tag each wire with a bit of tape marked with its position if two look alike.</li>
  <li>Cut the Dupont housing off, close to it, so the cable keeps its length.</li>
  <li><b>Optional:</b> if you will sleeve the lead, slide a 1 m (39 in) length of braided sleeving over the four wires from the cut end now, before you load the 4-pin housing. The 6-pin housing on the other end is too big for it to go over. Leave it bunched up on the cable for now; <a href="#sleeving-optional">Sleeving (optional)</a> says how to cut and finish it.</li>
  <li>Strip about 2 mm (0.08 in) off each conductor and crimp a contact onto it, in the die of the open-barrel crimping pliers marked for 24 AWG (0.20 mm²) wire. The motor's own wire is 26 AWG (0.13 mm²), which a PH contact takes (24 to 28 AWG), and the 24 AWG die is the one to use. Pull on each wire to check it holds. How to crimp a contact, with a picture, is at [Crimping connectors]({{ '/hardware/helpers/crimping/' | relative_url }}). Practise on a scrap first, the contacts are small and easy to spoil.</li>
  <li>Load the <code>PHR-4</code> from the back, counting from the end that goes over the square pad of the board socket (offer the empty housing to the socket to see which end that is): the wire from motor position 1 into position 1, the wire from motor position 4 into 2, the wire from motor position 3 into 3 and the wire from motor position 6 into 4. Push each contact in until it clicks.</li>
  <li>Pull gently on each wire, then meter across <code>PHR-4</code> positions 1 and 2 and across 3 and 4 with the motor plugged in. Both read a couple of ohms, 2.3 &Omega; on the motor in the parts list, and across the two pairs is open circuit. If either pair reads open, two contacts are in the wrong places.</li>
</ol>

## Sleeving (optional)

<div class="callout">
  <p><b>You can skip this and the lead works the same.</b> The sleeving is on the parts list as optional. It keeps the four wires of each lead together as one tidy cable, and it protects them where the lead runs along the frame and past the moving parts. The parts list sells a braided sleeving for it.</p>
</div>

**Where:** over the four wires of each lead, from just behind the 6-pin motor housing to just short of where the wires fan out into the PHR-4. One metre (39 in) per lead, four metres (13 ft) for the machine.

**How:**

<ol class="numbered-steps">
  <li>Push the braid together lengthwise to open it: it widens as it shortens. Feed the four wires into it together, so none of them is left outside.</li>
  <li>Cut it to length with a hot knife or a soldering iron with a blade tip, so the cut melts shut. Plain scissors leave the braid fraying. With no hot tool, wrap a turn of tape around the braid where you will cut, cut through the middle of the tape with scissors, and leave the tape on.</li>
  <li>Stop the sleeving 5 to 10 mm (0.2 to 0.4 in) short of the PHR-4 and short of the 6-pin housing, so the crimped contacts and the housing can flex and the sleeving never crowds into a housing.</li>
  <li>Hold each end with a small piece of heat shrink or a turn of tape, so that the braid cannot creep back along the wires.</li>
</ol>

**Leave the sleeving loose enough to bend.** The anchor under <b>How long</b>, below, goes on over the sleeving: pull the tie tight enough to hold, but not so tight that it crushes the braid.

## How long

<div class="callout">
  <p><b>The length is not measured.</b> The harness drawing says 1 m (39 in), which is also what the motors ship with and the length you keep. It was set while the c-channel positions were still moving, so check the run on your own frame before you cut the plug off.</p>
</div>

Whatever the length, **anchor the cable above the connector**. Zip-tie it to the frame a short way back from the plug and leave a service loop, so that nothing hanging off the cable can lever the housing sideways.

## The finished result

Four leads (`S1` to `S4`), each with a 4-pin PHR-4 at the board end and a 6-pin PHR-6 at the motor end with two of its six positions empty.

<div class="img-placeholder">Image coming: one finished lead laid out straight, both housings in the frame, the motor end close enough to show the two empty positions</div>

## Where it goes

Onto the four channel stepper sockets at [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 2, which is also where the socket decides which motor the software drives.

## Reference

The vendor drawing for this cable (`S1` to `S4`), its bill of materials and its downloads are on the [WireViz
drawings]({{ '/hardware/parts/harness-order/#channel-stepper' | relative_url }}) page. It shows the same lead in the form a cable supplier quotes from.
