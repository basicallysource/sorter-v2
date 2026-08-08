---
layout: default
title: WireViz drawings
type: reference
section: hardware
slug: electronics-wireviz
kicker: Electronics — WireViz
lede: Rendered harness drawings, BOMs, and everything a cable vendor would ask for.
permalink: /hardware/electronics/wireviz/
last_verified: 2026-07-12
---

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Not remotely validated.</b> Nothing on this page has been checked against the physical machine. Gauges, lengths, connector part numbers, and pin orders marked <b>GUESS</b> in the drawings are guesses layered on top of the <a href="{{ '/hardware/electronics/' | relative_url }}">wire harness</a> notes. Do not send this to a supplier for production: sample quantities only, after a review pass.</p>
</div>

## 1 &nbsp; What you'd actually send a supplier

One zip with everything in it. Attach it to an Alibaba "custom cable assembly" inquiry along with the quantity (it's stated in the cover sheet: 2 sample sets, price breaks at 10 / 50).

<p class="download-line">
  <a href="{{ site.harness_base }}/sorter-v2-harness-rfq.zip{{ site.harness_v }}" download><b>↓ sorter-v2-harness-rfq.zip</b></a>
  <span>cover sheet + 3 drawings (PDF/PNG/SVG/HTML) + 3 BOMs (TSV) + WireViz YAML sources</span>
</p>

The cover sheet ([rfq.txt]({{ site.harness_base }}/rfq.txt{{ site.harness_v }})) pre-answers their standard questions: quantity, wire spec, clone connectors OK, tolerance, labeling, test requirement, and a callout that cable S is a crossover.

### 1.1 &nbsp; The maximum a supplier might ask for

- **Drawing per cable** with pin-to-pin table, lengths, and tolerances: the PDFs here (they may ask for DWG; PDF is normally accepted).
- **BOM** with connector part numbers or approved equivalents: the TSVs here. JST MPNs are in the [order spec]({{ '/hardware/electronics/order/' | relative_url }}), clones explicitly allowed.
- **Wire spec**: gauge, UL style (UL1007), colors, RoHS. Cover sheet section 3.
- **Quantity and target price**: cover sheet section 2. Expect MOQ pushback below ~50 pcs/type; the cover sheet frames the 2 sets as a paid sample run.
- **Quality/test requirements**: IPC/WHMA-A-620 class, continuity, hipot. Cover sheet says hobby grade, 100% continuity, no hipot, no UL cert.
- **Label and packaging spec**: cover sheet section 6.
- **Photos or samples of mating hardware** for anything ambiguous (the StepperOnline lead, the board jacks). The only thing not in the zip; send phone photos if asked.

## 2 &nbsp; Drawings

Generated with [WireViz](https://github.com/wireviz/WireViz) from the YAML in `electronics/wire_harness/`. Everything on this page is derived from those three files and none of it is stored in the repo: CI renders and publishes on any harness change, and this page always shows the drawings for the branch it was built from. Nothing here is edited by hand. HTML = drawing + BOM + cut list in one file.

{% assign b = site.harness_base %}{% assign v = site.harness_v %}
{% for d in site.data.harness.drawings %}
### {{ d.title }}

<figure class="harness-figure">
  <a href="{{ b }}/{{ d.name }}.png{{ v }}" target="_blank" rel="noopener">
    <img src="{{ b }}/{{ d.name }}.png{{ v }}" alt="WireViz drawing: {{ d.title }}">
  </a>
  <figcaption>{{ d.caption }} Click for full size.</figcaption>
</figure>

<p class="download-line">
  <span>Download:</span>
  <a href="{{ b }}/{{ d.name }}.pdf{{ v }}">PDF</a> ·
  <a href="{{ b }}/{{ d.name }}.png{{ v }}" download>PNG</a> ·
  <a href="{{ b }}/{{ d.name }}.svg{{ v }}" download>SVG</a> ·
  <a href="{{ b }}/{{ d.name }}.html{{ v }}">HTML (drawing + BOM)</a> ·
  <a href="{{ b }}/{{ d.name }}.bom.tsv{{ v }}" download>BOM (TSV)</a> ·
  <a href="{{ b }}/{{ d.name }}.yml{{ v }}" download>YAML source</a>
</p>
{% endfor %}
