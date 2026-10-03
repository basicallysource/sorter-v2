---
layout: default
title: Make your own PSU output pigtail (PJ1 to PJ3)
type: how-to
section: hardware
slug: helper-psu-pigtail
kicker: Helpers — PSU output pigtail (PJ1 to PJ3)
lede: Build one of the three DC output pigtails (PJ1 to PJ3) for the PSU box, a panel-mount barrel jack with a crimp fork terminal on each of its two leads.
permalink: /hardware/helpers/psu-pigtail/
author: effreek
contributors: [brickcyclealice]
last_verified: 2026-07-12
og_image: https://assets.basically.website/sorter-docs/harness-psu-pigtail-built-w1600-59554dc6b189.jpg
parts_needed:
  - part: dc-jack-5521-panel
    qty: 3
  - part: terminal-fork-m35
    qty: 8
tools_needed: ["Wire strippers, for 18 AWG (0.82 mm²) wire", "Ratcheting crimping pliers with a die for 22 to 16 AWG (0.33 to 1.3 mm²) insulated terminals, for the fork terminals", Multimeter]
---

The PSU box has three DC outputs. Each one is a short pigtail (`PJ1` to `PJ3`): a panel-mount barrel jack at one end, a crimp fork terminal on each of its two leads at the other. **Build three**, one for each 24 V load: the basically board, the USB hub and the Orange Pi buck. All three are the same, so it does not matter which one goes to which load. Three need six fork terminals; the list has eight, two for a crimp that goes wrong. More on crimping is at [Crimping connectors]({{ '/hardware/helpers/crimping/' | relative_url }}).

<div class="callout">
  <p><b>Buy the jacks with their leads already attached.</b> This page assumes that. It crimps the terminals onto leads the jack already has. A bare jack means soldering the leads on, which this page does not cover.</p>
</div>

The jack's **2.1 mm (0.083 in) pin** is the thing to check when you buy: a 2.5 mm (0.098 in) one looks identical and does not mate.

## Build it

<ol class="numbered-steps">
  <li>Start from a panel-mount jack with its leads already attached.</li>
  <li>Work out which lead is the tip (+24 V) and which is the sleeve (ground). The jack is <b>centre-positive</b>, so red is the tip and black is the sleeve. If the leads are not red and black, set a <a href="{{ '/hardware/helpers/multimeter/' | relative_url }}#continuity-for-tracing-a-cable">multimeter to continuity</a> and hold one probe on the centre pin inside the jack: the lead that beeps is the tip.</li>
  <li>Crimp a fork terminal onto the free end of each lead, one on the tip lead and one on the sleeve lead. How is under <b>Crimping the fork terminal</b>, below.</li>
  <li>Check it. Set the multimeter to continuity. Touch one probe to the centre pin inside the jack and the other to the terminal on the tip lead: it should beep. Move the second probe to the terminal on the other lead: it should not beep. Touch the two terminals to each other: it should not beep.</li>
</ol>

If the first test does not beep, or the second does, the two terminals are on the wrong leads or a lead is broken. If the third beeps, the two leads are touching somewhere.

### Crimping the fork terminal

The crimp is the part that takes care. Do one lead at a time. The leads are 18 AWG (0.82 mm²) and the terminals are rated for 22 to 16 AWG (0.33 to 1.3 mm²) wire, so use the die of your pliers for that range.

**Do not choose the die by colour.** Colour codes on crimpers and terminals differ between makers, and some pliers have none. Go by the wire size marked on the die, in mm² or AWG, or in the tool's own table. If your die gives only mm², use the one that covers 0.82 mm².

<ol class="numbered-steps">
  <li>Hold the terminal against the lead and strip as much insulation as the metal barrel is long.</li>
  <li>Push the bare strands into the barrel until they show at its far end and the wire's own insulation reaches the terminal's plastic sleeve.</li>
  <li>Close the terminal in the die marked for 22 to 16 AWG (0.33 to 1.3 mm²). Squeeze until the ratchet releases.</li>
  <li>Pull on the terminal to check it holds.</li>
</ol>

<div class="photo-grid">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/harness-psu-pigtail-step1-stripped-w1600-7fe6beee8efc.png" alt="Stripped end of the 18 AWG (0.82 mm²) wire showing bare strands">
    <figcaption>Strip the wire back to bare strands. <cite>Photo: Jon.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/harness-psu-pigtail-step2-terminal-w1600-6302bb6e8bc4.png" alt="Stripped wire seated in the fork terminal barrel, not yet crimped">
    <figcaption>Seat the bare strands fully in the terminal barrel. <cite>Photo: Jon.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/harness-psu-pigtail-step3-crimping-w1600-0ecacc7e17fd.png" alt="Crimping the terminal in the 22 to 16 AWG (0.33 to 1.3 mm²) die of a ratcheting crimp tool">
    <figcaption>Crimp in the die marked 22 to 16 AWG (0.33 to 1.3 mm²), which suits the 18 AWG (0.82 mm²) wire. <cite>Photo: Jon.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/harness-psu-pigtail-step4-crimped-w1600-ba1c9b488c45.png" alt="The finished crimp with the insulation grip closed on the wire jacket">
    <figcaption>Finished: the grip is closed on the jacket and the wire will not pull out. <cite>Photo: Jon.</cite></figcaption>
  </figure>
</div>

## The finished result

Three pigtails (`PJ1` to `PJ3`), each a panel-mount jack with a fork terminal crimped on both of its leads.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/harness-psu-pigtail-built-w1600-59554dc6b189.jpg" alt="An assembled PSU output pigtail: a panel-mount barrel jack with red and black 18 AWG (0.82 mm²) leads, each ending in an insulated fork terminal">
  <figcaption>One finished pigtail: the jack, its red +24 V and black ground leads, and an insulated fork terminal crimped on each. <cite>Photo: Jon.</cite></figcaption>
</figure>

## Where it goes

Step 1 of the [PSU box]({{ '/hardware/electronics/installation/psu-box/' | relative_url }}): the three jacks push through the connections plate from behind, and the six fork terminals land under the screws of the supply's own terminal block.

## Reference

The drawing for this pigtail (`PJ1` to `PJ3`), its bill of materials and its downloads are on the [WireViz drawings]({{ '/hardware/parts/harness-order/#psu-pigtail' | relative_url }}) page.
