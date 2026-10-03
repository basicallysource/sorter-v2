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

Do this for every camera on the machine, one at a time.

<ol class="numbered-steps">
  <li>Lay the Siemens Star flat where that camera looks at parts. On a channel camera that is the <strong>rotor</strong>, the part the pieces ride on, at the point where the camera sees them. On a machine with a classification chamber it is the chamber tray, centred where parts sit.</li>
  <li>Open the SorterOS UI, then <strong>Settings</strong>, then pick that camera. The live feed shows the star pattern.</li>
  <li>Loosen the lens lock ring and turn the lens until the <strong>centre spokes resolve sharply</strong>, the point where the individual black and white wedges stay separate all the way in to the middle.</li>
  <li>Tighten the lock ring. Take the chart out.</li>
</ol>

**The centre of the star is the most demanding part of the image.** If the spokes merge into grey mush in the middle, focus is not tight enough yet.

## Run this again when

- You swap a camera or a lens.
- You move a camera lamp to a different dovetail.
- Detection starts missing pieces a camera used to see.

## The finished result

Every camera on the machine sharp, with the centre of the star resolving cleanly in each live view.

<div class="img-placeholder">Screenshot of a channel camera's live view in Settings with the Siemens Star in frame and its centre spokes resolving sharply.</div>

## Next

[Chute calibration]({{ '/sorter/chute-calibration/' | relative_url }}), then [before your first sort run]({{ '/sorter/before-first-sort-run/' | relative_url }}).
