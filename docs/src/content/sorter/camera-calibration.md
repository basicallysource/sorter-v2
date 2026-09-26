---
layout: default
title: Camera calibration
type: how-to
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-camera-calibration
kicker: Sorter — Operate
lede: Focus every camera on the machine against a printed chart. Do this once per camera, and again after swapping a camera or a lens.
permalink: /sorter/camera-calibration/
last_verified: 2026-09-18
tools_needed:
  - A printer, for the focus chart
---

Focus is the whole of camera calibration today, and it is mechanical: you turn each lens by hand against a printed chart until the image is sharp. A soft image costs you detection accuracy on every piece that camera sees.

Color calibration exists in the software but is switched off in the current build. There is nothing to set up for it, and the last section says what that means.

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
  <li>Open the Sorter UI, then <strong>Settings</strong>, then pick that camera. The live feed shows the star pattern.</li>
  <li>Loosen the lens lock ring and turn the lens until the <strong>centre spokes resolve sharply</strong>, the point where the individual black and white wedges stay separate all the way in to the middle.</li>
  <li>Tighten the lock ring. Take the chart out.</li>
</ol>

**The centre of the star is the most demanding part of the image.** If the spokes merge into grey mush in the middle, focus is not tight enough yet.

## Color calibration

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Color calibration is switched off in the current software, so there is nothing to do here.</b> No <b>Calibrate</b> button appears in Settings and no frames are corrected on any camera. Focus above is unaffected. Any profile already saved on a machine is kept and applies again if it is switched back on.</p>
</div>

Skip to [Chute calibration]({{ '/sorter/chute-calibration/' | relative_url }}). The rest of this section is the reference for when color calibration comes back, so you do not need to read it or build anything for it now.

### The reference plate, for later

Color calibration uses a **6-color LEGO reference plate**, not a commercial color checker. The same flow runs per camera role (`classification_top`, `classification_bottom`, `classification_channel`, `c_channel_2`, `c_channel_3`, `carousel`), so one plate has to work in front of each of those.

A 4-column x 6-row grid, columns left to right and rows top to bottom:

| | Col 1 | Col 2 | Col 3 | Col 4 |
|---|---|---|---|---|
| Row 1 | white | black | white | black |
| Row 2 | blue | blue | red | red |
| Row 3 | blue | blue | red | red |
| Row 4 | green | green | yellow | yellow |
| Row 5 | green | green | yellow | yellow |
| Row 6 | black | white | black | white |

The six colors, with the closest standard LEGO color name and ID in each cataloging system. These are the six basic colors LEGO has used since 1949; the hex values are measured off a photographed reference swatch under specific lighting, not a pigment spec.

| Color | Hex | RGB | LEGO name (ID) | BrickLink name (ID) | Rebrickable name (ID) |
|---|---|---|---|---|---|
| White | `#dbeff3` | 219, 239, 243 | White (1) | White (1) | White (15) |
| Black | `#1b1e25` | 27, 30, 37 | Black (26) | Black (11) | Black (0) |
| Blue | `#269cdd` | 38, 156, 221 | Bright Blue (23) | Blue (7) | Blue (1) |
| Red | `#e22b24` | 226, 43, 36 | Bright Red (21) | Red (5) | Red (4) |
| Green | `#0b9b63` | 11, 155, 99 | Dark Green (28) | Green (6) | Green (2) |
| Yellow | `#f0d61d` | 240, 214, 29 | Bright Yellow (24) | Yellow (3) | Yellow (14) |

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>No official size exists for this plate.</b> Any size works, so check a build against each camera's live preview in Settings before committing to it.</p>
</div>

<figure class="figure-float-right">
  <a href="https://assets.basically.website/sorter-docs/camera-calibration-suggested-plate-2x2-full-91ad046adc71.png" target="_blank" rel="noopener">
    <img src="https://assets.basically.website/sorter-docs/camera-calibration-suggested-plate-2x2-full-91ad046adc71.png" alt="4 by 6 grid diagram of the calibration plate pattern, drawn as LEGO plates with studs, in the six reference colors, 2 studs per cell">
  </a>
  <figcaption>Click to enlarge. <cite>Rendered from the pattern above, not a photo. Render: Balloon.</cite></figcaption>
</figure>

One way to build it: 2x2 studs per grid cell, 8 studs wide x 12 studs tall overall. The four 2x2-cell color blocks (blue, red, green, yellow) are each 4x4 studs, so one plate or tile per color instead of four 2x2s. The alternating top and bottom rows need individual 2x2 plates or tiles, because they do not form contiguous blocks.

<div class="clear-float"></div>

## Run this again when

- You swap a camera or a lens.
- You move a camera lamp to a different dovetail.
- Detection starts missing pieces a camera used to see.

## The finished result

Every camera on the machine sharp, with the centre of the star resolving cleanly in each live view.

<div class="img-placeholder">Screenshot of a channel camera's live view in Settings with the Siemens Star in frame and its centre spokes resolving sharply.</div>

## Next

[Chute calibration]({{ '/sorter/chute-calibration/' | relative_url }}), then [before your first sort run]({{ '/sorter/before-first-sort-run/' | relative_url }}).
