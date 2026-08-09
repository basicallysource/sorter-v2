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
    <tr><td class="wire-id">PSU-J</td><td>3</td><td>18 AWG</td><td>4 in</td><td>2</td><td>2× insulated spade/fork terminal, M3.5, 8 mm wide max (PSU screws 7/4, 8/5, 9/6)</td><td>Panel-mount female DC jack 5.5×2.1</td><td>Lives inside the PSU box. Usually comes already attached to the jack, so buy the jacks with leads</td></tr>
    <tr><td class="wire-id">W1</td><td>1</td><td>18 AWG</td><td>36 in</td><td>2</td><td>Male DC plug 5.5×2.1</td><td>JST VHR-2 + SVH-21T-P1.1 contacts</td><td>Board 24V in. Pin 1 = +24V <span class="flagged">verify silkscreen</span></td></tr>
    <tr><td class="wire-id">W2</td><td>1</td><td>22 AWG</td><td>12 in</td><td>2</td><td>Male DC plug 5.5×2.1</td><td>Male DC plug 5.5×2.1</td><td>USB hub. Double-male, center-positive both ends <span class="flagged">verify hub jack size</span></td></tr>
    <tr><td class="wire-id">W3</td><td>1</td><td>22 AWG</td><td>6 in</td><td>2</td><td>Male DC plug 5.5×2.1</td><td>Bare, tinned</td><td>Splice to USB-C buck input leads</td></tr>
    <tr><td class="wire-id">L1-L3</td><td>3</td><td>22 AWG</td><td>36 in</td><td>2</td><td>Dupont 1x2 female (2.54 mm)</td><td>Female inline DC jack 5.5×2.1</td><td>LED feed from board to unplug point</td></tr>
    <tr><td class="wire-id">L1p, L2p</td><td>2</td><td>22 AWG</td><td>6 in</td><td>2</td><td>Male DC plug 5.5×2.1</td><td>Bare, tinned</td><td>Solder to COB board pads</td></tr>
    <tr><td class="wire-id">L3p</td><td>1</td><td>22 AWG</td><td>6 in</td><td>2</td><td>Male DC plug 5.5×2.1</td><td>Bare, tinned</td><td>Into a solderless clamp-on strip connector (6000K strip)</td></tr>
    <tr><td class="wire-id">LIM</td><td>1</td><td>22 AWG</td><td>24 in</td><td>2</td><td>Dupont 1x3 female (2.54 mm), position 3 empty</td><td>2× insulated quick-connect receptacle, #187</td><td>Pushes onto the switch tabs, no soldering. Empty third position keys the board end</td></tr>
    <tr><td class="wire-id">S1-S4</td><td>4</td><td>24 AWG</td><td>1 m</td><td>4</td><td>JST PHR-4 + SPH-002T contacts</td><td>JST PHR-6 + SPH-002T contacts</td><td>Crossover cable, pin map 3.2. Into the motor's own 6-pin socket. 4-wire bundle in PVC sleeving</td></tr>
    <tr><td class="wire-id">CH</td><td>1</td><td>24 AWG</td><td>40 in <span class="flagged">guess</span></td><td>4</td><td>JST PHR-4 + SPH-002T contacts</td><td>Bare, tinned, 4 leads labeled 1-4</td><td>Splice to chute stepper flying leads, pin map 3.3</td></tr>
  </tbody>
</table>

<div class="callout">
  <span class="callout-icon" aria-hidden="true">›</span>
  <p><b>Steppers move to JST-PH.</b> This spec adopts the recommended change: stepper cables plug the board's <b>JST-PH 4-pin</b> jacks (J23, J27, J31, J35, J39) instead of dupont on the parallel pin headers. PH contacts accept 24-28 AWG, hence 24 AWG on S1-S4 and CH. The mains inlet wiring (18 AWG, 3-cond.) comes pre-made on the 3Dman inlet switch and is not part of this order. The 16-pin IDC ribbon is an off-the-shelf uxcell part: buy, don't build.</p>
</div>

## 3 &nbsp; Pin maps

### 3.1 &nbsp; 2-conductor power (PSU-J, W1-W3, L1-L3, pigtails)

Barrel jacks and plugs are **5.5 × 2.1 mm** everywhere, confirmed against the Waveshare hub (part DC-044 on their wiki). 5.5 × 2.5 also exists and does not mate, so specify 2.1 on every line. Center/tip = +24V (red), sleeve = GND (black). W1 board end: VH pin 1 = +24V, pin 2 = GND, <span class="flagged">verify against board silkscreen before ordering</span>. LED feed dupont: pin 1 = +24V, pin 2 = GND, same caveat.

### 3.2 &nbsp; Channel stepper cable S1-S4 (crossover)

The motor end is a 6-position housing with only 4 positions populated, so the four board positions land on motor 1, 4, 3 and 6. Motor positions 2 and 5 stay empty. The nets match end to end; the positions do not.

