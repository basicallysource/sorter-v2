---
layout: default
title: Make your own PSU output pigtail
type: reference
section: hardware
slug: electronics-psu-pigtail
kicker: Electronics — PSU output pigtail
lede: Build one of the three DC output pigtails for the PSU box: a panel-mount barrel jack and two crimp spade terminals.
permalink: /hardware/electronics/psu-pigtail/
last_verified: 2026-07-12
---

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Not validated against a built machine.</b> This is the current spec off the harness drawings, not a checked build procedure. Values marked <b>GUESS</b> in the <a href="{{ '/hardware/electronics/wireviz/' | n }}">WireViz drawing</a> are guesses.</p>
</div>

The PSU box has three DC outputs, and each one is a short pigtail: two crimp spade terminals onto the PSU terminal block at one end, a panel-mount barrel jack on the other. You need **three per PSU build**, one for each 24V load (the basically board, the USB hub, and the Orange Pi buck).

<div class="callout">
  <p><b>You usually don't have to make these.</b> The panel-mount jacks are commonly sold with the pigtail leads already attached, so buying the jacks with leads and crimping the spade terminals on is less work than building from bare wire. This page is for when you want to make your own.</p>
</div>

<figure class="harness-figure">
  <img src="https://img.basically.website/web/harness/psu-pigtail-built.dc73ad657b30cce2.jpg" alt="An assembled PSU output pigtail: a panel-mount barrel jack with red and black 18 AWG leads, each ending in an insulated spade terminal">
  <figcaption>One assembled pigtail: panel-mount barrel jack, red +24V and black ground leads, an insulated spade terminal crimped on each.</figcaption>
</figure>

## Parts, per pigtail

<dl class="spec-list">
  <dt>DC barrel jack</dt><dd>5.5 × 2.1 mm female, panel-mount, center-positive, rated ≥ 5 A. <b>2.1 mm pin, not 2.5 mm</b> — the two do not mate.</dd>
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
4. At the PSU terminal block, the red terminal lands on a <b>+V</b> screw and the black on the matching <b>−V</b> screw. MEAN WELL numbers the LRS-350-24 block so that <b>4–6 are −V</b> and <b>7–9 are +V</b>: pair <b>7 with 4, 8 with 5, 9 with 6</b>, one pigtail per pair.
5. Panel-mount the jack into the PSU enclosure.

Repeat for all three outputs.

## Reference

The full drawing, BOM and downloads for this pigtail are on the [WireViz drawings]({{ '/hardware/electronics/wireviz/' | n }}) page, under **PSU output pigtail**.
