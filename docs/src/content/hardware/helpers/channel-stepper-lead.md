---
layout: default
title: Make the channel stepper leads
type: how-to
section: hardware
slug: helper-channel-stepper-lead
kicker: Helpers — Channel stepper leads
lede: The four leads from the control board to the c-channel motors. Four per machine, all identical, each made by replacing the Dupont plug on the motor's own lead with a 4-pin JST connector.
permalink: /hardware/helpers/channel-stepper-lead/
author: effreek
contributors: [daddyosbricksbill, spencer, brickcyclealice, barthel]
last_verified: 2026-10-01
parts_needed:
  - part: jst-phr-4
    qty: 4
  - part: jst-sph-002t
    qty: 16
tools_needed: ["Multimeter, to check the finished lead", "Side cutters, to cut the Dupont housing off", "Wire strippers, for 26 AWG (0.13 mm²) wire", "Crimping pliers for open-barrel contacts, with a die for 24 AWG (0.20 mm²) wire"]
---

These are `S1` to `S4` on the [harness drawings]({{ '/hardware/parts/harness-order/#channel-stepper' | relative_url }}), one for each of the four c-channel motors. **Four per machine**, all identical. The crossover has been built on a motor's own lead by swapping the two middle contacts in its Dupont plug; this page makes the same lead with a PH housing instead of the plug.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The lead that comes in the box with the motor is not usable as it comes.</b> Two of its four conductors are in the wrong order for this board, so the driver drives half of one coil against half of the other and the motor buzzes and barely turns. It also ends in a Dupont housing, which does fit the 2.54 mm pins beside each stepper socket, so it looks right. Pull a Dupont contact sideways and its spring lifts off the pin: resistance rises, the joint heats, and it gets worse from there. Two have cooked on running machines.</p>
</div>

**Both faults are in that one housing.** So the fix is to replace it: cut the plug off the motor's own lead, crimp a contact onto each of the four wires and load them into a 4-pin PHR-4 in the order below. The motor end of the lead is already right and stays as it is. **Per lead: one `jst-phr-4` and four `jst-sph-002t` contacts**, so sixteen contacts for the machine, and a crimp tool for open-barrel contacts. You do not need a ready-made cable or a PHR-6.

## The two ends

<dl class="spec-list">
  <dt>Board end</dt><dd>JST <b>PH</b> housing, 4-pin (PHR-4), 2.0 mm pitch, into <code>J27</code>, <code>J31</code>, <code>J35</code> or <code>J39</code>. Positions 1 to 4 are <code>A2</code>, <code>A1</code>, <code>B1</code>, <code>B2</code>.</dd>
  <dt>Motor end</dt><dd>The 6-pin JST <b>PH</b> housing the motor's lead already ends in, plugged into the socket on the motor can. Only four of the six positions carry a contact. Leave it alone.</dd>
  <dt>Wire</dt><dd>The motor's own lead, four conductors of 26 AWG (0.13 mm²). The harness drawing says 1 m; see the note on length below.</dd>
</dl>

### The crossover

The board and the motor do not use the same positions, so this cable is not straight through.
Board 1 goes to motor 1, 2 to 4, 3 to 3 and 4 to 6, which is why two wires cross in the drawing
under <b>Re-house the lead</b>, below. Motor positions 2 and 5 stay empty.

**On the motor, pin 1 is the right end of the socket** when you look at the motor from the shaft end with the socket at the top edge. Reading left to right the positions are 6, empty, 4, 3, empty, 1. Positions 1 and 4 are one coil and 3 and 6 are the other, whatever colour the wires are.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/channel-stepper-lead-motor-pin1-top-full-c61ff3727a76.png" alt="The NEMA 17 seen from the shaft end, with its 6-position socket on the top edge. The positions are numbered 6 to 1 from left to right with pin 1 at the right end. Positions 1 and 4 are filled in blue as coil A, positions 3 and 6 in green as coil B, and positions 2 and 5 are empty. A list beside it gives the board net for each position: A2, empty, B1, A1, empty, B2.">
  <figcaption>The motor's socket, with the socket at the top. Position 1 is at the right, 2 and 5 are empty.</figcaption>
</figure>

**Positions 1 and 2 on the board are one coil, 3 and 4 are the other.** Keeping each pair together is what matters. Swapping the two wires inside a coil only reverses which way the motor turns, and the direction is set in the software.

## Re-house the lead the motor came with

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Check the wire diagram that came with your motor before you cut anything.</b> StepperOnline supplies a small wire diagram with the motor that names the wire in every position of the 6-pin housing, with its colour and its coil (A+, A-, B+, B-). The figure below is drawn from the datasheet for the 17HE15-1504S, and the wire colours and the position 1 end have not been checked against a real motor. Lay the motor's own drawing next to this figure: positions 1 and 4 must be the same coil, and positions 3 and 6 the other. If your drawing differs, follow it. A photo of that drawing from a real motor is still missing from this page, so if you have one, please post it in the Discord.</p>
</div>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/channel-stepper-lead-rehouse-datasheet-style-png-full-54ea4face49d.png" alt="A line drawing in the style of the StepperOnline cable drawing. On the left the 6-pin PHR-6 housing at the motor end, positions 6 at the top down to 1 at the bottom, with the labels RED B-, empty, BLU A-, GRN B+, empty, BLK A+ beside positions 6, 5, 4, 3, 2 and 1. On the right the 4-pin PHR-4 at the board end, positions 4 at the top down to 1 at the bottom, labelled coil B from motor 6, coil B from motor 3, coil A from motor 4 and coil A from motor 1. Four wires join them: motor 6 to PHR-4 position 4, motor 4 to position 2, motor 3 to position 3 and motor 1 to position 1, so the wires from motor positions 4 and 3 cross."">
  <figcaption>Follow the position, not the colour. Each wire goes from the motor-end position on the left to the PHR-4 position on the right.</figcaption>
