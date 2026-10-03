---
layout: default
title: Ordering the wire harness
type: reference
section: hardware
slug: parts-harness-order
kicker: Parts — Ordering the harness
lede: The pack you send a cable vendor. Every drawing on the machine with its bill of materials, the spec they build to, and the zip.
permalink: /hardware/parts/harness-order/
author: spencer
contributors: [effreek]
last_verified: 2026-10-03
---

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Not validated against a machine, and there are guesses in it.</b> Nothing here has been checked against the physical machine. Gauges, most lengths and several connector part numbers are engineering guesses, not measurements; they are conservative and safe to order against. Values marked <b>GUESS</b> in the drawings are guesses, and the ones that matter are listed at the bottom of this page.</p>
</div>

This is the only page that carries the harness drawings. Everywhere else on the site links here, so a cable is drawn once and a redrawn harness updates in one place.

**You do not have to order the harness.** Every cable can be bought ready made or built on the bench, and the four you build have their own pages under [Helpers]({{ '/hardware/helpers/' | relative_url }}). This page is for having the set made in one go.

<p class="download-line">
  <a href="{{ site.data.harness.zip }}" download><b>↓ sorter-v2-harness-rfq.zip</b></a>
  <span>cover sheet + every drawing (PDF/PNG/SVG/HTML) + a BOM per drawing (TSV) + WireViz YAML sources</span>
</p>

## Global spec

What every cable is built to, whoever builds it.

<dl class="spec-list">
  <dt>Wire</dt><dd>UL1007 stranded, 300 V, tinned copper</dd>
  <dt>Gauges</dt><dd>18 AWG (0.82 mm²) (PSU box internals) · 22 AWG (0.33 mm²) (all barrel-plug 24 V runs, LED feeds, limit switch) · 24 AWG (0.20 mm²) (stepper cables, set by the JST-PH contact limit)</dd>
  <dt>Colours</dt><dd>Red = +24 V, black = GND on every 2-conductor power cable. Stepper colours are on the drawings.</dd>
  <dt>Barrel jacks and plugs</dt><dd><b>5.5 mm (0.217 in) outside, 2.1 mm (0.083 in) inside</b>, centre-positive, rated 5 A or better. Confirmed against the Waveshare hub (their part DC-044). 5.5 × 2.5 mm (0.217 × 0.098 in) exists, looks identical and does not mate, so put 2.1 on every line of the order.</dd>
  <dt>Length tolerance</dt><dd>±10 mm (±0.4 in), and ±25 mm (±1 in) is fine on anything 914 mm (36 in) or longer</dd>
  <dt>Bare ends</dt><dd>Strip 5 mm (0.2 in), tin</dd>
  <dt>Labelling</dt><dd>Each cable labelled with its ID from the schedule below (<code>W2</code>, <code>S1</code>…) on a flag label near end A, which is the left-hand end in the schedule. <b>S1 to S4 are labelled at both ends</b>: four identical cables land within inches of each other at the board and at the motors, and they cannot be told apart once unplugged. Printed wrap-around laser labels or printed heat shrink are both fine.</dd>
  <dt>Acceptance test</dt><dd>100% continuity, every conductor, end to end. On <code>S1</code> to <code>S4</code> that means checking the position map in the pin map below, not just that each wire arrives. No hipot. No UL listing or IPC class is asked for at this stage.</dd>
  <dt>Packaging</dt><dd>One bag per cable type, ID on the bag</dd>
  <dt>Parts and brands</dt><dd>Any RoHS-compliant equivalent of the connectors in the connector table is acceptable if it mates and crimps the same. The part numbers there are the ones the machine was designed against.</dd>
  <dt>Order quantity</dt><dd>2 full sets, because the lengths are guesses and spares are cheap. Treat them as the sample run.</dd>
</dl>

## Cable schedule

Every cable and lead in the machine, one row each, with its ID. The IDs are the same on the drawings, on the [wire harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) page and on the labels, so a cable keeps one name everywhere. Socket references (<code>J1</code>, <code>J27</code>…) are the sockets on basically board v1.3, and a socket on a layer board is named as such. <b>End A</b> is the end that gets the label.

