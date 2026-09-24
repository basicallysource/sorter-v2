---
layout: default
title: Sorter V2 Documentation
type: landing
slug: home
kicker: Sorter V2
lede: The durable documentation layer for the Sorter V2 project — hardware, the local machine software, the Hive community platform, and the lab where research and contributor references live.
---

## Start here

<div class="landing-split">
  <div class="callout-grid callout-grid-paired">
    <div class="callout">
      <strong><a href="{{ '/getting-started/' | relative_url }}">Getting started</a></strong>
      <p>New to the project? Prerequisites, contribution tracks, key resources, and how the project works.</p>
    </div>
    <div class="callout">
      <strong><a href="{{ '/hardware/' | relative_url }}">Hardware</a></strong>
      <p>The physical machine — mechanics, electronics, bill of materials, and assembly notes.</p>
    </div>
    <div class="callout">
      <strong><a href="{{ '/sorter/' | relative_url }}">Sorter</a></strong>
      <p>The local software running on the machine — Python backend, SvelteKit UI, setup wizard, profiles.</p>
    </div>
    <div class="callout">
      <strong><a href="{{ '/hive/' | relative_url }}">Hive</a></strong>
      <p>The community platform — shared sorting profiles, uploaded samples, crowd verification.</p>
    </div>
    <div class="callout">
      <strong><a href="{{ '/lab/' | relative_url }}">Lab</a></strong>
      <p>Research and contributor references — detector runtime findings, model artifacts, benchmarks, and the shared styleguide.</p>
    </div>
  </div>
  <figure class="landing-split-figure">
    <div class="landing-split-media">
      <img src="https://assets.basically.website/web/hero-w1600-webp-8481cdd67816.webp"
        alt="Sorter V2 assembled: a hexagonal tower of open bins under the platter, distributor and camera head.">
    </div>
    <figcaption>Sorter V2, assembled. <cite>Rendered from the part geometry, not from a build.</cite></figcaption>
  </figure>
</div>

## Editing and publishing

The site source lives in `docs/`. To preview locally, run:

```bash
cd docs && npm run dev
```

and open the URL it prints. Hot reload picks up Markdown changes automatically.
