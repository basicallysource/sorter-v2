---
layout: default
title: Wire harness
type: reference
section: hardware
slug: electronics-wire-harness
kicker: Electronics — Wire harness
lede: 24V power distribution from the PSU, plus everything connected to basically board v1.3.
permalink: /hardware/electronics/
author: spencer
contributors: [effreek]
last_verified: 2026-07-12
---

Wire IDs match the schedule tables. Open items are in section 7.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>These electronics pages are working notes right now, not finished documentation.</b> The harness is actively being specced, so parts of this change week to week and some of it contradicts what a machine already built looks like. Anything still undecided is written down as an open item in section 7 rather than smoothed over. Started from Basically's own working notes as of July 12th 2026; treat it as the current thinking, not the final state.</p>
</div>

This page is the wiring. Where the PSU, the control board and the Orange Pi physically mount is [Installing the electronics]({{ '/hardware/electronics/installation/' | relative_url }}).

## 1 &nbsp; Power supply

<dl class="spec-list">
  <dt>Model</dt><dd>MEAN WELL LRS-350-24</dd>
  <dt>Output</dt><dd>24V, 14.6A, 350.4W, single output</dd>
  <dt>Enclosure</dt><dd>Custom 3D-printed box, fused AC input</dd>
  <dt>Terminal block</dt><dd>9-position, MEAN WELL's own numbering: <b>1</b> AC/L, <b>2</b> AC/N, <b>3</b> FG, <b>4-6</b> DC OUTPUT -V, <b>7-9</b> DC OUTPUT +V (LRS-350-SPEC)</dd>
  <dt>DC outputs</dt><dd>3 × female DC jack, each a 4 in 18 AWG pigtail with 2 × spade/fork terminals (M3.5, 8 mm wide max, Molex 0191310031 or equivalent). One pigtail per +V/-V screw pair: 7 with 4, 8 with 5, 9 with 6</dd>
  <dt>AC input</dt><dd>Screws 1, 2, 3. Fed by the fused IEC inlet switch's own pre-terminated leads, so there is no cable to make</dd>
  <dt>Loads</dt><dd>basically board v1.3, the USB hub, and the Orange Pi buck converter. One jack each, no spare</dd>
  <dt>Not on this bus</dt><dd>The cooling fans. They run off the Orange Pi or basically board v1.3 instead. Both boards supply 5V natively: the OPi's 26-pin header (pins 2 and 4), or board v1.3's empty <code>J16</code> socket (pin 2). Either is a plug-in connection, no soldering needed. They are still needed: the Pi and the board end up in a box with no airflow but the fan. See <a href="#7--open-items">open items</a></dd>
</dl>

## 2 &nbsp; Component layout

<figure class="harness-figure">
  <img src="https://assets.basically.website/sorter-docs/electronics-component-layout-topdown-full-2d38b86c4b2e.jpg" alt="Top-down physical component layout on the machine, with the PSU, Pi, basically board, USB hub, Pico, chute stepper and ribbon run called out">
  <figcaption>Physical placement on the machine (top-down): PSU, Orange Pi, basically board v1.3, USB hub, Pico, the chute stepper and its limit switch, and the ribbon run. <cite>Rendered from the layout, not a photo. Render: Spencer.</cite></figcaption>
</figure>

