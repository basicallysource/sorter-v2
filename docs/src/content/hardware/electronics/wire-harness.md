---
layout: default
title: Wire harness
type: reference
section: hardware
slug: electronics-wire-harness
kicker: Electronics — Wire harness
lede: How the machine is wired. The supply, what it feeds, and what plugs into the control board.
permalink: /hardware/electronics/wire-harness/
author: spencer
contributors: [effreek]
last_verified: 2026-10-03
---

This page is the wiring. Where the PSU, the control board and the Orange Pi physically mount is [Installing the electronics]({{ '/hardware/electronics/installation/' | relative_url }}), and the render of where each one sits is on that page. Plugging them together afterwards is [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}).

**The cables are yours to make, buy or order.** Every cable on the diagram below can be bought ready made or built on the bench, with the [Helpers]({{ '/hardware/helpers/' | relative_url }}) pages and the bill of materials under each drawing. To have the whole set made in one go, send a cable vendor the pack on [Ordering the wire harness]({{ '/hardware/parts/harness-order/' | relative_url }}), which also has the drawing, length and connectors of every cable.

## 1 &nbsp; Power supply

<dl class="spec-list">
  <dt>Model</dt><dd>MEAN WELL LRS-350-24</dd>
  <dt>Output</dt><dd>24V, 14.6A, 350.4W, single output</dd>
  <dt>Enclosure</dt><dd>Custom 3D-printed box, fused AC input</dd>
  <dt>Terminal block</dt><dd>9-position, MEAN WELL's own numbering: <b>1</b> AC/L, <b>2</b> AC/N, <b>3</b> FG, <b>4-6</b> DC OUTPUT -V, <b>7-9</b> DC OUTPUT +V (LRS-350-SPEC)</dd>
  <dt>DC outputs</dt><dd>3 × female DC jack, each a 4 in 18 AWG (0.82 mm²) pigtail with 2 × spade/fork terminals (M3.5, 8 mm wide max, Molex 0191310031 or equivalent). One pigtail per +V/-V screw pair: 7 with 4, 8 with 5, 9 with 6</dd>
  <dt>AC input</dt><dd>Screws 1, 2, 3. Fed by the fused IEC inlet switch's own pre-terminated leads, so there is no cable to make</dd>
  <dt>Loads</dt><dd>basically board v1.3, the USB hub, and the Orange Pi buck converter. One jack each, no spare</dd>
  <dt>Not on this bus, but on the 24V bus indirectly</dt><dd>The cooling fans. Not a direct PSU jack. The control board's own 40mm fan plugs into one of board v1.3's four LED ports instead (24V, GPIO-switched, current-limited unless a bypass jumper is bridged), see <a href="{{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}">control board housing</a> step 5. The Orange Pi needs nothing off this bus: it is cooled by the 5V heatsink fan on its own SoC, which runs off the board's own FAN socket.</dd>
</dl>

## 2 &nbsp; Interconnect diagram