</figure>

**Position 1 is the end that lands on pin 1.** Both housings are keyed and only plug in one way round, so the end that goes over pin 1 of the socket is position 1 and the positions count away from it. On the motor that is the right end of the socket in the figure above, and on the board it is the square pad. The wire colours on the drawing are an example: your wires may be other colours, and the drawing still works because each wire is named by the motor-end position it sits in.

<ol class="numbered-steps">
  <li>Look at the back of the 6-pin housing at the motor end while it is still plugged into the motor, with the shaft towards you: position 1 is the right-hand end and the positions count 1 to 6 from right to left. Four wires sit in positions 1, 3, 4 and 6, and 2 and 5 are empty. Write down which colour is in which position, or tag each wire with a bit of tape marked with its position if two look alike.</li>
  <li>Cut the Dupont housing off close to the housing, so the cable keeps its length.</li>
  <li>Strip and crimp a contact onto each conductor, as under <b>Crimping a PH contact</b>, below. Practise on a scrap first, the contacts are small and easy to spoil.</li>
  <li>Load the <code>PHR-4</code> from the back, counting from the end that goes over the square pad of the board socket (offer the empty housing to the socket to see which end that is): the wire from motor position 1 into position 1, the wire from motor position 4 into 2, the wire from motor position 3 into 3 and the wire from motor position 6 into 4. Each contact goes in with its lance facing the slot in the housing, and clicks when it is home.</li>
  <li>Pull gently on each wire, then meter across <code>PHR-4</code> positions 1 and 2 and across 3 and 4 with the motor plugged in. Both read a couple of ohms, 2.3 &Omega; on the motor in the parts list, and across the two pairs is open circuit. If either pair reads open, two contacts are in the wrong places.</li>
</ol>

**If you cannot tell which wire was in which position,** meter the wires <a href="{{ '/hardware/helpers/multimeter/' | relative_url }}#resistance-for-finding-a-steppers-coils">with the meter</a> instead. Two of the four read a couple of ohms between them and open circuit to the other two: those two are one coil. Put one coil in <code>PHR-4</code> positions 1 and 2 and the other in 3 and 4. Either order inside a pair works, it only reverses which way the motor turns, and the direction is set in the software.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/channel-stepper-lead-rehouse-pin1-keyed-diagram-full-png-full-21b2a19c1bf3.png" alt="Two rows. Top: the motor with its own lead running to a Dupont housing, a dashed line marking where to cut close to the housing, the housing marked as scrap. Bottom: the same lead with a crimped contact on each of its four wires, loaded into a 4-pin PHR-4 with positions 1 and 2 bracketed as coil A and 3 and 4 as coil B.">
  <figcaption>Cut the Dupont housing off, crimp a contact on each wire, load the PHR-4 one coil at a time.</figcaption>
</figure>

The Dupont housing you cut off is scrap.

## Crimping a PH contact

A PH contact takes 24 to 28 AWG (0.08 to 0.20 mm²) wire only.

<ol class="numbered-steps">
  <li>Strip about 2 mm off the end of the wire.</li>
  <li>Close the contact's inner wings on the bare strands and its outer wings on the insulation, in the die of the crimping pliers marked for 24 AWG (0.20 mm²) wire.</li>
  <li>Pull on the wire to check it holds, then push the contact into the housing from the back, with its lance facing the slot in the housing, until it clicks.</li>
</ol>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/ph-contact-crimp-steps-full-985dd5dc580a.png" alt="Three stages: a wire with about 2 mm of bare strands; a contact crimped on, its outer wings on the insulation and its inner wings on the bare strands; the contact pushed into the back of a housing until it clicks.">
  <figcaption>Strip, crimp, push in until it clicks.</figcaption>
</figure>

Choose the die by the size marked on it, not by its colour.

## How long

<div class="callout">
  <p><b>The length is not measured.</b> The harness drawing says 1 m, which is also what the motors ship with and the length you keep. It was set while the c-channel positions were still moving, so check the run on your own frame before you cut the plug off.</p>
</div>

Whatever the length, **anchor the cable above the connector**. Zip-tie it to the frame a short way back from the plug and leave a service loop, so that nothing hanging off the cable can lever the housing sideways.

## The finished result

Four leads, each with a 4-pin PHR-4 at the board end and a 6-pin PHR-6 at the motor end with two of its six positions empty.

<div class="img-placeholder">Image coming: one finished lead laid out straight, both housings in the frame, the motor end close enough to show the two empty positions</div>

## Where it goes

Onto the four channel stepper sockets at [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 2, which is also where the socket decides which motor the software drives.

## Reference

The vendor drawing for this cable, its bill of materials and its downloads are on the [WireViz
drawings]({{ '/hardware/parts/harness-order/#channel-stepper' | relative_url }}) page. It shows the same lead in the form a cable supplier quotes from.