## 3 &nbsp; Interconnect diagram

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
        <text x="154" y="194">J1</text><text x="154" y="364">J2</text><text x="154" y="414">J3</text>
      </g>
      <text x="262" y="80" font-size="13" font-weight="700" fill="var(--ink)">basically board</text>
      <text x="262" y="96" font-size="12" font-weight="700" fill="var(--ink)">v1.3</text>
      <text x="262" y="118" font-size="10.5" fill="var(--muted)">hub for LEDs, sensors,</text>
      <text x="262" y="132" font-size="10.5" fill="var(--muted)">steppers, servo adapters</text>
      <text x="262" y="184" font-size="9.5" fill="var(--muted)">24V in: JST-VH female</text>
      <g font-size="11" fill="var(--ink)" text-anchor="middle">
        <text x="207" y="184">W1 · 36 in</text>
        <text x="207" y="354">W2 · 12 in</text>
        <text x="207" y="404">W3 · 6 in</text>
      </g>
      <g font-size="10" fill="var(--primary)" font-style="italic" text-anchor="middle">
        <text x="207" y="203">too long</text>
      </g>
      <g font-size="10.5" fill="var(--ink)" text-anchor="middle">
        <text x="535" y="48">L1 · 2x1 dupont · 36+6 in</text>
        <text x="535" y="93">L2 · 2x1 dupont · 36+6 in</text>
        <text x="535" y="143">L3 · 2x1 dupont · 36+6 in</text>
        <text x="535" y="188">limit · 2x1 dupont</text>
        <text x="535" y="233">S1-4 · JST-PH 4-pin · 1 m</text>
        <text x="535" y="283">CH · 4x1 dupont · flying leads</text>
        <text x="535" y="328">RIB · 16-pin IDC · 1 m</text>
      </g>
      <g font-size="11" font-weight="700" fill="var(--ink)">
        <text x="258" y="364">Waveshare 4-port USB hub</text>
        <text x="258" y="414">Orange Pi 5</text>
      </g>
      <g font-size="12" font-weight="700" fill="var(--ink)">
        <text x="652" y="55">COB board</text>
        <text x="652" y="105">COB board</text>
        <text x="652" y="155">LED strip (6000K)</text>
        <text x="652" y="205">Limit switch</text>
        <text x="652" y="255">Stepper, channels 1-4 (×4)</text>
        <text x="652" y="305">Chute stepper</text>
        <text x="652" y="355">Servo adapter board (first)</text>
      </g>
    </svg>
  </div>
  <figcaption>PSU distributes 24V to basically board v1.3 (through a JST-VH inlet) and the two other direct loads (USB hub, Orange Pi buck). Cooling fans are not on this bus, they run off the Pi or the board. basically board v1.3 then drives the LED drops (L1-L3), the limit switch, the steppers, and the first servo adapter board over a 16-pin IDC ribbon. Wire IDs match the schedule below.</figcaption>
</figure>

### 3.1 &nbsp; Stepper polarity

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Source of truth is the basically board v1.3 pinout. Cable S plugs into the motor's own 6-position JST-PH socket, so the four board positions <code>1·2·3·4</code> land on motor positions <code>1·4·3·6</code> and motor positions 2 and 5 stay empty. The nets line up, the positions do not. Mark polarity on each of the 4 channel steppers, and check the coils with a multimeter first.</p>
</div>

Full basically board v1.3 pinout (J23-J40), connector-to-connector mapping, and connector reference: [stepper connectors]({{ '/hardware/electronics/steppers/' | relative_url }}).

{% include harness/pin-swap.html %}

## 4 &nbsp; Wire schedule

### 4.1 &nbsp; PSU assembly (enclosure)

