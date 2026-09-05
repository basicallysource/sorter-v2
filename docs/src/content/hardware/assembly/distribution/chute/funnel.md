---
layout: default
title: Funnel
type: how-to
section: hardware
slug: assembly-funnel
kicker: Chute — Funnel
lede: The funnel that guides parts through the door.
permalink: /hardware/assembly/distribution/chute/funnel/
author: spencer
contributors: [barthel]
last_verified: 2026-09-05
parts_needed:
  - part: funnel-half
  - part: funnel-third
  - part: funnel-bracket-left
    qty: 1
  - part: funnel-bracket-right
    qty: 1
  - part: scr-m3-12-cs
    qty: 4
---

The funnel catches what the door releases and guides it into the bin below. It hangs off two printed brackets that are part of the chute.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

- **One funnel per layer**, in one of two sizes, and it is your choice which. Step 2 is that decision; the brackets are the same either way, so they go on before you have made it.
- The brackets screw into the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }})'s M3 heat inserts, so there is nothing to tap.
- The 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} they take are in the list above, and they go into the core's inserts rather than into anything on this page.
- **The funnel itself takes no fasteners.** It snaps into the brackets, which is step 3.

{% include step.html n="1" title="Fit the funnel brackets to the chute core" %}

Every chute carries a Funnel bracket (left) and a Funnel bracket (right), one of each. They screw into the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }})'s M3 heat inserts, which are pressed in on that page.

Each bracket takes 2 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws, 4 for the pair. The bracket is 8.16 mm thick at the screw, so a 12 mm screw reaches 3.84 mm into the core's blind 5.70 mm insert and an 8 mm one would not reach it at all.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-core-funnel-brackets-full-36040ab587fd.png" alt="Render of one long side of the chute core with the two heat inserts a funnel bracket screws into circled in red">
  <figcaption>The two inserts one funnel bracket screws into, at the lower end of one long side of the chute core. The other long side carries the mirror pair for the second bracket. <cite>Render: Balloon.</cite></figcaption>
</figure>

<div class="img-placeholder">Photo of both funnel brackets fitted to the chute core.</div>

{% include step.html n="2" title="Pick the funnel size for the layer" %}

**This is a builder's decision, taken once per layer.** What you are choosing is how finely that layer divides its ring: into 12 bins or into 18. The funnel and the bin set are a matched pair, so the size you pick decides both at once, and a machine can mix sizes from layer to layer. Decide before you print either part.

**Half size: 12 bins on that layer**, six Bin (half, left) and six Bin (half, right).

- Wider funnel mouth, so this layer takes the biggest pieces the machine can sort.
- Twelve destinations instead of eighteen, so fewer categories land on this layer.

**Third size: 18 bins on that layer**, six each of Bin (third, left), Bin (third, center) and Bin (third, right-back).

- Half again as many destinations, which is what you want for the small parts that make up most of a pile.
- Narrower mouth. The opening is what limits piece size on a layer, so anything too big for it has to be routed to a half-size layer instead.

Neither is cheaper to build: a layer's bins come to roughly 2.1 kg of filament and 55 to 60 hours of printing either way, and total capacity per layer works out much the same, since the extra walls of the three-way split take room out of each bin rather than out of the layer.

**If you have no reason to prefer one:** the [parts calculator](https://parts-calculator.basically.website/) starts a fresh machine at two third-size layers and one half-size, which is a sensible default. Most LEGO is small, so most of your destinations should be, but you want at least one layer that can take the big pieces. Nothing in the machine or the software ties a size to a particular height, so which level carries the half-size layer is yours to choose too.

The calculator takes a size per layer and totals the print for whatever mix you pick.

{% include step.html n="3" title="Hang the funnel" %}

**Nothing is screwed or glued here.** Each bracket has two arms: the one with the two countersunk holes is the one that went onto the core in step 1, and the plain arm is a sprung slide. The funnel has a rail down each side that runs into that arm. Push the funnel onto the pair of brackets, the arm flexes to let the rail past, and it springs back and holds the funnel there.

It should feel like it has landed. If the funnel can be lifted straight back off without the arm flexing, it has not gone far enough in.

<div class="img-placeholder">Photo of a funnel snapped into its two brackets.</div>
