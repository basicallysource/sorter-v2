---
layout: default
title: Sorter V2 Documentation
type: landing
slug: home
kicker: Sorter V2
lede: What Sorter V2 is, what it sorts, and where to start if you want to build one.
---

## What Sorter V2 is

<figure class="landing-hero-float">
  <div class="landing-hero-media">
    <img src="https://assets.basically.website/web/hero-w1600-webp-8481cdd67816.webp"
      alt="Sorter V2 assembled: a hexagonal tower of open bins under the platter, distributor and camera head.">
  </div>
  <figcaption><cite>Rendered from the part geometry, not from a build.</cite></figcaption>
</figure>

Sorter V2 is an open-source LEGO sorting machine. You feed bulk LEGO into a hopper. The machine separates the pieces one at a time, works out what each one is by part number (and by color, if you want), and drops it into the right bin.

Machines are built and running, and they sort every day. It is not a product: there is no kit, no price, and nothing for sale. What exists is the design, the parts list, and these instructions.

**What it sorts:** loose, rigid LEGO pieces up to ten studs in any direction. That is most of a mixed tub, not all of it, and the rest you pick out by hand before a run:

- **Anything over ten studs.** Baseplates, long plates and beams, boat hulls, large wheels and tank tracks.
- **Tyres and anything rubber.** Rubber grips where plastic slides, so a tyre stalls in a channel instead of dropping out of it.
- **Cloth, string and chain.** These tangle, with each other and with ordinary parts.
- **Minifigures and their small accessories.**
- **Duplo, Primo and other brands.**

[Preparing LEGO]({{ '/sorter/preparing-lego/' | relative_url }}) is the full list, with what each thing does to the machine if it stays in.

**How much it sorts at once is your choice.** The machine is a stack of layers, each holding 18 bins or 12 larger ones, so more layers means more categories in one pass and more to build. [Hardware]({{ '/hardware/' | relative_url }}) has what each size costs in parts, filament and printing time.

<div class="clear-float"></div>

## Start here

<div class="callout-grid callout-grid-paired">
  <div class="callout">
    <strong><a href="{{ '/getting-started/' | relative_url }}">Getting started</a></strong>
    <p>Want to build a machine? This is the first page. It also covers working on the project.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/hardware/' | relative_url }}">Hardware</a></strong>
    <p>What the machine costs in parts and printing time, everything to buy and print, and the step-by-step assembly.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/sorter/' | relative_url }}">Sorter</a></strong>
    <p>The software on the machine. Install it, set it up, calibrate the cameras and the chute, and run a sort.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/hive/' | relative_url }}">Hive</a></strong>
    <p>Sorting profiles shared by other builders, and the samples behind them.</p>
  </div>
  <div class="callout">
    <strong><a href="{{ '/lab/' | relative_url }}">Lab</a></strong>
    <p>Research and contributor references: detector runtime findings, model artifacts, benchmarks, and the shared styleguide.</p>
  </div>
</div>
