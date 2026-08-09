---
layout: default
title: Stepper connectors
type: reference
section: hardware
slug: electronics-stepper-connectors
kicker: Electronics — Stepper connectors
lede: basically board v1.3 stepper pinout, the connector-to-motor mapping, and the connector reference.
permalink: /hardware/electronics/steppers/
last_verified: 2026-07-12
---

All five stepper outputs on the board are identical.

## 1 &nbsp; basically board v1.3 connector pinout

Every stepper output connector on **basically board v1.3** has the same pinout, pin 1 to pin 4:

<table style="max-width:360px">
  <thead><tr><th>Pin</th><th>Net</th><th>Coil</th></tr></thead>
  <tbody>
    <tr><td>1</td><td>A2</td><td>coil A</td></tr>
    <tr><td>2</td><td>A1</td><td>coil A</td></tr>
    <tr><td>3</td><td>B1</td><td>coil B</td></tr>
    <tr><td>4</td><td>B2</td><td>coil B</td></tr>
  </tbody>
</table>

<figure class="diagram diagram-inline">
  <svg viewBox="0 0 360 150" width="330" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Board-side stepper connector footprint: pin 1 is the square pad, carrying A2, A1, B1, B2 across four pins with coil A on pins 1-2 and coil B on pins 3-4">
    <g font-size="12" fill="var(--muted)" text-anchor="middle">
      <text x="60" y="26">1</text><text x="140" y="26">2</text>
      <text x="220" y="26">3</text><text x="300" y="26">4</text>
    </g>
    <rect x="44" y="34" width="32" height="32" rx="4" fill="var(--bg)" stroke="var(--ink)" stroke-width="1.6" />
    <g fill="var(--bg)" stroke="var(--ink)" stroke-width="1.6">
      <circle cx="140" cy="50" r="16" /><circle cx="220" cy="50" r="16" /><circle cx="300" cy="50" r="16" />
    </g>
    <g font-size="12.5" font-weight="700" text-anchor="middle" fill="var(--ink)">
      <text x="60" y="92">A2</text><text x="140" y="92">A1</text>
      <text x="220" y="92">B1</text><text x="300" y="92">B2</text>
    </g>
    <g stroke="var(--ink)" stroke-width="1.3" fill="none">
      <path d="M46 108 v8 h108 v-8" /><path d="M206 108 v8 h108 v-8" />
    </g>
    <g font-size="12" fill="var(--ink)" text-anchor="middle">
      <text x="100" y="138">coil A</text><text x="260" y="138">coil B</text>
    </g>
  </svg>
  <figcaption>Pin 1 (A2) is the square pad.</figcaption>
</figure>

- Holds for all five **JST-PH 4-pin** connectors: `J23, J27, J31, J35, J39`.
- The parallel **2.54 mm headers** next to each are wired identically: `J24, J28, J32, J36, J40`.
- Pin 1 is the roundrect (square-ish) pad on the footprint.
- Straight pass-through of the BigTreeTech TMC2209 module output order: module pins 3-6 = A2, A1, B1, B2, mapping to connector pins 1-4.

<div class="callout">
  <span class="callout-icon" aria-hidden="true">›</span>
  <p><b>Coil rule.</b> Pins 1-2 are one coil (A), pins 3-4 the other (B). Swapping the two wires <i>within</i> a coil only reverses motor direction. Splitting a coil across the 2/3 boundary is what actually breaks operation, so keep each pair together.</p>
</div>

## 2 &nbsp; basically board v1.3 to motor connections

On the board side the stepper harness uses **4x1 dupont** housings (2.54 mm) on the parallel pin headers. The 4 channel motors are StepperOnline NEMA 17, shipped with a **JST-XH 2.54 mm** 4-pin lead (the 3D-printer "XH2.54" cable, black/green/red/blue). The chute motor ships as bare flying leads.

<table>
  <thead><tr><th>Stepper</th><th>basically board v1.3 connector</th><th>Motor connector</th><th>Wire length</th><th>Gauge</th><th>Notes</th></tr></thead>
  <tbody>
    <tr>
      <td>Channels 1-4 (×4)</td>
      <td>4x1 dupont (2.54 mm) on pin headers J24 / J28 / J32 / J36</td>
      <td>JST-XH 2.54 mm, 4-pin (StepperOnline "XH2.54")</td>
      <td>40 in</td>
      <td>unknown</td>
      <td>Inner two wires flipped (positions 2 and 3) so coils line up</td>
    </tr>
    <tr>
      <td>Chute (5th)</td>
      <td>4x1 dupont (2.54 mm) on pin header J40</td>
      <td>Bare flying leads, crimp into a 4x1 housing</td>
      <td>unknown</td>
      <td>unknown</td>
      <td>Motor has no connector; crimp leads to the coil order above</td>
    </tr>
  </tbody>
</table>

Refdes-to-channel assignment (which of J23/J27/J31/J35/J39 is which channel, and which is the chute) is still to confirm.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Polarity, restated.</b> The basically board v1.3 order is fixed (section 1). For channels 1-4 the cable swaps the inner two conductors relative to how StepperOnline ships them, so the motor coils match the basically board v1.3 grouping. Confirm against the actual motor before crimping the chute.</p>
</div>

{% include harness/pin-swap.html %}

## 3 &nbsp; Connector reference

- **4x1 dupont (2.54 mm)**: board-side harness connector for the steppers, mates the 2.54 mm pin headers J24, J28, J32, J36, J40.
- **2.54 mm (0.1") pin header, 4-pin**: the board headers the dupont plugs onto (J24, J28, J32, J36, J40).
- **JST-PH 2.0 mm, 4-pin**: also on the board (J23, J27, J31, J35, J39), same pinout as the headers.
- **JST-XH 2.54 mm, 4-pin ("XH2.54")**: StepperOnline motor lead (channels 1-4). Color code black/green = one coil, red/blue = the other.

## 4 &nbsp; Sources

- StepperOnline NEMA 17 motors (XH2.54 lead): [omc-stepperonline.com](https://www.omc-stepperonline.com/nema-17-stepper-motor)
- JST PH series: [jst.com](https://www.jst.com/products/crimp-style-connectors-wire-to-board-type/ph-connector/)
