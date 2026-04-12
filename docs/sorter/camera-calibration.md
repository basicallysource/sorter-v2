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
last_verified: 2026-04-12
---

Camera calibration has two stages: **focus** (mechanical, done by hand) and **color** (automated via the Settings UI). Both matter — a soft image kills detection accuracy, and wrong color balance drifts classification.

## Focus calibration

### What you need

- A printed **Siemens Star** focus chart, roughly 8 x 8 cm. Any high-contrast radial spoke pattern works.

![Siemens Star focus chart]({{ '/assets/png-transparent-siemens-star-focus-camera-optics-charts-angle-lens-triangle.png' | relative_url }})

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

Color calibration uses a **SpyderCheckr 24** color checker and runs automatically from the UI.

### What you need

- SpyderCheckr 24 (or compatible 4 x 6 patch target) placed in the classification chamber, filling most of the frame.

### Steps

| # | Action |
|---|--------|
| 1 | Place the color checker on the tray, angled so all 24 patches are visible in the live feed. |
| 2 | Go to **Settings** → select the camera → click **Calibrate**. |
| 3 | The backend runs through exposure bracketing, white balance, and color matrix fitting. Progress appears in the sidebar. |
| 4 | When done, the color profile is saved automatically and applied to every frame. |

The calibration pipeline:

1. **Exposure** — bracketed captures estimate the camera response curve, then sets optimal exposure directly.
2. **Firmware neutralize** — resets white balance, saturation, gamma, contrast to defaults so the software pipeline has a clean input.
3. **Detect checker** — locates the 24 color patches in the frame.
4. **Color correction matrix** — least-squares fit of a 3 x 3 affine CCM + per-channel gamma from measured vs. reference patch colors.

The resulting profile (CCM, response LUT, gamma curves) is stored in the machine config and applied at runtime with no per-frame overhead beyond a lookup + matrix multiply.

### Re-calibration

Re-run calibration when:

- You swap a camera or lens.
- Lighting hardware changes (new LED strip, different diffuser).
- Color drift is visible in classification samples.
