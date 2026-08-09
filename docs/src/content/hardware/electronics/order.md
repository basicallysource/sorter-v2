---
layout: default
title: Order spec
type: reference
section: hardware
slug: electronics-order-spec
kicker: Electronics — Order spec
lede: Order-ready cable build list for a custom harness vendor.
permalink: /hardware/electronics/order/
last_verified: 2026-07-12
---

Every TBD from the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page is filled in with a stated guess. Lengths are kept deliberately long; if a cable comes back a little wrong we iterate. IDs match the wire schedule.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Guesses inside.</b> Gauges, connector part numbers, and the chute stepper length are engineering guesses, not measurements. They are conservative and safe to order against. Verify list in section 7.</p>
</div>

## 1 &nbsp; Global spec

<dl class="spec-list">
  <dt>Wire</dt><dd>UL1007 stranded, 300V, tinned copper</dd>
  <dt>Gauges</dt><dd>18 AWG (PSU box internals) · 22 AWG (all barrel-plug 24V runs, LED feeds, limit switch) · 24 AWG (stepper cables, set by the JST-PH contact limit)</dd>
  <dt>Colors</dt><dd>Red = +24V, black = GND on all 2-conductor power cables. Steppers: see pin maps, section 3.</dd>
  <dt>Barrel jacks</dt><dd>5.5 mm OD × 2.1 mm ID, center-positive, rated ≥5 A</dd>
  <dt>Length tolerance</dt><dd>±10 mm (±25 mm fine on anything ≥36 in)</dd>
  <dt>Bare ends</dt><dd>Strip 5 mm, tin</dd>
  <dt>Labeling</dt><dd>Each cable labeled with its ID (W1, S1…) on a flag label near end A</dd>
  <dt>Order quantity</dt><dd>2 full sets recommended, because lengths are guesses and spares are cheap</dd>
</dl>

## 2 &nbsp; Cable build list

One row = one buildable cable SKU. End A is the PSU/board side. "Bare" ends are for parts the vendor cannot terminate (section 4).

