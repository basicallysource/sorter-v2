---
layout: default
title: Camera calibration
type: how-to
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-camera-calibration
kicker: SorterOS — Operate
lede: Focus every camera on the machine against a printed chart. Do this once per camera, and again after swapping a camera or a lens.
permalink: /sorter/camera-calibration/
warning: >-
  **SorterOS changes quickly.** This page describes what each step does, but a
  button's name, or where it is, may have changed since this page was written,
  so it keeps screenshots to a minimum.
last_verified: 2026-09-18
tools_needed:
  - A printer, for the focus chart
---

Focus is the whole of camera calibration, and it is mechanical: you turn each lens by hand against a printed chart until the image is sharp. A soft image costs you detection accuracy on every piece that camera sees.

## Focus calibration

### What you need

- A printed **Siemens Star** focus chart, roughly 8 x 8 cm. Any high-contrast radial spoke pattern works.

<figure class="figure-float-right">
  <a href="{{ '/assets/siemens-star-print.html' | relative_url }}" target="_blank" rel="noopener">
    <img src="{{ '/assets/png-transparent-siemens-star-focus-camera-optics-charts-angle-lens-triangle.png' | relative_url }}" alt="Siemens Star focus chart">
  </a>
  <figcaption>Click to open the print page.</figcaption>
</figure>

This preview isn't sized to print, it's just scaled to fit the column. Click it to open a print-ready page, sized exactly 8 x 8 cm with crop marks, and print that at 100% scale, not "fit to page", or it won't come out to size.

<div class="clear-float"></div>

### Steps

Do this for every camera on the machine, one at a time. Some steps happen at the machine and some in the UI, and each step says which.

<ol class="numbered-steps">
  <li><strong>At the machine:</strong> lay the Siemens Star flat on that channel's <strong>rotor</strong>, the part the pieces ride on, at the point where the camera sees them.</li>
  <li><strong>In the UI:</strong> open <strong>Settings</strong>, and under <strong>Hardware</strong> pick that camera's channel: <strong>C-channel 2</strong>, <strong>C-channel 3</strong> or <strong>Classification channel</strong>. The live view shows the star.</li>
  <li><strong>In the UI:</strong> check that the channel's lamp is on, so you focus in the same light the camera sorts in. If it is off, press <strong>LED</strong> on the same page and pick its <strong>Output</strong>.</li>
  <li><strong>At the camera:</strong> loosen the lens lock ring and turn the lens until the <strong>centre spokes resolve sharply</strong> in the live view, the point where the individual black and white wedges stay separate all the way in to the middle. It is possible to turn too far and lose it again. Keep your hand where the camera can still see the star, so you can watch it on screen while you turn.</li>
  <li><strong>At the camera:</strong> tighten the lock ring. Take the chart out.</li>
</ol>

<div class="img-row">
  <figure><img src="https://assets.basically.website/sorter-docs/siemens-star-chart-on-c4-rotor-w1600-47a49ac6af95.jpg" alt="A printed Siemens Star chart lying flat on the classification channel rotor, seen from the side"><figcaption>The chart lying on the classification channel rotor, ready to focus. <cite>Photo: BrickCycleAlice.</cite></figcaption></figure>
</div>

**The centre of the star is the most demanding part of the image.** If the spokes merge into grey mush in the middle, focus is not tight enough yet.

## Run this again when

- You swap a camera or a lens.
- You move a camera lamp to a different dovetail.
- Detection starts missing pieces a camera used to see.

## The finished result

Every camera on the machine sharp, with the centre of the star resolving cleanly in each live view.

<div class="img-row">
  <figure><img src="https://assets.basically.website/sorter-docs/siemens-star-focus-live-view-full-e4a416d7d9ef.png" alt="The classification channel camera's live view in Settings, with the Siemens Star on the rotor and its spokes separate all the way to the centre"><figcaption>The classification channel camera in focus, with the star's spokes separate in to the middle. <cite>Screenshot courtesy of BrickCycleAlice.</cite></figcaption></figure>
</div>

Finer camera tuning can be done during operation: open **Settings**, pick the channel under **Hardware** and press **Picture**. Its **Manual settings** hold the camera's own controls, such as exposure.

## Next

[Chute calibration]({{ '/sorter/chute-calibration/' | relative_url }}), then [before your first sort run]({{ '/sorter/before-first-sort-run/' | relative_url }}).
