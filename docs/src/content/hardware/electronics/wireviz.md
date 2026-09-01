---
layout: default
title: WireViz drawings
type: reference
section: hardware
slug: electronics-wireviz
kicker: Electronics — WireViz
lede: The harness drawings and the zip to send a cable vendor.
permalink: /hardware/electronics/wireviz/
author: spencer
contributors: [effreek]
last_verified: 2026-07-12
---

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Not remotely validated.</b> Nothing on this page has been checked against the physical machine. Values marked <b>GUESS</b> in the drawings are guesses. Sample quantities only, after a review pass.</p>
</div>

<p class="download-line">
  <a href="{{ site.data.harness.zip }}" download><b>↓ sorter-v2-harness-rfq.zip</b></a>
  <span>cover sheet + every drawing (PDF/PNG/SVG/HTML) + a BOM per drawing (TSV) + WireViz YAML sources</span>
</p>

{% for d in site.data.harness.drawings %}
{% if d.of %}### {{ d.title }}{% else %}## {{ d.title }}{% endif %}

{% if d.photo %}
<figure class="harness-figure harness-photo">
  <a href="{{ d.guide | n }}">
    <img src="{{ d.photo }}" alt="Assembled {{ d.title }}">
  </a>
  <figcaption>What it looks like built. <cite>{% if d.photo_credit %}Photo: {{ d.photo_credit }}.{% else %}Photographer not recorded.{% endif %}</cite> <a href="{{ d.guide | n }}">{{ d.guide_label }} →</a></figcaption>
</figure>
{% endif %}

<figure class="harness-figure">
  <a href="{{ d.png }}" target="_blank" rel="noopener">
    <img src="{{ d.png }}" alt="WireViz drawing: {{ d.title }}">
  </a>
  <figcaption>{{ d.caption }} <cite>WireViz-generated drawing, not a photo.</cite> Click for full size.</figcaption>
</figure>

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
