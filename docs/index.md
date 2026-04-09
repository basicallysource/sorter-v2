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

## What's stable and what's a stub

Right now the site is uneven on purpose:

- **Lab** is the only section with real, promoted content — the April 6, 2026 detector findings plus the shared styleguide that keeps the Sorter UI, Hive, and this site visually consistent.
- **Hardware**, **Sorter**, and **Hive** are still placeholder indexes. Their content is being promoted out of code comments, in-repo notes, and the handoff file as each area stabilizes.

The durable rule: keep decisions and workflows in checked-in Markdown here, and treat every generated report or experiment bundle under `software/sorter/backend/blob/` as disposable working state unless a document in this site promotes it.

## Editing and publishing

The site source lives in `docs/` and is deployed via GitHub Pages. To preview locally, run:

```bash
./docs/local-jekyll.sh serve
```

and open <http://localhost:4000>. Live-reload picks up Markdown changes automatically.