<table>
  <thead><tr><th>ID</th><th>Qty</th><th>End A</th><th>End B</th><th>Length</th><th>Wire</th><th>Route</th></tr></thead>
  <tbody>
    <tr><td class="wire-id">PJ1, PJ2, PJ3</td><td>3</td><td>Panel-mount DC jack, female, on the PSU box plate</td><td>Two insulated M3.5 fork terminals, onto the PSU's paired screws (7+4, 8+5, 9+6)</td><td>100 mm (4 in)</td><td>18 AWG (0.82 mm²), red and black</td><td>Vendor, or <a href="{{ '/hardware/helpers/psu-pigtail/' | relative_url }}">build</a></td></tr>
    <tr><td class="wire-id">W1</td><td>1</td><td>DC plug, male, into <code>PJ1</code></td><td>JST VHR-2 housing into board <code>J1</code>, pin 1 = +24 V, pin 2 = GND</td><td>914 mm (36 in)</td><td>18 AWG (0.82 mm²), red and black</td><td><a href="{{ '/hardware/helpers/board-24v-lead/' | relative_url }}">You build</a></td></tr>
    <tr><td class="wire-id">W2</td><td>1</td><td>DC plug, male, into <code>PJ2</code></td><td>Bare, tinned, into the USB hub's 2-pin 24 V terminal</td><td>305 mm (12 in), see guesses</td><td>22 AWG (0.33 mm²), red and black</td><td>Vendor</td></tr>
    <tr><td class="wire-id">W3</td><td>1</td><td>DC plug, male, into <code>PJ3</code></td><td>Bare, tinned, spliced to the buck converter's input leads</td><td>150 mm (6 in)</td><td>22 AWG (0.33 mm²), red and black</td><td>Vendor, or <a href="{{ '/hardware/helpers/pi-24v-lead/' | relative_url }}">build</a></td></tr>
    <tr><td class="wire-id">L1, L2, L3</td><td>3</td><td>2-position Dupont housing, 2.54 mm (0.1 in), into board <code>J8</code>, <code>J9</code>, <code>J10</code></td><td>Inline DC socket, female</td><td>914 mm (36 in)</td><td>22 AWG (0.33 mm²), red and black</td><td>Vendor</td></tr>
    <tr><td class="wire-id">L1p, L2p, L3p</td><td>3</td><td>DC plug, male, into the matching <code>L1</code> to <code>L3</code> socket</td><td>Bare, tinned, to the clamp-on connector on the LED strip</td><td>150 mm (6 in)</td><td>22 AWG (0.33 mm²), red and black</td><td>Vendor</td></tr>
    <tr><td class="wire-id">LIM</td><td>1</td><td>3-position Dupont housing into board <code>J5</code>: position 1 ground, position 2 signal, position 3 empty</td><td>Two insulated #187 quick-connect receptacles, onto the limit switch</td><td>610 mm (24 in)</td><td>22 AWG (0.33 mm²), any two colours</td><td>Vendor, or <a href="{{ '/hardware/helpers/limit-switch-lead/' | relative_url }}">build</a></td></tr>
    <tr><td class="wire-id">S1, S2, S3, S4</td><td>4</td><td>JST PHR-4 into board <code>J27</code>, <code>J31</code>, <code>J35</code>, <code>J39</code></td><td>JST PHR-6 into the motor's own socket, positions 1·4·3·6 (see the pin map)</td><td>1 m (39 in)</td><td>24 AWG (0.20 mm²), blue, green, red, black</td><td>Vendor</td></tr>
    <tr><td class="wire-id">CH</td><td>1</td><td>JST PHR-4 into board <code>J23</code></td><td>The chute motor's flying leads, spliced</td><td>610 mm (24 in)</td><td>24 AWG (0.20 mm²)</td><td><a href="{{ '/hardware/helpers/chute-stepper-lead/' | relative_url }}">You build</a></td></tr>
    <tr><td class="wire-id">RIB</td><td>1</td><td>16-pin IDC (2×8), female, into board <code>J17</code></td><td>16-pin IDC (2×8), female, into <code>J3</code> on the first layer board</td><td>1.2 to 1.5 m (47 to 59 in)</td><td>Flat ribbon</td><td>Buy</td></tr>
    <tr><td class="wire-id">U1</td><td>1</td><td>USB-A on the hub</td><td><code>UP USB3.0</code> on the Orange Pi</td><td>0.9 m (3 ft) or shorter</td><td>USB data cable</td><td>Buy</td></tr>
    <tr><td class="wire-id">U2</td><td>1</td><td>Micro USB on the Pico</td><td>USB-A on the hub</td><td>0.9 m (3 ft) or shorter</td><td>USB data cable</td><td>Buy</td></tr>
  </tbody>
