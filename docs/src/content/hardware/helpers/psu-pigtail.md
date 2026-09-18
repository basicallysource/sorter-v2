---
layout: default
title: Make your own PSU output pigtail
type: how-to
section: hardware
slug: helper-psu-pigtail
kicker: Helpers — PSU output pigtail
lede: Build one of the three DC output pigtails for the PSU box, a panel-mount barrel jack with a crimp fork terminal on each of its two leads.
permalink: /hardware/helpers/psu-pigtail/
author: effreek
contributors: [brickcyclealice]
last_verified: 2026-07-12
tools_needed: [Wire strippers, "Ratcheting crimp tool, or ordinary pliers", Multimeter]
---

The PSU box has three DC outputs. Each one is a short pigtail: a panel-mount barrel jack at one end, a crimp fork terminal on each of its two leads at the other. **Build three**, one for each 24 V load: the basically board, the USB hub and the Orange Pi buck.

<div class="callout">
  <p><b>Buy the jacks with their leads already attached.</b> This page assumes that. It crimps the terminals onto leads the jack already has. A bare jack means soldering the leads on, which this page does not cover.</p>
</div>

<figure class="harness-figure">
  <img src="https://assets.basically.website/sorter-docs/harness-psu-pigtail-built-w1600-59554dc6b189.jpg" alt="An assembled PSU output pigtail: a panel-mount barrel jack with red and black 18 AWG leads, each ending in an insulated fork terminal">
  <figcaption>One finished pigtail: the jack, its red +24 V and black ground leads, and an insulated fork terminal crimped on each. <cite>Photo: Jon.</cite></figcaption>
</figure>

## Parts

**A machine takes 3 jacks and 6 fork terminals.** The list below is one pigtail's worth.

<dl class="spec-list">
  <dt>DC barrel jack (×1)</dt><dd>5.5 × 2.1 mm female, panel-mount, centre-positive, rated 5 A or better, with its leads already attached: about 100 mm (4 in) of 18 AWG, red and black. The body fits a <b>12 mm</b> panel hole. <b>2.1 mm pin, not 2.5 mm</b> — the two do not mate.</dd>
  <dt>Fork terminals (×2)</dt><dd>Insulated fork terminal, 18 AWG, M3.5 stud, sold as fork or spade and often listed as #6. <b>8 mm wide at most.</b> Molex <code>0191310031</code> or equivalent. The width is the catch: plenty of them are wider and will not fit between the LRS-350-24's output screws, and the listing rarely gives the width, so go by the stud size.</dd>
</dl>

## Build it

<ol class="numbered-steps">
  <li>Start from a panel-mount jack with its leads already attached.</li>
  <li>Work out which lead is the tip (+24 V) and which is the sleeve (ground). The jack is <b>centre-positive</b>, so red is the tip and black is the sleeve. If the leads are not red and black, set a multimeter to continuity and hold one probe on the centre pin inside the jack: the lead that beeps is the tip.</li>
  <li>Crimp a fork terminal onto the free end of each lead, one on the tip lead and one on the sleeve lead.</li>
</ol>

Build three. All three are the same, so it does not matter which one goes to which load.

### Crimping the fork terminal

The crimp is the part that takes care. Strip the lead, seat it fully in the terminal barrel, crimp it in the matching die, then pull on it to check it holds.

<div class="callout">
  <p><b>No crimp tool?</b> Ordinary pliers will do it. Squeeze slowly and stop as soon as the barrel has closed on the wire. Pliers put all the force in one place and will crush the terminal if you keep going, which a ratcheting tool will not.</p>
</div>

<div class="photo-grid">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/harness-psu-pigtail-step1-stripped-w1600-7fe6beee8efc.png" alt="Stripped end of the 18 AWG wire showing bare strands">
    <figcaption>1. Strip the wire back to bare strands. <cite>Photo: Jon.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/harness-psu-pigtail-step2-terminal-w1600-6302bb6e8bc4.png" alt="Stripped wire seated in the fork terminal barrel, not yet crimped">
    <figcaption>2. Seat the bare strands fully in the terminal barrel. <cite>Photo: Jon.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/harness-psu-pigtail-step3-crimping-w1600-0ecacc7e17fd.png" alt="Crimping the terminal in the red 22 to 16 AWG die of a ratcheting crimp tool">
    <figcaption>3. Crimp in the matching die — the red (22–16 AWG) jaw suits the 18 AWG wire. <cite>Photo: Jon.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/harness-psu-pigtail-step4-crimped-w1600-ba1c9b488c45.png" alt="The finished crimp with the insulation grip closed on the wire jacket">
    <figcaption>4. Finished: the grip is closed on the jacket and the wire will not pull out. <cite>Photo: Jon.</cite></figcaption>
  </figure>
</div>

## Reference

The full drawing, BOM and downloads for this pigtail are on the [WireViz drawings]({{ '/hardware/electronics/wireviz/' | n }}) page, under **PSU output pigtail**.
