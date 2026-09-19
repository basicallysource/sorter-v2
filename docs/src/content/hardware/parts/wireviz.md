---
layout: default
title: WireViz drawings
type: reference
section: hardware
slug: parts-wireviz
kicker: Parts — WireViz
lede: Every harness drawing on the machine, with its bill of materials, its downloads, and the zip to send a cable vendor.
permalink: /hardware/parts/wireviz/
author: spencer
contributors: [effreek]
last_verified: 2026-07-12
---

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Not remotely validated.</b> Nothing on this page has been checked against the physical machine. Values marked <b>GUESS</b> in the drawings are guesses. Sample quantities only, after a review pass.</p>
</div>

This is the only page that carries the drawings. Everywhere else on the site links here, so a cable is drawn once and a redrawn harness updates in one place.

<p class="download-line">
  <a href="{{ site.data.harness.zip }}" download><b>↓ sorter-v2-harness-rfq.zip</b></a>
  <span>cover sheet + every drawing (PDF/PNG/SVG/HTML) + a BOM per drawing (TSV) + WireViz YAML sources</span>
</p>

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
  <figcaption>{{ d.caption }} <cite>WireViz-generated drawing, not a photo.</cite> Click for full size.</figcaption>
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
