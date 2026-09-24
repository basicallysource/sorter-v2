---
layout: default
title: Sorter V2 Documentation
type: landing
slug: home
kicker: Sorter V2
lede: The durable documentation layer for the Sorter V2 project — hardware, the local machine software, the Hive community platform, and the lab where research and contributor references live.
---

## What Sorter V2 is

Sorter V2 is an open-source LEGO sorting machine. Feed bulk LEGO into a hopper, and the machine singulates each piece, classifies it by part number (and optionally color), and drops it into the correct bin. The project is source-available; see [CONTRIBUTING.md](https://github.com/basicallysource/sorter-v2/blob/main/CONTRIBUTING.md) for licensing details. V1 exists as a reference but is no longer maintained; V2 is the active development target.

Machines are built and running, and they sort every day. It is not a product: there is no kit, no price, and nothing for sale. What exists is the design, the parts list, and these instructions.

**What it sorts:** loose, rigid LEGO pieces up to ten studs in any direction. That is most of a mixed tub, not all of it, and the rest you pick out by hand before a run:

- **Anything over ten studs.** Baseplates, long plates and beams, boat hulls, large wheels and tank tracks.
- **Tyres and anything rubber.** Rubber grips where plastic slides, so a tyre stalls in a channel instead of dropping out of it.
- **Cloth, string and chain.** These tangle, with each other and with ordinary parts.
- **Minifigures and their small accessories.**
- **Duplo, Primo and other brands.**

[Preparing LEGO]({{ '/sorter/preparing-lego/' | relative_url }}) is the full list, with what each thing does to the machine if it stays in.

**How much it sorts at once is your choice.** The machine is a stack of layers, each holding 18 bins or 12 larger ones, so more layers means more categories in one pass and more to build. [Hardware]({{ '/hardware/' | relative_url }}) has what each size costs in parts, filament and printing time.

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