</table>

That is 21 cables per machine, each with its own ID. 18 of them are in the zip, 16 of those are built by a vendor, and the other two (`W1`, `CH`) are built on the bench. `RIB`, `U1` and `U2` are bought. The three cameras use their own USB leads and are not scheduled. `U1` and `U2` are new IDs, given here so every cable in the machine has one; they must be real data cables, because a lot of short USB cables are power-only.

On `L1` to `L3`, the optional inline socket and the plug on `L1p` to `L3p` can be left out, in which case the feed runs straight to the strip and the pigtail is not needed. The plug and socket are recommended because they let the lamp be unplugged close to where it is.

## Connectors and terminals

What goes on the ends in the schedule. The part numbers are the ones the machine was designed against; where there is none, the spec is what to order to.

<table>
  <thead><tr><th>Where</th><th>Housing or part</th><th>Contact or crimp</th><th>Used on</th></tr></thead>
  <tbody>
    <tr><td>Board 24 V input</td><td>JST VHR-2N, 2-position</td><td>JST SVH-21T-P1.1</td><td><code>W1</code></td></tr>
    <tr><td>Stepper, board end</td><td>JST PHR-4, 4-position</td><td>JST SPH-002T-P0.5S</td><td><code>S1</code> to <code>S4</code>, <code>CH</code></td></tr>
    <tr><td>Stepper, motor end</td><td>JST PHR-6, 6-position, 4 populated</td><td>JST SPH-002T-P0.5S</td><td><code>S1</code> to <code>S4</code></td></tr>
    <tr><td>LED feeds, limit switch</td><td>Dupont housing, female, 2.54 mm (0.1 in): 2-position, and 3-position with 2 populated</td><td>Dupont female crimp contact, 2.54 mm (0.1 in). No part number yet.</td><td><code>L1</code> to <code>L3</code>, <code>LIM</code></td></tr>
    <tr><td>Limit switch</td><td>Fully insulated female quick-connect receptacle, #187 (4.75 × 0.5 mm, 0.187 × 0.020 in, tab), for 22 AWG (0.33 mm²). No part number yet.</td><td>Mates the Omron V-155-1C25</td><td><code>LIM</code></td></tr>
    <tr><td>DC plug</td><td>Barrel plug, male, 5.5 × 2.1 mm (0.217 × 0.083 in), centre-positive, 5 A or better. No part number yet.</td><td>Soldered or crimped per the vendor's process</td><td><code>W1</code> to <code>W3</code>, <code>L1p</code> to <code>L3p</code></td></tr>
    <tr><td>DC socket</td><td>Barrel socket, female, 5.5 × 2.1 mm (0.217 × 0.083 in), panel-mount on <code>PJ1</code> to <code>PJ3</code>, inline on <code>L1</code> to <code>L3</code>. No part number yet.</td><td>As above</td><td><code>PJ1</code> to <code>PJ3</code>, <code>L1</code> to <code>L3</code></td></tr>
    <tr><td>PSU terminal block</td><td>Insulated fork terminal, M3.5 stud, 8 mm (0.31 in) wide at most, for 18 AWG (0.82 mm²). No part number yet.</td><td>Crimp</td><td><code>PJ1</code> to <code>PJ3</code></td></tr>
    <tr><td>Ribbon</td><td>16-pin IDC (2×8), 2.54 mm (0.1 in), female, both ends</td><td>Pre-made, bought</td><td><code>RIB</code></td></tr>
    <tr><td>Bare ends</td><td>Strip 5 mm (0.2 in), tin</td><td>No connector</td><td><code>W2</code>, <code>W3</code>, <code>L1p</code> to <code>L3p</code></td></tr>
  </tbody>
