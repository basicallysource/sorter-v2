---
layout: default
title: WireViz drawings
type: reference
section: hardware
slug: electronics-wireviz
kicker: Electronics — WireViz
lede: The harness drawings and the zip to send a cable vendor.
permalink: /hardware/electronics/wireviz/
last_verified: 2026-07-12
---

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Not remotely validated.</b> Nothing on this page has been checked against the physical machine. Values marked <b>GUESS</b> in the drawings are guesses. Sample quantities only, after a review pass.</p>
</div>

<p class="download-line">
  <a href="{{ site.harness_base }}/sorter-v2-harness-rfq.zip{{ site.harness_v }}" download><b>↓ sorter-v2-harness-rfq.zip</b></a>
  <span>cover sheet + 3 drawings (PDF/PNG/SVG/HTML) + 3 BOMs (TSV) + WireViz YAML sources</span>
</p>

{% assign b = site.harness_base %}{% assign v = site.harness_v %}
{% for d in site.data.harness.drawings %}
## {{ d.title }}

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
