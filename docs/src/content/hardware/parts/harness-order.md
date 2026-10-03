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

This is the only page that carries the harness drawings. Everywhere else on the site links here, so a cable is drawn once and a redrawn harness updates in one place.

**You do not have to order the harness.** Every cable can be bought ready made or built on the bench, and the four you build have their own pages under [Helpers]({{ '/hardware/helpers/' | relative_url }}). This page is for having the set made in one go.

**Building them yourself?** Use the Helpers pages and the bill of materials under each drawing, and skip to [the drawings](#the-drawings). Everything above the drawings is the specification for a vendor.

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
  <dt>Length tolerance</dt><dd>±10 mm (±0.4 in), and ±25 mm (±1 in) is fine on anything 920 mm (36 in) or longer</dd>
  <dt>Bare ends</dt><dd>Strip 5 mm (0.2 in), tin</dd>
  <dt>Labelling</dt><dd>Each cable labelled with its ID from the schedule below (<code>W2</code>, <code>S1</code>…) on a wrap-around label near end A, which is the left-hand end in the schedule. <b>S1 to S4 are labelled at both ends</b>: four identical cables land within inches of each other at the board and at the motors, and they cannot be told apart once unplugged. Printed laser labels or printed heat shrink are both fine.</dd>
  <dt>Acceptance test</dt><dd>100% continuity, every conductor, end to end. On <code>S1</code> to <code>S4</code> that means checking the position map under <a href="#channel-stepper">Channel stepper lead</a>, not just that each wire arrives. No hipot. No UL listing or IPC class is asked for at this stage.</dd>
  <dt>Packaging</dt><dd>One bag per cable type, ID on the bag</dd>
  <dt>Parts and brands</dt><dd>The vendor sources the connectors to the spec in the connector table. Where a row gives a part number it is the one the machine was designed against, and any RoHS-compliant equivalent that mates and crimps the same is fine.</dd>
  <dt>Order quantity</dt><dd>2 full sets, because spares are cheap. Treat them as the sample run.</dd>
</dl>

## Cable schedule

Every cable and lead in the machine, one row each, with its ID. The IDs are the same on the drawings, on the [wire harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) page and on the labels, so a cable keeps one name everywhere. Socket references (<code>J1</code>, <code>J27</code>…) are the sockets on basically board v1.3, and a socket on a layer board is named as such. <b>End A</b> is the end that gets the label.

<table>
  <thead><tr><th>ID</th><th>Qty</th><th>How</th><th>End A</th><th>End B</th><th>Length</th><th>Wire</th></tr></thead>
  <tbody>
    <tr><td class="wire-id">PJ1, PJ2, PJ3</td><td>3</td><td>Vendor, or <a href="{{ '/hardware/helpers/psu-pigtail/' | relative_url }}">build</a></td><td>Panel-mount DC jack, female, on the PSU box plate</td><td>Two insulated M3.5 fork terminals, onto the PSU's paired screws (7+4, 8+5, 9+6)</td><td>100 mm (4 in)</td><td>18 AWG (0.82 mm²), red and black</td></tr>
    <tr><td class="wire-id">W1</td><td>1</td><td>Vendor, or <a href="{{ '/hardware/helpers/board-24v-lead/' | relative_url }}">build</a></td><td>DC plug, male, into <code>PJ1</code></td><td>JST VHR-2 housing into board <code>J1</code>, pin 1 = +24 V, pin 2 = GND</td><td>920 mm (36 in)</td><td>18 AWG (0.82 mm²), red and black</td></tr>
    <tr><td class="wire-id">W2</td><td>1</td><td>Vendor</td><td>DC plug, male, into <code>PJ2</code></td><td>Bare, tinned, into the USB hub's 2-pin 24 V terminal</td><td>310 mm (12 in)</td><td>22 AWG (0.33 mm²), red and black</td></tr>
    <tr><td class="wire-id">W3</td><td>1</td><td>Vendor, or <a href="{{ '/hardware/helpers/pi-24v-lead/' | relative_url }}">build</a></td><td>DC plug, male, into <code>PJ3</code></td><td>Bare, tinned, spliced to the buck converter's input leads</td><td>150 mm (6 in)</td><td>22 AWG (0.33 mm²), red and black</td></tr>
    <tr><td class="wire-id">L1, L2, L3</td><td>3</td><td>Vendor</td><td>2-position Dupont housing, 2.54 mm (0.1 in), into board <code>J8</code>, <code>J9</code>, <code>J10</code>: black wire in the cavity at the moulded arrow, red in the other</td><td>Inline DC socket, female</td><td>920 mm (36 in)</td><td>22 AWG (0.33 mm²), red and black</td></tr>
    <tr><td class="wire-id">L1p, L2p, L3p</td><td>3</td><td>Vendor</td><td>DC plug, male, into the matching <code>L1</code> to <code>L3</code> socket</td><td>Bare, tinned, to the clamp-on connector on the LED strip</td><td>150 mm (6 in)</td><td>22 AWG (0.33 mm²), red and black</td></tr>
    <tr><td class="wire-id">LIM</td><td>1</td><td>Vendor, or <a href="{{ '/hardware/helpers/limit-switch-lead/' | relative_url }}">build</a></td><td>3-position Dupont housing into board <code>J5</code>: position 1 (the cavity at the moulded arrow) ground, position 2 signal, position 3 empty. Black for ground, white for signal</td><td>Two insulated #187 quick-connect receptacles, onto the limit switch</td><td>610 mm (24 in)</td><td>22 AWG (0.33 mm²), black and white</td></tr>
    <tr><td class="wire-id">S1, S2, S3, S4</td><td>4</td><td>Vendor</td><td>JST PHR-4 into board <code>J27</code>, <code>J31</code>, <code>J35</code>, <code>J39</code></td><td>JST PHR-6 into the motor's own socket, positions 1·4·3·6 (see the <a href="#channel-stepper">pin map</a>)</td><td>1 m (39 in)</td><td>24 AWG (0.20 mm²), blue, green, red, black</td></tr>
    <tr><td class="wire-id">CH</td><td>1</td><td><a href="{{ '/hardware/helpers/chute-stepper-lead/' | relative_url }}">You build</a></td><td>JST PHR-4 into board <code>J23</code></td><td>The chute motor's flying leads, spliced</td><td>300 mm (12 in) tail, about 600 mm (24 in) overall with the motor's own leads</td><td>24 AWG (0.20 mm²)</td></tr>
    <tr><td class="wire-id">RIB1</td><td>1</td><td>Buy</td><td>16-pin IDC (2×8), female, into board <code>J17</code></td><td>16-pin IDC (2×8), female, into <code>J3</code> on the first layer board</td><td>1.2 to 1.5 m (47 to 59 in)</td><td>Flat ribbon</td></tr>
    <tr><td class="wire-id">U1</td><td>1</td><td>Buy</td><td>USB-A on the hub</td><td><code>UP USB3.0</code> on the Orange Pi</td><td>0.9 m (3 ft) or shorter</td><td>USB data cable</td></tr>
    <tr><td class="wire-id">U2</td><td>1</td><td>Buy</td><td>Micro USB on the Pico</td><td>USB-A on the hub</td><td>0.9 m (3 ft) or shorter</td><td>USB data cable</td></tr>
    <tr><td class="wire-id">RIB2</td><td>layers - 1</td><td>Buy</td><td>16-pin IDC (2×8), female, into <code>J4</code> on a layer board</td><td>16-pin IDC (2×8), female, into <code>J3</code> on the layer board below</td><td>300 mm (12 in)</td><td>Flat ribbon</td></tr>
    <tr><td class="wire-id">AC1</td><td>1</td><td>Buy</td><td>IEC C13 socket, onto the PSU box's inlet</td><td>Wall plug for your country (NEMA 5-15 or CEE 7/7)</td><td>As supplied</td><td>Mains cord</td></tr>
  </tbody>
</table>

`RIB2` is one per joint between two layers, so one fewer than the number of layers: 2 on a 3-layer machine, 4 on 5. `CH` is listed as the tail wire to cut, 300 mm (12 in); the motor's own leads are 300 to 500 mm (12 to 20 in) depending on the batch and are not part of it. `U1` and `U2` must be real data cables, because a lot of short USB cables are power-only. The three cameras use their own USB leads and are not scheduled.

On `L1` to `L3`, the optional inline socket and the plug on `L1p` to `L3p` can be left out, in which case the feed runs straight to the strip and the pigtail is not needed. The plug and socket are recommended because they let the lamp be unplugged close to where it is.

## Connectors and terminals

What goes on the ends in the schedule. The part numbers are the ones the machine was designed against; where there is none, the spec is what to order to.

<table>
  <thead><tr><th>Where</th><th>Housing or part</th><th>Contact or crimp</th><th>Used on</th></tr></thead>
  <tbody>
    <tr><td>Board 24 V input</td><td>JST VHR-2N, 2-position</td><td>JST SVH-21T-P1.1</td><td><code>W1</code></td></tr>
    <tr><td>Stepper, board end</td><td>JST PHR-4, 4-position</td><td>JST SPH-002T-P0.5S</td><td><code>S1</code> to <code>S4</code>, <code>CH</code></td></tr>
    <tr><td>Stepper, motor end</td><td>JST PHR-6, 6-position, 4 populated</td><td>JST SPH-002T-P0.5S</td><td><code>S1</code> to <code>S4</code></td></tr>
    <tr><td>LED feeds, limit switch</td><td>Dupont housing, female, 2.54 mm (0.1 in): 2-position, and 3-position with 2 populated</td><td>Dupont female crimp contact, 2.54 mm (0.1 in).</td><td><code>L1</code> to <code>L3</code>, <code>LIM</code></td></tr>
    <tr><td>Limit switch</td><td>Fully insulated female quick-connect receptacle, #187 (4.75 × 0.5 mm, 0.187 × 0.020 in, tab), for 22 AWG (0.33 mm²).</td><td>Mates the Omron V-155-1C25</td><td><code>LIM</code></td></tr>
    <tr><td>DC plug</td><td>Barrel plug, male, 5.5 × 2.1 mm (0.217 × 0.083 in), centre-positive, 5 A or better.</td><td>Soldered or crimped per the vendor's process</td><td><code>W1</code> to <code>W3</code>, <code>L1p</code> to <code>L3p</code></td></tr>
    <tr><td>DC socket</td><td>Barrel socket, female, 5.5 × 2.1 mm (0.217 × 0.083 in), panel-mount on <code>PJ1</code> to <code>PJ3</code>, inline on <code>L1</code> to <code>L3</code>.</td><td>As above</td><td><code>PJ1</code> to <code>PJ3</code>, <code>L1</code> to <code>L3</code></td></tr>
    <tr><td>PSU terminal block</td><td>Insulated fork terminal, M3.5 stud, 8 mm (0.31 in) wide at most, for 18 AWG (0.82 mm²).</td><td>Crimp</td><td><code>PJ1</code> to <code>PJ3</code></td></tr>
    <tr><td>Ribbon</td><td>16-pin IDC (2×8), 2.54 mm (0.1 in), female, both ends</td><td>Pre-made, bought</td><td><code>RIB1</code></td></tr>
    <tr><td>Bare ends</td><td>Strip 5 mm (0.2 in), tin</td><td>No connector</td><td><code>W2</code>, <code>W3</code>, <code>L1p</code> to <code>L3p</code></td></tr>
  </tbody>
</table>

**Dupont housings: the moulded arrow always marks the ground wire.** The black wire goes in the cavity next to the arrow, and positions count away from the arrow. The housing has no key and the board's `J8` to `J11` have no reverse-polarity protection, so fit the lead with the arrow end over the pin the board prints `GND` (the round pad on `J8` to `J11`; on `J5` the pin on the square pad, with the empty position over `3.3V`). Black is always ground and red is always +24 V. The self-builder pages ([LED strip lead]({{ '/hardware/helpers/led-strip/' | relative_url }}), [limit switch lead]({{ '/hardware/helpers/limit-switch-lead/' | relative_url }})) say the same.

Rows without a part number are specified by type and size, and the vendor sources them. The [parts catalog](https://parts-calculator.basically.website/hardware) carries each one with its per-machine count.

## Ends the vendor cannot terminate

Some parts come with their own fixed leads or solder pads, so the harness cannot fully land on them. Those cables are ordered with one end bare and tinned, and joined on the machine.

- **24 V to 5 V USB-C buck** (`W3`): the converter has fixed input leads, so splice.
- **Chute stepper** (`CH`): flying leads out of the motor, so splice. [Make the chute stepper lead]({{ '/hardware/helpers/chute-stepper-lead/' | relative_url }}).
- **LED strips** (`L1p`, `L2p`, `L3p`): a solderless clamp-on connector bites onto the cut strip, so nothing is soldered. Pick the variant with IDC crimp points on both sides and it takes the pigtail wire too.

<div class="callout">
  <span class="callout-icon" aria-hidden="true">›</span>
  <p><b>Splice spec:</b> solder splice plus adhesive-lined heat shrink, one sleeve per conductor and one over both. No twist-and-tape, no inline lever nuts.</p>
</div>

The connectors themselves, with a photo and a per-machine count for each, are in the [parts catalog](https://parts-calculator.basically.website/hardware) under **Wire harness**.

<h2 id="the-drawings">The drawings</h2>

One per buildable cable, each with the bill of materials for it.

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

{% if d.name == "channel-stepper" %}{% include harness/stepper-pin-map.html %}{% endif %}

{% if d.name == "channel-stepper" %}
<div class="callout">
  <span class="callout-icon" aria-hidden="true">›</span>
  <p><b>Motor end.</b> The positions are the ones on the motor's own wire diagram in the StepperOnline 17HE15-1504S datasheet: position 1 is coil A+, 3 is B+, 4 is A-, 6 is B-, and 2 and 5 are empty. Coil A is positions 1 and 4, coil B is positions 3 and 6.</p>
</div>
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
