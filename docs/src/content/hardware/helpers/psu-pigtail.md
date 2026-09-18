---
layout: default
title: Make your own PSU output pigtail
type: how-to
section: hardware
slug: helper-psu-pigtail
kicker: Helpers — PSU output pigtail
lede: Build one of the three DC output pigtails for the PSU box, a panel-mount barrel jack with two crimp spade terminals on its leads.
permalink: /hardware/helpers/psu-pigtail/
author: effreek
contributors: [brickcyclealice]
last_verified: 2026-07-12
tools_needed: [Side cutters, Wire strippers, Ratcheting crimp tool, Multimeter]
---

The PSU box has three DC outputs, and each one is a short pigtail: two crimp spade terminals at one end, a panel-mount barrel jack at the other. You need **three per PSU build**, one for each 24V load (the basically board, the USB hub, and the Orange Pi buck).

This page builds the cables and stops there. Landing them on the supply's terminal block and mounting the jacks in the box is step 4 of the [PSU box]({{ '/hardware/electronics/installation/psu-box/' | n }}) page.

<div class="callout">
  <p><b>You usually don't have to make these.</b> The panel-mount jacks are commonly sold with the pigtail leads already attached, so buying the jacks with leads and crimping the spade terminals on is less work than building from bare wire. This page is for when you want to make your own.</p>
</div>

<figure class="harness-figure">
  <img src="https://assets.basically.website/sorter-docs/harness-psu-pigtail-built-w1600-59554dc6b189.jpg" alt="An assembled PSU output pigtail: a panel-mount barrel jack with red and black 18 AWG leads, each ending in an insulated spade terminal">
  <figcaption>One assembled pigtail: panel-mount barrel jack, red +24V and black ground leads, an insulated spade terminal crimped on each. <cite>Photo: Jon.</cite></figcaption>
</figure>

## Parts, per pigtail

<dl class="spec-list">
  <dt>DC barrel jack</dt><dd>5.5 × 2.1 mm female, panel-mount, center-positive, rated ≥ 5 A, on a body that fits a <b>12 mm</b> panel hole. <b>2.1 mm pin, not 2.5 mm</b> — the two do not mate.</dd>
  <dt>Spade terminals (×2)</dt><dd>Insulated fork/spade, 18 AWG, M3.5 stud, <b>8 mm wide max</b>. Molex <code>0191310031</code> or equivalent. The 8 mm limit matters: wider terminals will not fit between the LRS-350-24 output screws.</dd>
  <dt>Wire</dt><dd>~4 in of 18 AWG, one red and one black. Skip this if your jack already ships with leads.</dd>
</dl>

<p class="download-line">
  <span>Where to buy:</span>
  <span><b>Amazon links for the jack and the crimp terminals are being added here.</b></span>
</p>

## Build it

1. Start from ~4 in of 18 AWG red and black wire, or from a panel-mount jack that already has its leads.
2. Wire the jack **center-positive**: red to the tip (+24V), black to the sleeve (GND). If your jack came with unlabeled leads, check tip vs sleeve with a multimeter before you trust the colors.
3. Crimp an insulated spade terminal onto the free end of each wire — one on red, one on black.

Repeat for all three outputs. All three are identical, so it does not matter which finished pigtail goes to which load.

### Crimping the spade terminal

The crimp is the fiddly part. Strip the wire, seat it fully in the terminal barrel, crimp it in the matching die, and check it does not pull out.

<div class="photo-grid">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/harness-psu-pigtail-step1-stripped-w1600-7fe6beee8efc.png" alt="Stripped end of the 18 AWG wire showing bare strands">
    <figcaption>1. Strip the wire back to bare strands. <cite>Photo: Jon.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/harness-psu-pigtail-step2-terminal-w1600-6302bb6e8bc4.png" alt="Stripped wire seated in the spade terminal barrel, not yet crimped">
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

## Where they go

Three finished pigtails are a needed component of the [PSU box]({{ '/hardware/electronics/installation/psu-box/' | n }}). That page has which screw pair each one lands on and how the jacks mount in the box.

## Reference

The full drawing, BOM and downloads for this pigtail are on the [WireViz drawings]({{ '/hardware/electronics/wireviz/' | n }}) page, under **PSU output pigtail**.