<figure class="harness-figure">
  <div class="diagram diagram-wide">
    <svg viewBox="-120 0 1080 460" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="System interconnect: PSU feeds basically board v1.3 and the direct 24V loads; the board drives LEDs, sensors, steppers and the first servo adapter board">
      <g stroke="var(--ink)" stroke-width="1.5" fill="none" stroke-linecap="round">
        <rect x="14" y="40" width="150" height="400" rx="4" fill="var(--bg)" />
        <rect x="250" y="50" width="180" height="280" rx="4" fill="var(--bg)" />
        <line x1="164" y1="190" x2="250" y2="190" />
        <line x1="164" y1="360" x2="250" y2="360" />
        <line x1="164" y1="410" x2="250" y2="410" />
        <line x1="430" y1="70" x2="640" y2="50" />
        <line x1="430" y1="110" x2="640" y2="100" />
        <line x1="430" y1="150" x2="640" y2="150" />
        <line x1="430" y1="190" x2="640" y2="200" />
        <line x1="430" y1="230" x2="640" y2="250" />
        <line x1="430" y1="270" x2="640" y2="300" />
        <line x1="430" y1="310" x2="640" y2="350" />
      </g>
      <g stroke="var(--ink)" stroke-width="1.2" fill="var(--surface)">
        <rect x="158" y="182" width="14" height="16" /><rect x="158" y="352" width="14" height="16" />
        <rect x="158" y="402" width="14" height="16" />
      </g>
      <g stroke="var(--ink)" stroke-width="1.2" fill="var(--surface)">
        <rect x="250" y="345" width="180" height="30" rx="3" />
        <rect x="250" y="395" width="180" height="30" rx="3" />
      </g>
      <g stroke="var(--ink)" stroke-width="1.2" fill="var(--surface)">
        <rect x="640" y="33" width="300" height="34" rx="3" />
        <rect x="640" y="83" width="300" height="34" rx="3" />
        <rect x="640" y="133" width="300" height="34" rx="3" />
        <rect x="640" y="183" width="300" height="34" rx="3" />
        <rect x="640" y="233" width="300" height="34" rx="3" />
        <rect x="640" y="283" width="300" height="34" rx="3" />
        <rect x="640" y="333" width="300" height="34" rx="3" />
      </g>
      <text x="24" y="66" font-size="13" font-weight="700" fill="var(--ink)">MEAN WELL</text>
      <text x="24" y="82" font-size="12" font-weight="700" fill="var(--ink)">LRS-350-24</text>
      <text x="24" y="100" font-size="11" fill="var(--muted)">24V · 14.6A · 350W</text>
      <line x1="-56" y1="118" x2="14" y2="118" stroke="var(--ink)" stroke-width="1.5" stroke-linecap="round" />
      <rect x="-96" y="104" width="40" height="28" rx="3" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.2" />
      <text x="-76" y="122" font-size="10" font-weight="700" text-anchor="middle" fill="var(--ink)">AC in</text>
      <text x="-76" y="147" font-size="9" fill="var(--muted)" text-anchor="middle">fused inlet switch</text>
      <g font-size="11" fill="var(--ink)" text-anchor="end" font-weight="700">
        <text x="154" y="194">PJ1</text><text x="154" y="364">PJ2</text><text x="154" y="414">PJ3</text>
      </g>
      <text x="262" y="80" font-size="13" font-weight="700" fill="var(--ink)">basically board</text>
      <text x="262" y="96" font-size="12" font-weight="700" fill="var(--ink)">v1.3</text>
      <text x="262" y="118" font-size="10.5" fill="var(--muted)">hub for LEDs, sensors,</text>
      <text x="262" y="132" font-size="10.5" fill="var(--muted)">steppers, servo adapters</text>
      <text x="262" y="184" font-size="9.5" fill="var(--muted)">24V in: JST-VH female</text>
      <g font-size="11" fill="var(--ink)" text-anchor="middle">
        <text x="207" y="184">W1</text>
        <text x="207" y="354">W2</text>
        <text x="207" y="404">W3</text>
      </g>
      <g font-size="10.5" fill="var(--ink)" text-anchor="middle">
        <text x="535" y="48">L1 · 2x1 dupont</text>
        <text x="535" y="93">L2 · 2x1 dupont</text>
        <text x="535" y="143">L3 · 2x1 dupont</text>
        <text x="535" y="188">LIM · 2x1 dupont</text>
        <text x="535" y="233">S1-4 · JST-PH 4-pin</text>
        <text x="535" y="283">CH · 4x1 dupont · flying leads</text>
        <text x="535" y="328">RIB1 · 16-pin IDC</text>
      </g>
      <g font-size="11" font-weight="700" fill="var(--ink)">
        <text x="258" y="364">Waveshare 4-port USB hub</text>
        <text x="258" y="414">Orange Pi 5</text>
      </g>
      <g font-size="12" font-weight="700" fill="var(--ink)">
        <text x="652" y="55">LED strip (6000K)</text>
        <text x="652" y="105">LED strip (6000K)</text>
        <text x="652" y="155">LED strip (6000K)</text>
        <text x="652" y="205">Limit switch</text>
        <text x="652" y="255">Stepper, channels 1-4 (×4)</text>
        <text x="652" y="305">Chute stepper</text>
        <text x="652" y="355">Servo adapter board (first)</text>
      </g>
    </svg>
  </div>
  <figcaption>PSU distributes 24V to basically board v1.3 (through a JST-VH inlet) and the two other direct loads (USB hub, Orange Pi buck). Cooling fans are not on this bus, they run off the Pi or the board. basically board v1.3 then drives the LED drops (L1-L3), the limit switch, the steppers, and the first servo adapter board over a 16-pin IDC ribbon. Wire IDs are the cable IDs on the order page.</figcaption>
</figure>

### 2.1 &nbsp; Stepper pinout and polarity

Every stepper output on **basically board v1.3** has the same pinout, pin 1 to pin 4:

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

The 4 channel motors are NEMA 17 with their own **JST-PH 6-pin** socket, so cable S plugs straight into the motor and the shipped StepperOnline lead is not used. The chute motor ships as bare flying leads instead, and its cable is built: [make the chute stepper lead]({{ '/hardware/helpers/chute-stepper-lead/' | relative_url }}).

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Source of truth is the basically board v1.3 pinout. Cable S plugs into the motor's own 6-position JST-PH socket, so the four board positions <code>1·2·3·4</code> land on motor positions <code>1·4·3·6</code> and motor positions 2 and 5 stay empty. The nets line up, the positions do not. Mark polarity on each of the 4 channel steppers, and <a href="{{ '/hardware/helpers/multimeter/' | relative_url }}#resistance-for-finding-a-steppers-coils">check the coils with a multimeter</a> first.</p>
</div>

{% include harness/pin-swap.html %}

Which socket drives which motor is on [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 2, and the driver beside each socket is addressed in [preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}), step 3.
