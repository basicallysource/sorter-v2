---
layout: default
title: Funnel brackets
type: how-to
section: hardware
slug: assembly-funnel
kicker: Chute — Funnel brackets
lede: The two brackets that bolt to the chute core, and the funnel that slides into them.
og_image: https://assets.basically.website/sorter-docs/chute-v3-funnel-seated-full-20b636c77729.png
permalink: /hardware/assembly/distribution/chute/funnel/
author: spencer
contributors: [barthel, brickcyclealice, zed0]
tools_needed: ["Hex key, 2 mm"]
parts_needed:
  - part: funnel-half
    qty: 1
  - part: funnel-third
    qty: 1
  - part: funnel-bracket-left
    qty: 1
  - part: funnel-bracket-right
    qty: 1
  - part: scr-m3-12-cs
    qty: 4
warning: >-
  **AI-generated first draft.** Written from the 3D parts of the inverted chute, not from an actual
  build. Positions, hole counts and the dovetail joint are read off the part geometry, and the
  screw and how the funnel is held were confirmed by the part's designer, but the order of the steps
  is not checked against a machine and nobody has built this chute yet.
---

The funnel catches what the door releases and guides it into the bin below. It slides onto two printed brackets that are bolted to the chute core.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

- **One funnel per layer**, in one of two sizes, and it is your choice which. Step 2 is that decision; the brackets are the same either way, so they go on before you have made it.
- The brackets screw into the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }})'s M3 heat inserts (the A pockets on that page), so there is nothing to tap.
- The 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} they take are in the list above, and they go into the core's inserts rather than into anything on this page.
- **The funnel itself takes no screws.** It slides into the brackets, which is step 3.

{% include step.html n="1" title="Fit the funnel brackets to the chute core" %}

Every chute carries a Funnel bracket (left) and a Funnel bracket (right), one of each. The left one goes on the plain side wall of the core and the right one on the servo side wall. They screw into the core's four A inserts, two on each wall.

Each bracket is a long bar. **The end with the two round recesses goes against the core**: that is where the screws go, with the heads sitting in the recesses. The other end, with the two long slits cut along it, runs out past the core's opening to carry the funnel. Each bracket takes 2 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws, 4 for the pair. Use the 12 mm.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-funnel-brackets-exploded-plus-y-full-b9b9c6fc0f25.png" alt="Render of the servo side wall of the chute core with the right funnel bracket held away from it, two inserts ringed in red and lettered A on the wall where the bracket's two recessed holes line up">
    <figcaption>The servo side: the two inserts the right bracket screws into (A), and the bracket held off the wall. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-funnel-brackets-exploded-minus-y-full-ec07a9e61982.png" alt="Render of the plain side wall of the chute core with the left funnel bracket held away from it, two inserts ringed in red and lettered A on the wall">
    <figcaption>The plain side: the same two inserts for the left bracket. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

{% include step.html n="2" title="Pick the funnel size for the layer" %}

**This is a builder's decision, taken once per layer.** What you are choosing is how finely that layer divides its ring: into 12 bins or into 18. The funnel and the bin set are a matched pair, so the size you pick decides both at once. A layer has one funnel, so every bin on it is the same size and you cannot mix 12 and 18 within a layer, but a machine can mix sizes from layer to layer. Decide before you print either part.

**Half size: 12 bins on that layer**, six Bin (half, left) and six Bin (half, right).

- Wider funnel mouth, so this layer takes the biggest pieces the machine can sort.
- Twelve destinations instead of eighteen, so fewer categories land on this layer.

**Third size: 18 bins on that layer**, six each of Bin (third, left), Bin (third, center) and Bin (third, right-back).

- Half again as many destinations, which is what you want for the small parts that make up most of a pile.
- Narrower mouth. The opening is what limits piece size on a layer, so anything too big for it has to be routed to a half-size layer instead.

Neither is cheaper to build, and neither holds more.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-funnel-seated-full-20b636c77729.png" alt="Render of a chute core with the third-size funnel in place, a long funnel running away from the core's opening between the two green brackets">
    <figcaption>Third size: 18 bins. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-funnel-half-seated-full-d56c031fc6f0.png" alt="Render of a chute core with the half-size funnel in place, a shorter and wider funnel between the two green brackets">
    <figcaption>Half size: 12 bins. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
  </figure>
</div>

**If you have no reason to prefer one:** the [parts calculator](https://parts-calculator.basically.website/) starts a fresh machine at two third-size layers and one half-size, which is a sensible default. Most LEGO is small, so most of your destinations should be, but you want at least one layer that can take the big pieces. Nothing in the machine or the software ties a size to a particular height, so which level carries the half-size layer is yours to choose too.

The calculator takes a size per layer and totals the print for whatever mix you pick.

{% include step.html n="3" title="Slide the funnel on" %}

**Nothing is screwed or glued here.** Each side of the funnel has a raised rail that is wider at its outer edge than where it meets the funnel, a dovetail. Each bracket has a matching channel along its underside, and that channel is open at the end away from the core. Line the funnel's two rails up with the two channels and slide the funnel in along them, towards the core, until its open end meets the core's opening.

Both brackets are on the core from step 1, so there is nothing to fit first.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-funnel-exploded-full-cf88dcd54ef7.png" alt="Render of the chute core with the two green brackets on it and the tan funnel held out along the line of the brackets, ready to slide in towards the core">
  <figcaption>The funnel, held out along the line of the brackets. It slides in from the free end of the brackets, towards the core. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

**The funnel is held in by the spring force of the brackets.** Each bracket has two slits along its free end, which let it flex, and there is no screw to fit.

<div class="callout">
  <span class="callout-icon" aria-hidden="true">💡</span>
  <p>Each funnel has one small round pocket in the middle of each rail, two in all. They are the size of an M3 heat insert pocket, but the brackets have no holes over them, so nothing uses them and they stay empty.</p>
</div>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-funnel-pocket-plus-y-full-40653619db12.png" alt="Render of the side of a funnel with its raised dovetail rail and one small round pocket ringed in red in the middle of the rail">
  <figcaption>The pocket on one side of the funnel, inside the rail. The other side has the same. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

## The finished result

Both brackets are bolted to the core, one on each long wall, and the funnel is slid in along them with its mouth against the core's opening.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-funnel-seated-full-20b636c77729.png" alt="Render of a chute core with both green funnel brackets bolted to its long walls and the tan funnel slid in along them, its mouth against the core's opening">
  <figcaption>Brackets bolted on and funnel home. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

The [Chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}) page carries the other three sub-assemblies that go on the same core, and is where you should return once you're done here.