<table style="max-width:520px">
  <thead><tr><th>Board PHR-4 pos.</th><th>Net</th><th>Motor PHR-6 pos.</th><th>Color</th></tr></thead>
  <tbody>
    <tr><td>1</td><td>A2</td><td>1</td><td>blue</td></tr>
    <tr><td>2</td><td>A1</td><td>4</td><td>green</td></tr>
    <tr><td>3</td><td>B1</td><td>3</td><td>red</td></tr>
    <tr><td>4</td><td>B2</td><td>6</td><td>black</td></tr>
    <tr><td>—</td><td>—</td><td>2, 5</td><td>unpopulated</td></tr>
  </tbody>
</table>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>For the vendor, explicitly:</b> this is NOT a straight-through cable, and the two ends have a different number of positions. Board 1→motor 1, board 2→motor 4, board 3→motor 3, board 4→motor 6. Motor positions 2 and 5 are left empty.</p>
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
- **Chute stepper** (CH): flying leads out of the motor, so splice.
- **COB boards** (L1p, L2p): solder pads, so solder direct.
- **LED strip** (L3p): a solderless clamp-on connector bites onto the cut strip, so no soldering. Pick the variant with IDC crimp points on both sides and it takes the pigtail wire too.

<div class="callout">
  <span class="callout-icon" aria-hidden="true">›</span>
  <p><b>Splice spec:</b> solder splice plus adhesive-lined heat shrink, one sleeve per conductor plus an overall sleeve. No twist-and-tape, no inline lever nuts.</p>
</div>

## 5 &nbsp; Connector BOM

Genuine JST part numbers given where they exist. Chinese-clone equivalents of all of these are fine for a vendor quote.

<table>
  <thead><tr><th>Connector</th><th>Housing</th><th>Contacts</th><th>Used on</th></tr></thead>
  <tbody>
    <tr><td>JST VH 2-pin</td><td>VHR-2</td><td>SVH-21T-P1.1 (16-22 AWG)</td><td>W1 board end</td></tr>
    <tr><td>JST PH 4-pin</td><td>PHR-4</td><td>SPH-002T-P0.5S (24-28 AWG)</td><td>S1-S4, CH board ends</td></tr>
    <tr><td>JST PH 6-pin</td><td>PHR-6</td><td>SPH-002T-P0.5S (24-28 AWG)</td><td>S1-S4 motor end, into the NEMA 17 socket</td></tr>
    <tr><td>Dupont 1x2 female, 2.54 mm</td><td colspan="2">generic dupont housing + female crimps (any vendor stocks these)</td><td>L1-L3 board ends</td></tr>
    <tr><td>Dupont 1x3 female, 2.54 mm</td><td colspan="2">generic housing + female crimps, only 2 positions populated</td><td>LIM board end (the empty position keys it)</td></tr>
    <tr><td>Quick-connect receptacle, #187</td><td colspan="2">fully insulated female, 4.75 × 0.5 mm (.187 × .020 in) tab, 22 AWG</td><td>LIM switch end (Omron V-155-1C25)</td></tr>
    <tr><td>DC barrel male 5.5×2.1</td><td colspan="2">moulded plug w/ lead, or field-installable</td><td>W1-W3, L pigtails</td></tr>
    <tr><td>DC barrel female inline 5.5×2.1</td><td colspan="2">moulded inline jack</td><td>L1-L3 unplug points</td></tr>
    <tr><td>DC barrel female panel-mount 5.5×2.1</td><td colspan="2">panel-mount jack, ≥5 A</td><td>PSU box outputs J1-J3</td></tr>
    <tr><td>Spade/fork terminal, insulated</td><td colspan="2">18 AWG, M3.5 stud, 8 mm wide max, must fit the LRS-350-24 terminal block (screws 4-6 are -V, 7-9 are +V)</td><td>PSU-J</td></tr>
  </tbody>
</table>

## 6 &nbsp; How to order this

- **Custom harness vendor** (Alibaba "custom cable assembly", or a US quick-turn shop): send them sections 1-3 and 5 as the drawing. Expect MOQ 50-100 pcs per line item from China; small US shops and some AliExpress custom-cable storefronts will do 5-10.
- **Low volume alternative:** buy pre-crimped PH / XH / dupont leads plus housings and assemble. The only labor a vendor saves is crimping.
- The rationale for every guess in this spec: steppers draw ≤1.5 A/phase (24 AWG ok at these lengths), no single barrel-plug load exceeds ~3 A (22 AWG ok), PSU box pigtails carry worst-case single-load current (18 AWG).
- The 24V distribution feeds three loads: the board, the USB hub, and the Orange Pi buck. The cooling fans are not on it, they run off the Pi or the board.

## 7 &nbsp; Guesses to verify before sending

1. **Board 24V input polarity:** which pin is +24V. The connector itself is settled as VH (VHR-2, 18 AWG).
2. **Chute stepper cable:** 40 in copied from the channel steppers, and it is not covered by Jon's drawing at all.
3. **LED drop count:** 3 feeds + 3 pigtails, per the schedule. Re-count against the machine.
4. **Motor coil order:** the 1·4·3·6 map and the two empty positions come from Jon's drawing, not from a measurement. Check the coils with a multimeter first.
5. **Limit switch contact:** the switch (Omron V-155-1C25) is SPDT with three tabs and the harness lands on two. Confirm which pair, COM+NC or COM+NO, against the board.