</table>

The Dupont, quick-connect, barrel and fork-terminal rows have specs but no manufacturer part numbers yet. They are added as they are chosen, and the [parts catalog](https://parts-calculator.basically.website/hardware) carries each one with its per-machine count.

## How to order it

- **A custom harness vendor** (Alibaba "custom cable assembly", or a quick-turn shop): send them the zip. Expect MOQ 50 to 100 pieces per line item from China; small shops and some AliExpress custom-cable storefronts will do 5 to 10.
- **Low volume instead:** buy pre-crimped PH, XH and Dupont leads plus housings and assemble them. The only labour a vendor saves you is crimping.
- The reasoning behind the guessed gauges: steppers draw 1.5 A per phase or less, so 24 AWG (0.20 mm²) is fine at these lengths; no single barrel-plug load exceeds about 3 A, so 22 AWG (0.33 mm²) is fine; the PSU box pigtails carry worst-case single-load current, hence 18 AWG (0.82 mm²).

**Two things are not part of the order.** The mains inlet wiring comes pre-made on the 3Dman inlet switch, so there is no AC cable to have built. The 16-pin IDC ribbons are an off-the-shelf part: buy them, do not have them made.

## Ends the vendor cannot terminate

Some parts come with their own fixed leads or solder pads, so the harness cannot fully land on them. Those cables are ordered with one end bare and tinned, and joined on the machine.

- **24 V to 5 V USB-C buck** (`W3`): the converter has fixed input leads, so splice.
- **Control board feed** (`W1`): no supplier sells a barrel plug to JST-VH, so it is built rather than ordered. [Make the control board's 24 V lead]({{ '/hardware/helpers/board-24v-lead/' | relative_url }}).
- **Chute stepper** (`CH`): flying leads out of the motor, so splice. [Make the chute stepper lead]({{ '/hardware/helpers/chute-stepper-lead/' | relative_url }}).
- **COB boards** (`L1p`, `L2p`): solder pads, so solder direct. Each COB board also needs a **220 Ω, 1/4 W current-limiting resistor in series**, one per board, unless it is fed from a basically board v1.3 LED header, which has its own. Without one the plate pulls about 0.5 A and melts its mount. See [LEDs]({{ '/hardware/electronics/wire-harness/#33--leds-from-basically-board-v13' | relative_url }}).
- **LED strip** (`L3p`): a solderless clamp-on connector bites onto the cut strip, so nothing is soldered. Pick the variant with IDC crimp points on both sides and it takes the pigtail wire too.

<div class="callout">
  <span class="callout-icon" aria-hidden="true">›</span>
  <p><b>Splice spec:</b> solder splice plus adhesive-lined heat shrink, one sleeve per conductor and one over both. No twist-and-tape, no inline lever nuts.</p>
</div>

The connectors themselves, with a photo and a per-machine count for each, are in the [parts catalog](https://parts-calculator.basically.website/hardware) under **Wire harness**.

## Stepper cable pin map

The four channel stepper cables are the only crossover in the harness, so they are the ones to spell out. The motor end is a 6-position housing with four positions populated, so the four board positions land on motor positions 1, 4, 3 and 6. The nets match end to end; the positions do not.

<table style="max-width:520px">
  <thead><tr><th>Board PHR-4 position</th><th>Net</th><th>Motor PHR-6 position</th><th>Colour</th></tr></thead>
  <tbody>
    <tr><td>1</td><td><code>A2</code></td><td>1</td><td>blue</td></tr>
    <tr><td>2</td><td><code>A1</code></td><td>4</td><td>green</td></tr>
    <tr><td>3</td><td><code>B1</code></td><td>3</td><td>red</td></tr>
    <tr><td>4</td><td><code>B2</code></td><td>6</td><td>black</td></tr>
    <tr><td>—</td><td>—</td><td>2 and 5</td><td>unpopulated</td></tr>
  </tbody>
</table>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>For the vendor, explicitly:</b> this is <b>not</b> a straight-through cable, and the two ends have a different number of positions. Board 1 to motor 1, board 2 to motor 4, board 3 to motor 3, board 4 to motor 6. Motor positions 2 and 5 are left empty.</p>
</div>

The fifth stepper cable, the chute one, is straight through and is built rather than ordered: [make the chute stepper lead]({{ '/hardware/helpers/chute-stepper-lead/' | relative_url }}).

**The drawings.** One per buildable cable, each with the bill of materials for it.

<ul class="harness-contents">{% for d in site.data.harness.drawings %}{% unless d.of %}<li><a href="#{{ d.name }}">{{ d.title }}</a>{% assign parts = site.data.harness.drawings | where: "of", d.name %}{% if parts.size > 0 %}<ul>{% for p in parts %}<li><a href="#{{ p.name }}">{{ p.title }}</a></li>{% endfor %}</ul>{% endif %}</li>{% endunless %}{% endfor %}</ul>

{% for d in site.data.harness.drawings %}
{% if d.of %}{% assign parent = site.data.harness.drawings | where: "name", d.of | first %}<h3 id="{{ d.name }}">{{ d.title }}</h3>
<p class="harness-parent">A sub-harness of <a href="#{{ d.of }}">{{ parent.title }}</a>.</p>{% else %}<h2 id="{{ d.name }}">{{ d.title }}</h2>{% endif %}

{% if d.photo %}
<figure class="harness-figure">
  <img src="{{ d.photo }}" alt="Assembled {{ d.title }}">
  <figcaption>What it looks like built. <cite>{% if d.photo_credit %}Photo: {{ d.photo_credit }}.{% else %}Photographer not recorded.{% endif %}</cite></figcaption>
</figure>
{% endif %}

<figure class="harness-figure">
  <a href="{{ d.png }}" target="_blank" rel="noopener">
    <img src="{{ d.png }}" alt="WireViz drawing: {{ d.title }}">
  </a>
  <figcaption>{{ d.caption }} Click for full size. <cite>WireViz-generated drawing, not a photo.</cite></figcaption>
</figure>

{% if d.guide %}
<p class="download-line">
  <a href="{{ d.guide | relative_url }}"><b>How to make your own →</b></a>
</p>
{% endif %}

<p class="download-line">
  <span>Download:</span>
  <a href="{{ d.pdf }}">PDF</a> ·
  <a href="{{ d.png }}" download>PNG</a> ·
  <a href="{{ d.svg }}" download>SVG</a> ·
  <a href="{{ d.html }}">HTML (drawing + BOM)</a> ·
  <a href="{{ d.bom_tsv }}" download>BOM (TSV)</a> ·
  <a href="{{ d.yml }}" download>YAML source</a>
</p>

<div class="bom" data-bom="{{ d.bom_tsv }}">
  <p class="bom-status">Loading the bill of materials for {{ d.title }}</p>
</div>

{% endfor %}

## Guesses to verify before sending

1. **LED feed Dupont polarity.** Which pin is +24 V on `L1` to `L3` at the board. The board's own 24 V input is settled (JST-VH, pin 1 is +24 V); these have not been checked.
2. **Lengths.** `W2` is 305 mm (12 in) on the drawing, and the wire-harness page gives 280 mm (11 in) for the plug's own lead. `CH` is 610 mm (24 in) here and on its helper page, while the YAML source still says 1016 mm (40 in). `W1` is 914 mm (36 in) and longer than it needs to be. Check each against the built machine.
3. **LED drop count.** Three feeds and three pigtails, per the wire schedule. Re-count against the machine.
4. **Motor coil order.** The 1·4·3·6 map and the two empty positions come from the drawing, not from a measurement. Check the coils with a multimeter first.
5. **Limit switch contact.** The Omron V-155-1C25 is SPDT with three tabs and the harness lands on two. Confirm which pair, `COM` + `NC` or `COM` + `NO`, against the board.
6. **Missing part numbers.** The Dupont, quick-connect, barrel and fork-terminal rows in the connector table have specs only.
