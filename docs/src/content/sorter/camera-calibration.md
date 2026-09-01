---
layout: default
title: Camera calibration
type: how-to
audience: operator
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-camera-calibration
kicker: Sorter — Operate
lede: Set up focus, exposure, and color accuracy for the classification and feeder cameras. Do this once per camera or after swapping hardware.
permalink: /sorter/camera-calibration/
last_verified: 2026-08-31
---

Camera calibration has two stages: **focus** (mechanical, done by hand) and **color** (automated via the Settings UI). Both matter — a soft image kills detection accuracy, and wrong color balance drifts classification.

## Focus calibration

### What you need

- A printed **Siemens Star** focus chart, roughly 8 x 8 cm. Any high-contrast radial spoke pattern works.

<figure class="single-figure">
  <a href="{{ '/assets/png-transparent-siemens-star-focus-camera-optics-charts-angle-lens-triangle.png' | relative_url }}" target="_blank" rel="noopener">
    <img src="{{ '/assets/png-transparent-siemens-star-focus-camera-optics-charts-angle-lens-triangle.png' | relative_url }}" alt="Siemens Star focus chart" style="width: 8cm; height: 8cm;">
  </a>
  <figcaption>Sized to print at 8 x 8 cm. Click to open it on its own, then print at 100% scale, not "fit to page", or it won't come out to size.</figcaption>
</figure>

### Steps

| # | Action |
|---|--------|
| 1 | Place the Siemens Star flat on the **classification chamber tray**, centered where parts normally sit. |
| 2 | Open the Sorter UI → **Settings** → select the camera. The live feed shows the star pattern. |
| 3 | Loosen the camera lens lock ring and rotate the lens until the **center spokes resolve sharply** — the point where individual black/white wedges stay distinct all the way to the middle. |
| 4 | Tighten the lock ring. Remove the chart. |

**Tip:** The center of the Siemens Star is the most demanding part of the image. If the spokes merge into grey mush in the middle, focus is not tight enough.

For feeder cameras, place the chart on the C-channel belt at the detection point and repeat.

## Color calibration

Color calibration uses a **6-color LEGO reference plate**, not a commercial color checker, and runs automatically from the UI.

### What you need

A 4-column x 6-row plate built from LEGO plates/tiles in six colors, placed in front of the camera being calibrated and filling most of its frame. This isn't only for the classification chamber: the same calibration flow runs per camera role (`classification_top`, `classification_bottom`, `classification_channel`, `c_channel_2`, `c_channel_3`, `carousel`), so the same plate design needs to work in front of each of those, not only the chamber. The grid (columns left to right, rows top to bottom):

| | Col 1 | Col 2 | Col 3 | Col 4 |
|---|---|---|---|---|
| Row 1 | white | black | white | black |
| Row 2 | blue | blue | red | red |
| Row 3 | blue | blue | red | red |
| Row 4 | green | green | yellow | yellow |
| Row 5 | green | green | yellow | yellow |
| Row 6 | black | white | black | white |

Reference colors the pipeline fits against, with the closest standard LEGO color name and ID in each cataloging system (these are the six basic colors LEGO has used since 1949, not exact hex matches to the photographed reference swatch below, which is measured under specific lighting, not a pigment spec):

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
  <p><b>No official size exists for this plate.</b> Any size works, so check the build below against each camera's live preview in Settings before committing to it.</p>
</div>

<figure class="figure-float-right">
  <a href="https://assets.basically.website/sorter-docs/camera-calibration-suggested-plate-2x2-full-91ad046adc71.png" target="_blank" rel="noopener">
    <img src="https://assets.basically.website/sorter-docs/camera-calibration-suggested-plate-2x2-full-91ad046adc71.png" alt="4 by 6 grid diagram of the calibration plate pattern, drawn as LEGO plates with studs, in the six reference colors, 2 studs per cell">
  </a>
  <figcaption>Click to enlarge. <cite>Rendered from the pattern above, not a photo. Render: Balloon.</cite></figcaption>
</figure>

One way to build it: 2x2 studs per grid cell, 8 studs wide x 12 studs tall overall. The four 2x2-cell color blocks (blue/red/green/yellow) are each 4x4 studs, so one plate or tile per color instead of four 2x2s; the alternating top and bottom rows need individual 2x2 plates/tiles, they don't form contiguous blocks.

<div class="clear-float"></div>

### Steps

| # | Action |
|---|--------|
| 1 | Place the plate on the tray, angled so the full 4x6 grid is visible in the live feed. |
| 2 | Go to **Settings** → select the camera → click **Calibrate**. |
| 3 | The backend runs through exposure bracketing, white balance, and color matrix fitting. Progress appears in the sidebar. |
| 4 | When done, the color profile is saved automatically and applied to every frame. |

The calibration pipeline:

1. **Exposure** — bracketed captures estimate the camera response curve, then sets optimal exposure directly.
2. **Firmware neutralize** — resets white balance, saturation, gamma, contrast to defaults so the software pipeline has a clean input.
3. **Detect target** — locates the 6-color plate in the frame.
4. **Color correction matrix** — least-squares fit of a 3 x 3 affine CCM + per-channel gamma from measured vs. reference tile colors.

The resulting profile (CCM, response LUT, gamma curves) is stored in the machine config and applied at runtime with no per-frame overhead beyond a lookup + matrix multiply.

### Re-calibration

Re-run calibration when:

- You swap a camera or lens.
- Lighting hardware changes (new LED strip, different diffuser).
- Color drift is visible in classification samples.
