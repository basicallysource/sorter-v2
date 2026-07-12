---
layout: default
title: Sorter V2 Documentation
type: landing
slug: home
kicker: Sorter V2
lede: The durable documentation layer for the Sorter V2 project — hardware, the local machine software, the Hive community platform, and the lab where research and contributor references live.
---

## Start here

<div class="callout-grid">
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

## Editing and publishing

The site source lives in `docs/` and is deployed via GitHub Pages. To preview locally, run:

```bash
./docs/local-jekyll.sh serve
```

and open <http://localhost:4000>. Live-reload picks up Markdown changes automatically.