The PSU box is an assembly: the MEAN WELL LRS-350-24, a fused mains inlet switch, and 6 DC output jacks, in a 3D-printed enclosure. These are the wires inside that box. Enclosure CAD: [Onshape](https://cad.onshape.com/documents/ff3546ceb03f5fc907e6ed4c/v/f06d891a27f145d952ee5678/e/b9f80b00e4dd34407e23b560).

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Before making or checking any of these connections, unplug the PSU from the wall. Screws 1-3 on the terminal block carry live mains voltage whenever the unit is plugged in.</p>
</div>

<table>
  <thead><tr><th>Segment</th><th>From</th><th>To</th><th>Cond.</th><th>Length</th><th>Gauge</th></tr></thead>
  <tbody>
    <tr><td>Mains inlet</td><td>Fused inlet switch (3Dman, 10A fuse)</td><td>PSU AC input (L / N / earth)</td><td>3</td><td>-</td><td>18 AWG</td></tr>
    <tr><td>DC output jacks (×3)</td><td>PSU screws 7/4, 8/5, 9/6 — 2× spade/fork terminal (M3.5, 8 mm max)</td><td>Female DC jack</td><td>2</td><td>4 in</td><td>18 AWG</td></tr>
  </tbody>
</table>

### 4.2 &nbsp; Loads on the PSU (24V)

A male DC barrel plug on each wire mates one of the PSU output jacks (J1-J3).

<table>
  <thead><tr><th>ID</th><th>Load</th><th>From</th><th>To</th><th>Cond.</th><th>Length</th><th>Gauge</th></tr></thead>
  <tbody>
    <tr><td class="wire-id">W1</td><td>basically board v1.3</td><td>PSU J1, male DC</td><td>JST-VH female (board 24V in)</td><td>2</td><td>36 in <span class="flagged">too long</span></td><td>TBD</td></tr>
    <tr><td class="wire-id">W2</td><td>Waveshare 4-port USB hub, 24V</td><td>PSU J2, male DC</td><td>Male DC (hub)</td><td>2</td><td>12 in</td><td>TBD</td></tr>
    <tr><td class="wire-id">W3</td><td>Orange Pi 5</td><td>PSU J3, male DC</td><td>24V-5V USB-C buck</td><td>2</td><td>6 in</td><td>TBD</td></tr>
  </tbody>
</table>

Three outputs, three loads, no spare. The cooling fans are deliberately not on this bus.

### 4.3 &nbsp; LEDs (from basically board v1.3)

Each LED drop is two segments: a 2x1 dupont feed from the board to a female DC jack (the unplug point), then a 6 in male-DC pigtail into the module. The strip end uses a solderless clamp-on connector rather than soldering to pads.

<table>
  <thead><tr><th>ID</th><th>Segment</th><th>From</th><th>To</th><th>Cond.</th><th>Length</th></tr></thead>
  <tbody>
    <tr><td class="wire-id">L1</td><td>COB board feed</td><td>2x1 dupont (board)</td><td>Female DC jack</td><td>2</td><td>36 in</td></tr>
    <tr><td class="wire-id">L1p</td><td>COB board pigtail</td><td>Male DC jack</td><td>COB board</td><td>2</td><td>6 in</td></tr>
    <tr><td class="wire-id">L2</td><td>COB board feed</td><td>2x1 dupont (board)</td><td>Female DC jack</td><td>2</td><td>36 in</td></tr>
    <tr><td class="wire-id">L2p</td><td>COB board pigtail</td><td>Male DC jack</td><td>COB board</td><td>2</td><td>6 in</td></tr>
    <tr><td class="wire-id">L3</td><td>LED strip feed</td><td>2x1 dupont (board)</td><td>Female DC jack</td><td>2</td><td>36 in</td></tr>
    <tr><td class="wire-id">L3p</td><td>LED strip pigtail</td><td>Male DC jack</td><td>LED strip (6000K)</td><td>2</td><td>6 in</td></tr>
  </tbody>
</table>

<div class="callout">
  <span class="callout-icon" aria-hidden="true">›</span>
  <p>LED strip for the classification channel is <b>6000K</b>. Length: 2× revolutions around the classification channel inner tube = 108.400 mm × 2, so roughly 220 mm.</p>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Every COB board needs a current-limiting resistor in series, one per board.</b> The 50 mm COB plates have no current limiting of their own. Wired straight to 24V a plate pulls about 0.5A (12W), runs far hotter than it needs to, and melts its printed mount. Two boards sharing one resistor is not enough; give each its own. <b>This does not apply to the LED strip</b> (L3), which has current limiting built in (Jon, 2026-08-17 and 2026-08-19).</p>
</div>

<dl class="spec-list">
  <dt>Fit your own</dt><dd><b>220&#8486;</b>, <b>1/4 W</b>, in series, one per COB board. That is what Basically settled on for the C-channel plates and the classification chamber, and what Jon recommends. <b>200&#8486;</b> is the ballpark given to people whose lights are overheating</dd>
  <dt>On basically board v1.3</dt><dd>Already fitted, so a COB board fed from the board needs nothing added. <b>180&#8486;</b>, 1206, 250 mW, 1% (LCSC C17924) in series with the +24V feed to each of the four LED headers: R21 on J8, R22 on J9, R27 on J10, R28 on J11. Each has a solder jumper next to it (JP1-JP4) that bridges the resistor out. On the strip channel the resistor is not strictly required, and brightness can be trimmed with PWM instead (Jon, 2026-08-19)</dd>
  <dt>Effect</dt><dd>Draw drops from ~0.5A to ~0.1A. Still bright enough for the camera, per the C-channel testing in Feb 2026</dd>
</dl>

<p>Sources, since this has been asked several times: #c-channels 2026-02-13 (&ldquo;went for 220ohm resistor&rdquo;), the classification chamber thread 2026-03-22 (&ldquo;220 ohm&rdquo;), and #machine-setup-help 2026-05-13 (&ldquo;They need resistor. Ballpark of 200ohm is good&rdquo;, in series, 1/4 W) after a builder's C-channel COB mount started melting after a minute; Jon in #electronics 2026-08-17 and 2026-08-19.</p>

### 4.4 &nbsp; Sensors and steppers (from basically board v1.3)

<table>
  <thead><tr><th>ID</th><th>Segment</th><th>From</th><th>To</th><th>Cond.</th><th>Length</th></tr></thead>
  <tbody>
    <tr><td class="wire-id">LIM</td><td>Limit switch (Omron V-155-1C25)</td><td>basically board v1.3, 1x3 dupont (position 3 empty)</td><td>#187 quick-connect, push-on</td><td>2</td><td>24 in</td></tr>
    <tr><td class="wire-id">S1-4</td><td>Stepper, channels 1-4 (×4)</td><td>basically board v1.3, JST-PH 4-pin (PHR-4)</td><td>Stepper, JST-PH 6-pin (PHR-6), positions 1·4·3·6</td><td>4</td><td>1 m</td></tr>
    <tr><td class="wire-id">CH</td><td>Chute stepper</td><td>basically board v1.3, JST-PH 4-pin (PHR-4)</td><td>Chute stepper, flying leads, needs prep</td><td>4</td><td>40 in <span class="flagged">guess</span></td></tr>
  </tbody>
</table>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Done, and here is why:</b> the stepper cables are JST-PH 4-pin at the board, not 4x1 dupont. Dupont contacts do not take side load. The wires leave at an angle, that depresses the spring contact, the connection goes loose, resistance goes up and it heats. Two of these have already burned up on real machines. JST-PH takes the side load without damage.</p>
</div>

### 4.5 &nbsp; Servo adapter (ribbon)

<table>
  <thead><tr><th>ID</th><th>Segment</th><th>From</th><th>To</th><th>Cond.</th><th>Length</th></tr></thead>
  <tbody>
    <tr><td class="wire-id">RIB</td><td>Ribbon cable</td><td>basically board v1.3, 16-pin IDC (FC)</td><td>First servo adapter board, 16-pin IDC (FC)</td><td>16</td><td>1 m</td></tr>
  </tbody>
</table>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/electronics-idc-ribbon-16pin-full-21fee4f419fb.jpg" alt="uxcell 16-pin IDC flat ribbon cable, gray, with FC connectors at both ends">
  <figcaption><cite>Manufacturer product photo (uxcell), not a Basically photo.</cite></figcaption>
</figure>

## 5 &nbsp; Parts

- MEAN WELL LRS-350-24, 350.4W 24V 14.6A single output &middot; [link](https://www.amazon.com/dp/B013ETVO12)
- 3Dman fused mains inlet switch, 15A 250V rocker + 10A fuse, 3-pin, 18 AWG &middot; [link](https://www.amazon.com/dp/B07RQV2NPN)
- DC 12V/24V to 5V USB-C buck converter, 5A 25W, powers Orange Pi 5 &middot; [link](https://www.amazon.com/dp/B0FV3P6KLS)
- Current-limiting resistor for any COB board not fed through basically board v1.3: 220&#8486;, 1/4 W, one per board. The board's own LED headers already have theirs (see 4.3). The LED strip does not need one
- Cooling fan, 40×40×10mm, 5V &middot; two of them, one per box (Orange Pi 26-pin header pins 2/4, board v1.3's `J16` pin 2 — see open items). Not on the 24V bus.
- uxcell 16-pin IDC flat ribbon cable, FC/FC, 2.54 mm, 1 m, gray &middot; [link](https://www.amazon.com/dp/B07S2W4N9T)
- Waveshare 4-port USB hub, 24V model (USB 3.2 version, not the 5V industrial one, which cannot take 24V in)
- Orange Pi 5
- USB cables, Pi to hub and hub to Pico: 3 ft or shorter is plenty, but they must be data cables. A lot of short USB cables are power-only.

## 6 &nbsp; Connector and terminal types

- Fused IEC inlet switch, 3-pin (L / N / earth): PSU mains inlet
- Fork / screw terminal: PSU 24V output to the DC jacks
- DC barrel jack, female: PSU outputs, LED unplug junctions
- DC barrel jack, male: load pigtails, LED pigtails
- JST-VH female (VHR-2): basically board v1.3 24V input (W1)
- 2x1 dupont (2.54 mm): LED drops (L1-L3)
- 1x3 dupont (2.54 mm), 2 positions populated: limit switch board end, keyed so it cannot go on backwards
- Quick-connect receptacle, #187 (4.75 × 0.5 mm tab), fully insulated: limit switch end. The switch is an Omron V-155-1C25, SPDT, so it has three tabs and the harness uses two
- JST-PH 4-pin (PHR-4): steppers at the board, J23, J27, J31, J35, J39
- JST-PH 6-pin (PHR-6): the NEMA 17 motor socket, cable S motor end
- 16-pin IDC (FC), 2.54 mm: ribbon to first servo adapter board

## 7 &nbsp; Open items

1. **How the fans are powered — worked out from the v1.3 KiCad and the Orange Pi 5's own manual (2026-08-22).** Both boards can supply 5V natively, no soldering: on basically board v1.3, `J16` pin 2 is VSYS (~4.7V through the Pico's schottky) and pin 6 is GND, a pluggable dupont pair (this socket sits empty on assembled boards, the PCA9685 chip itself is soldered on). On the Orange Pi 5, the 26-pin header's pins 2 and 4 are both 5V, GND on 6/9/14/20/25 — the official manual documents running a 5V fan straight off this header, no PWM, live whenever USB-C power is present. Recommended size: **40×40×10mm 5V** (fits the OPi's RK3588 and covers the stepper-driver row; Noctua NF-A4x10 5V or a generic Sunon/Delta 4010 at ~0.05-0.1A, light enough for either board's 5V rail). Orient it to **blow in** (down onto the board), not exhaust, with low vents near the stepper row for the air to leave — impingement cools the drivers better and positive pressure keeps dust out except at the filtered intake. A 24V fan on either 5V rail is harmless but won't spin (most need roughly half their rated voltage to start); the reverse, a 5V fan on 24V, is instantly fatal, so key or label the plugs if both voltages exist on the bench at once.
2. **Lengths.** W1 is 36 in and longer than necessary. Pick a final length and cut.
3. **LED feed polarity.** Which dupont pin is +24V on `L1-L3`. The board's own 24V input is settled: JST-VH (VHR-2), pin 1 = +24V, pin 2 = GND.
4. **Missing LED wire(s).** Re-count the LED drops against the actual LEDs.
5. **Gauge per segment.** Current draw per load is needed to spec gauge.
6. **SKU reduction.** Once gauges are known, standardize on as few gauges and connector types as possible.

The [order spec]({{ '/hardware/electronics/order/' | relative_url }}) page fills these in with guesses (marked as guesses) for ordering purposes. Nothing there is confirmed.
