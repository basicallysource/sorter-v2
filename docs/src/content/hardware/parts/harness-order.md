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
last_verified: 2026-07-12
---

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Not validated against a machine, and there are guesses in it.</b> Nothing here has been checked against the physical machine. Gauges, connector part numbers and the chute stepper length are engineering guesses, not measurements; they are conservative and safe to order against. Values marked <b>GUESS</b> in the drawings are guesses, and the ones that matter are listed at the bottom of this page.</p>
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
  <dt>Gauges</dt><dd>18 AWG (PSU box internals) · 22 AWG (all barrel-plug 24 V runs, LED feeds, limit switch) · 24 AWG (stepper cables, set by the JST-PH contact limit)</dd>
  <dt>Colours</dt><dd>Red = +24 V, black = GND on every 2-conductor power cable. Stepper colours are on the drawings.</dd>
  <dt>Barrel jacks and plugs</dt><dd><b>5.5 mm outside, 2.1 mm inside</b>, centre-positive, rated 5 A or better. Confirmed against the Waveshare hub (their part DC-044). 5.5 × 2.5 mm exists, looks identical and does not mate, so put 2.1 on every line of the order.</dd>
  <dt>Length tolerance</dt><dd>±10 mm, and ±25 mm is fine on anything 36 in or longer</dd>
  <dt>Bare ends</dt><dd>Strip 5 mm, tin</dd>
  <dt>Labelling</dt><dd>Each cable labelled with its ID (`W1`, `S1`…) on a flag label near end A</dd>
  <dt>Order quantity</dt><dd>2 full sets, because the lengths are guesses and spares are cheap</dd>
</dl>

## How to order it

- **A custom harness vendor** (Alibaba "custom cable assembly", or a quick-turn shop): send them the zip. Expect MOQ 50 to 100 pieces per line item from China; small shops and some AliExpress custom-cable storefronts will do 5 to 10.
- **Low volume instead:** buy pre-crimped PH, XH and Dupont leads plus housings and assemble them. The only labour a vendor saves you is crimping.
- The reasoning behind the guessed gauges: steppers draw 1.5 A per phase or less, so 24 AWG is fine at these lengths; no single barrel-plug load exceeds about 3 A, so 22 AWG is fine; the PSU box pigtails carry worst-case single-load current, hence 18 AWG.

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
  <a href="{{ d.guide | n }}"><b>How to make your own →</b></a>
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
2. **Chute stepper cable.** The 40 in is copied from the channel steppers, and no drawing covers that cable at all.
3. **LED drop count.** Three feeds and three pigtails, per the wire schedule. Re-count against the machine.
4. **Motor coil order.** The 1·4·3·6 map and the two empty positions come from the drawing, not from a measurement. Check the coils with a multimeter first.
5. **Limit switch contact.** The Omron V-155-1C25 is SPDT with three tabs and the harness lands on two. Confirm which pair, `COM` + `NC` or `COM` + `NO`, against the board.