<table>
  <thead><tr><th>ID</th><th>Qty</th><th>Gauge</th><th>Length</th><th>Cond.</th><th>End A</th><th>End B</th><th>Notes</th></tr></thead>
  <tbody>
    <tr><td class="wire-id">PSU-J</td><td>6</td><td>18 AWG</td><td>4 in</td><td>2</td><td>2× insulated fork terminal (PSU output screws)</td><td>Panel-mount female DC jack 5.5×2.1</td><td>Lives inside the PSU box</td></tr>
    <tr><td class="wire-id">W1</td><td>1</td><td>22 AWG</td><td>36 in</td><td>2</td><td>Male DC plug 5.5×2.1</td><td>JST XHP-2 + SXH-001T contacts</td><td>Board 24V in. Pin 1 = +24V <span class="flagged">verify silkscreen</span></td></tr>
    <tr><td class="wire-id">W2</td><td>1</td><td>22 AWG</td><td>12 in</td><td>2</td><td>Male DC plug 5.5×2.1</td><td>Male DC plug 5.5×2.1</td><td>USB hub. Double-male, center-positive both ends <span class="flagged">verify hub jack size</span></td></tr>
    <tr><td class="wire-id">W3</td><td>1</td><td>22 AWG</td><td>6 in</td><td>2</td><td>Male DC plug 5.5×2.1</td><td>Bare, tinned</td><td>Splice to USB-C buck input leads</td></tr>
    <tr><td class="wire-id">W4, W5</td><td>2</td><td>22 AWG</td><td>36 in</td><td>2</td><td>Male DC plug 5.5×2.1</td><td>Bare, tinned</td><td>Splice to fan leads (cut off the fan's XH plug)</td></tr>
    <tr><td class="wire-id">L1-L3</td><td>3</td><td>22 AWG</td><td>36 in</td><td>2</td><td>Dupont 1x2 female (2.54 mm)</td><td>Female inline DC jack 5.5×2.1</td><td>LED feed from board to unplug point</td></tr>
    <tr><td class="wire-id">L1p, L2p</td><td>2</td><td>22 AWG</td><td>6 in</td><td>2</td><td>Male DC plug 5.5×2.1</td><td>Bare, tinned</td><td>Solder to COB board pads</td></tr>
    <tr><td class="wire-id">L3p</td><td>1</td><td>22 AWG</td><td>6 in</td><td>2</td><td>Male DC plug 5.5×2.1</td><td>Bare, tinned</td><td>Solder to LED strip (6000K) pads</td></tr>
    <tr><td class="wire-id">LIM</td><td>1</td><td>22 AWG</td><td>24 in</td><td>2</td><td>Dupont 1x2 female (2.54 mm)</td><td>Bare, tinned</td><td>Solder to limit switch lugs</td></tr>
    <tr><td class="wire-id">S1-S4</td><td>4</td><td>24 AWG</td><td>40 in</td><td>4</td><td>JST PHR-4 + SPH-002T contacts</td><td>XH2.54 4-pin inline male</td><td>Crossover cable, pin map 3.2. Mates the StepperOnline motor lead</td></tr>
    <tr><td class="wire-id">CH</td><td>1</td><td>24 AWG</td><td>40 in <span class="flagged">guess</span></td><td>4</td><td>JST PHR-4 + SPH-002T contacts</td><td>Bare, tinned, 4 leads labeled 1-4</td><td>Splice to chute stepper flying leads, pin map 3.3</td></tr>
  </tbody>
</table>

<div class="callout">
  <span class="callout-icon" aria-hidden="true">›</span>
  <p><b>Steppers move to JST-PH.</b> This spec adopts the recommended change: stepper cables plug the board's <b>JST-PH 4-pin</b> jacks (J23, J27, J31, J35, J39) instead of dupont on the parallel pin headers. PH contacts accept 24-28 AWG, hence 24 AWG on S1-S4 and CH. The mains inlet wiring (18 AWG, 3-cond.) comes pre-made on the 3Dman inlet switch and is not part of this order. The 16-pin IDC ribbon is an off-the-shelf uxcell part: buy, don't build.</p>
</div>

## 3 &nbsp; Pin maps

### 3.1 &nbsp; 2-conductor power (PSU-J, W1-W5, L1-L3, pigtails)

Barrel jacks and plugs: center/tip = +24V (red), sleeve = GND (black). W1 board end: XH pin 1 = +24V, pin 2 = GND, <span class="flagged">verify against board silkscreen before ordering</span>. LED feed dupont: pin 1 = +24V, pin 2 = GND, same caveat.

### 3.2 &nbsp; Channel stepper cable S1-S4 (crossover)

The inner-two swap lives in this cable. Colors follow the StepperOnline convention at the motor end, so colors line up straight where the cable mates the motor's shipped XH lead; the crossover is visible at the board end.

<table style="max-width:520px">
  <thead><tr><th>Board PH pin</th><th>Net</th><th>Motor XH pin</th><th>Color</th></tr></thead>
  <tbody>
    <tr><td>1</td><td>A2</td><td>1</td><td>black</td></tr>
    <tr><td>2</td><td>A1</td><td>3</td><td>red</td></tr>
    <tr><td>3</td><td>B1</td><td>2</td><td>green</td></tr>
    <tr><td>4</td><td>B2</td><td>4</td><td>blue</td></tr>
  </tbody>
</table>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>For the vendor, explicitly:</b> this is NOT a straight-through cable. Board pin 2 goes to motor pin 3, board pin 3 goes to motor pin 2. Pins 1 and 4 straight.</p>
</div>

### 3.3 &nbsp; Chute stepper cable CH (straight, bare end)

<table style="max-width:520px">
  <thead><tr><th>Board PH pin</th><th>Net</th><th>Coil</th><th>Color</th></tr></thead>
  <tbody>
    <tr><td>1</td><td>A2</td><td>A</td><td>black</td></tr>
    <tr><td>2</td><td>A1</td><td>A</td><td>green</td></tr>
    <tr><td>3</td><td>B1</td><td>B</td><td>red</td></tr>
    <tr><td>4</td><td>B2</td><td>B</td><td>blue</td></tr>
  </tbody>
</table>

Straight-through, coil pairs = 1-2 and 3-4. Identify the motor's coil pairs with a multimeter (a coil reads a few ohms, across coils reads open) before splicing. Swapping within a coil only flips direction.

### 3.4 &nbsp; Drawings (WireViz)

Rendered harness drawings, BOMs, downloads, and the full supplier package live on the [WireViz]({{ '/hardware/electronics/wireviz/' | relative_url }}) page. Every guessed value is marked **GUESS** in the drawings themselves.

## 4 &nbsp; Ends the vendor can't terminate

Some parts come with their own fixed leads or solder pads, so the harness can't fully land on them. Those cables are ordered with one end bare and tinned, and joined on the machine:

- **24V to 5V USB-C buck** (W3): converter has fixed input leads, so splice.
- **40mm fans** (W4, W5): ship with their own XH-terminated lead, so cut the plug off and splice.
- **Chute stepper** (CH): flying leads out of the motor, so splice.
- **COB boards / LED strip** (L1p-L3p): solder pads, so solder direct.
- **Limit switch** (LIM): solder lugs, so solder direct.

<div class="callout">
  <span class="callout-icon" aria-hidden="true">›</span>
  <p><b>Splice spec:</b> solder splice plus adhesive-lined heat shrink, one sleeve per conductor plus an overall sleeve. No twist-and-tape, no inline lever nuts.</p>
</div>

## 5 &nbsp; Connector BOM

Genuine JST part numbers given where they exist. Chinese-clone equivalents of all of these are fine for a vendor quote.

<table>
  <thead><tr><th>Connector</th><th>Housing</th><th>Contacts</th><th>Used on</th></tr></thead>
  <tbody>
    <tr><td>JST XH 2-pin</td><td>XHP-2</td><td>SXH-001T-P0.6 (22-28 AWG)</td><td>W1 board end</td></tr>
    <tr><td>JST PH 4-pin</td><td>PHR-4</td><td>SPH-002T-P0.5S (24-28 AWG)</td><td>S1-S4, CH board ends</td></tr>
    <tr><td>XH2.54 4-pin inline male</td><td colspan="2">clone part ("XH2.54 male wire housing"), no genuine JST wire-to-wire equivalent</td><td>S1-S4 motor end, mates the StepperOnline lead</td></tr>
    <tr><td>Dupont 1x2 female, 2.54 mm</td><td colspan="2">generic dupont housing + female crimps (any vendor stocks these)</td><td>L1-L3, LIM board ends</td></tr>
    <tr><td>DC barrel male 5.5×2.1</td><td colspan="2">moulded plug w/ lead, or field-installable</td><td>W1-W5, L pigtails</td></tr>
    <tr><td>DC barrel female inline 5.5×2.1</td><td colspan="2">moulded inline jack</td><td>L1-L3 unplug points</td></tr>
    <tr><td>DC barrel female panel-mount 5.5×2.1</td><td colspan="2">panel-mount jack, ≥5 A</td><td>PSU box outputs J1-J6</td></tr>
    <tr><td>Fork terminal, insulated</td><td colspan="2">22-16 AWG, sized for the LRS-350 output screws (M3.5, <span class="flagged">verify</span>)</td><td>PSU-J</td></tr>
  </tbody>
</table>

## 6 &nbsp; How to order this

- **Custom harness vendor** (Alibaba "custom cable assembly", or a US quick-turn shop): send them sections 1-3 and 5 as the drawing. Expect MOQ 50-100 pcs per line item from China; small US shops and some AliExpress custom-cable storefronts will do 5-10.
- **Low volume alternative:** buy pre-crimped PH / XH / dupont leads plus housings and assemble. The only labor a vendor saves is crimping.
- The rationale for every guess in this spec: steppers draw ≤1.5 A/phase (24 AWG ok at these lengths), no single barrel-plug load exceeds ~3 A (22 AWG ok), PSU box pigtails carry worst-case single-load current (18 AWG).

## 7 &nbsp; Guesses to verify before sending

1. **Board 24V input:** XH vs VH, and which pin is +24V. If it turns out VH, W1 becomes VHR-2N + SVH-21T-P1.1 contacts and can move up to 18 AWG.
2. **Board input current:** XH contacts are rated ~3 A. If all 5 steppers plus LEDs really run through W1 at once, that's tight, and would suggest the connector is actually VH.
3. **USB hub barrel size:** W2 assumes the Waveshare hub jack is 5.5×2.1. Could be 5.5×2.5.
4. **Chute stepper length:** 40 in copied from the channel steppers.
5. **LED drop count:** 3 feeds + 3 pigtails, per the schedule. Re-count against the machine.
6. **PSU screw size** for the fork terminals (assumed M3.5).
7. **J6** stays a spare output.
