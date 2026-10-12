---
layout: default
title: Funnel split into hood and floor tray
type: explanation
section: lab
slug: lab-funnel-split-hood-and-floor-tray
kicker: Design and research — Variants — Concepts
lede: "A proposal to print the third-size funnel as two parts, a hood and a shallow floor tray, so the sliding floor lies flat on the print bed and can be ironed smooth."
permalink: /lab/concepts/funnel-split-hood-and-floor-tray/
audience: contributor or builder interested in changing the distribution section
applies_to: hardware-v2
owner: docs
author: soran82
warning: >-
  **Concept, not verified and not built.** Nothing has been printed or test-fitted. All numbers come from the CAD geometry,
  and the jam percentages come from a simple 2D simulation. Nothing on the build pages changes because of this page.
---

This page is a design proposal for the [third-size funnel]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }}) (`gen3_snap_in_bin_third_size`, 18 bins per layer). It changes that funnel only. The half-size funnel is covered under [follow-up](#follow-up).

## Summary

The funnel is split into two printed parts along a plane parallel to the sliding floor:

- **Hood:** the cover plate, the upper walls, the dovetail rails and the outlet end.
- **Floor tray:** the sliding floor with the lower wall stubs.

The tray is trimmed on its underside so the underside is parallel to the floor. The two parts are joined by two guide pins and one M3 screw per side into a heat-set insert.

<h3>Why</h3>

<ul class="bulleted-list">
  <li><strong>Primary:</strong> the sliding floor can be smoothed during printing. LEGO parts slide over the floor, and the printer can iron it to reduce friction, but only if the surface lies parallel to the print bed. In the original orientation the floor is inclined against the bed and the underside overhangs (a curved outlet underside, 27° rail undersides).</li>
  <li><strong>Secondary:</strong> the funnel is easy to pull out of its brackets. With the split, the channel can then be opened from below to clear a jam, and the part that wears (the floor) can be replaced without reprinting the whole funnel.</li>
</ul>

<h3>What changes</h3>

<ul class="bulleted-list">
  <li>The split plane is parallel to the floor, 14.2 mm above it (through the lower edge of the wall-end bevels). The wall height above the floor is therefore constant along the whole length.</li>
  <li>The underside is trimmed parallel to the floor instead of adding material. The floor is a uniform 4.3 mm thick (it was 6.5 to 24 mm) and the curved, overhanging outlet underside is gone. Volume drops from 551,000 mm³ to about 430,000 mm³ (−22 %).</li>
  <li>The joint is two guide pins (4.0 mm diameter, front and rear) and one M3 × 16 mm countersunk screw (middle) per side. The screw runs from below through the tray wall (90° countersink seat, head 9.3 mm above the underside) into a Ruthex M3 × 5.7 heat-set insert in the hood. Pin bores are 4.4 mm, insert bores 4.0 mm.</li>
  <li>Everything of the joint sits inside the wall (9 to 16 mm thick at the joint). Nothing protrudes into the channel.</li>
  <li><strong>Unchanged:</strong> the side dovetail rails that carry the funnel in the funnel brackets, the inner channel geometry, and the floor inclination relative to the part.</li>
</ul>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/funnel-split-fig1-assembled-full-2628d00f5a25.png" alt="Oblique view from above of the assembled third-size funnel. The hood, in orange, forms the cover plate and upper walls and has a dovetail rail on its side. The floor tray, in blue, is a shallow part underneath, visible at the open outlet end.">
  <figcaption>The assembled funnel. Floor tray blue, hood orange. <cite>Rendered from the part geometry, not from a build. Render: Jan-Henning Grell (Soran82).</cite></figcaption>
</figure>

## Printing

| | Floor tray | Hood |
|---|---|---|
| Bed face | A (underside, 14,527 mm²) | N (inlet end rim, 1,386 mm²) |
| Orientation | Floor facing up, horizontal | Standing on its inlet end, cover plate vertical |
| Overhangs below 45° | None of relevance (one small flat of 34 mm²) | 2 × 24 mm² ledges at the rails. The rails are self-supporting (63°). |
| Support | None | None. A brim of 8 to 10 mm is recommended. |
| Special | Ironing on the floor (10,927 mm² plus an 859 mm² lip in one plane) | Height 169 mm, centre of gravity 6.9 mm inside the bed contact area |

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/funnel-split-fig2-print-bed-faces-full-ff7d84e2142c.png" alt="The assembled funnel seen from below and the front, with the two print-bed faces in green. Face A is the large flat underside of the floor tray. Face N is the narrow rim around the inlet end of the hood.">
  <figcaption>The print-bed faces, in green. The floor tray lies on face A with the floor facing up. The hood stands on face N, its inlet end. <cite>Rendered from the part geometry, not from a build. Render: Jan-Henning Grell (Soran82).</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/funnel-split-fig3-screw-joint-section-full-54a8350b4af2.png" alt="Section through the screw joint at y = 52 mm. A countersunk seat on the underside of the floor tray narrows to a through hole, and the hole lines up with the insert bore in the hood above it.">
  <figcaption>Section through the screw joint (y = 52 mm): the countersink seat below, the through hole, and the insert bore in the hood. <cite>Rendered from the part geometry, not from a build. Render: Jan-Henning Grell (Soran82).</cite></figcaption>
</figure>

## Original and proposed

| Topic | Original | This proposal |
|---|---|---|
| Sliding floor | Not ironable (inclined to the bed, overhanging underside) | Ironable over the full area, horizontal during printing |
| Support (tray / hood) | Needed | None / none |
| Material | 551,000 mm³ | 430,000 mm³ (−22 %) |
| Floor thickness | 6.5 to 24 mm | Uniform 4.3 mm |
| Rails and brackets | | Unchanged |
| Fasteners | | Only parts already in the BOM (M3 × 16 countersunk, Ruthex M3 × 5.7) |
| Wear | The whole funnel | Only the floor tray (about 25 % of the material) is replaced |
| Clearing a jam | The funnel stays closed | Pull the funnel out, remove 2 screws, and the channel is open from below |
| Experiments | A new funnel per variant | A new tray only (for example another floor shape or material) |

## Trade-offs and risks

<ul class="bulleted-list">
  <li><strong>Two parts instead of one.</strong> More print jobs, plus 2 × M3 × 16 mm countersunk and 2 × Ruthex M3 × 5.7 for each third-size funnel.</li>
  <li><strong>A joint line in the inner walls.</strong> A misfit at the joint can leave a small edge that a brick may catch on. The proposed mitigation is to assemble first, then apply PTFE tape across the joint.</li>
  <li><strong>The hood is printed standing.</strong> It has 5 mm wide bed contact at 169 mm height, so a brim is needed and there is a tip-over risk during printing.</li>
  <li><strong>Thin floor (4.3 mm).</strong> Fine for light LEGO parts, but untested for long-term wear and stiffness.</li>
  <li><strong>Outlet underside.</strong> The curved underside of the outlet is removed. If it has a guiding function in the hex frame or at the bins, that must be checked (it is not documented).</li>
  <li><strong>Large compact pieces</strong> (for example 6 × 6 or 4 × 8) still jam. That jam is geometric, not friction, so they should still be routed to a half-size layer.</li>
</ul>

## Jam behaviour (simulation)

A simple 2D rigid-body model with Coulomb friction (floor and walls) compared a 2 × 10 plate (80 × 16 mm) going through the funnel. Each variant used the same random start poses and velocities, 200 throws per variant.

| Variant | Floor μ | Wall μ | 2 × 10 jammed |
|---|---|---|---|
| A. Current: raw PLA | 0.35 | 0.40 | 55 % (48 to 62) |
| B. Ironed floor only | 0.25 | 0.40 | 22 % (16 to 28) |
| C. PTFE tape on inner walls only | 0.35 | 0.10 | 50 % (43 to 57) |
| D. Ironed floor and PTFE tape on inner walls | 0.25 | 0.10 | 5 % (2 to 8) |
| E. As D, plus PTFE on the floor | 0.15 | 0.10 | 8 % (4 to 12) |

In this model, ironing the floor and taping the inner walls work together, and neither alone is sufficient. The model ignores studs, impact from the chute and several pieces at once, and the friction values are literature values. The ordering of the variants is the useful result, not the absolute percentages.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/funnel-split-fig4-jam-simulation-full-0552623b8ef0.png" alt="Two plots of the same 14 start poses of a 2 by 10 plate in the funnel, seen from above. In the current funnel with raw PLA, several plates are stuck crosswise against the converging walls, drawn in red, and a few pass, drawn in green. With an ironed floor and PTFE tape on the inner walls, one plate is stuck and the rest pass.">
  <figcaption>The same 14 start poses: the current funnel (top) and an ironed floor with PTFE on the walls (bottom). Green passes, red jams. <cite>Drawn from the simulation, not from a build. Drawing: Jan-Henning Grell (Soran82).</cite></figcaption>
</figure>

## Follow-up

If this design is accepted and proves itself in use, the same split (hood plus floor tray, trimmed underside, pins and M3 screw with heat-set insert) could be applied to the half-size funnel, so that both funnels share one construction. This proposal deliberately changes the third-size funnel only.

## Verification status

<ul class="bulleted-list">
  <li><strong>Done:</strong> the bodies are valid single solids, the assembled parts do not overlap, overhang analysis for both print orientations, volume and bed-contact figures, section views, and the jam simulation.</li>
  <li><strong>Not done:</strong> no print, no fit check, no test with real pieces, no check against the bins or the hex frame, and no strength test of the pins or the insert joint.</li>
  <li><strong>Needs checking:</strong> bracket compatibility (the rails are unchanged, but this should be confirmed), whether a joint line in the inner walls is acceptable, and the guide pin clearance (0.2 mm per side is an assumption).</li>
</ul>

<h3>Suggested first prints and tests</h3>

<ol class="numbered-list">
  <li>Print the hood standing on N with a brim, and check bed adhesion and warping.</li>
  <li>Print the floor tray with ironing, and check floor flatness and the countersink seats.</li>
  <li>Assemble, check the joint line and the pins, then apply PTFE tape across the joint.</li>
  <li>Run the same set of long bricks (2 × 10, 1 × 10, 2 × 8, 4 × 8) before and after, 20 throws each.</li>
</ol>

## Files

The CAD files are STEP, in two orientations each: the one of the original funnel file, and the print orientation.

| File | Content |
|---|---|
| [`floor_tray_original_orientation.step`](https://assets.basically.website/sorter-parts/funnel-third-split-floor-tray-original-orientation-a39418bebf9d.step) | Floor tray, in the orientation of the original file |
| [`hood_original_orientation.step`](https://assets.basically.website/sorter-parts/funnel-third-split-hood-original-orientation-f61be5b84260.step) | Hood, in the orientation of the original file |
| [`floor_tray_print_A-down.step`](https://assets.basically.website/sorter-parts/funnel-third-split-floor-tray-print-a-down-bd448cbad8db.step) | Floor tray, print orientation (A on the bed, floor up) |
| [`hood_print_N-down.step`](https://assets.basically.website/sorter-parts/funnel-third-split-hood-print-n-down-8060731e604f.step) | Hood, print orientation (N on the bed) |

## Appendix: views of the single parts

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/funnel-split-app-floor-tray-above-full-1a5f10204a75.png" alt="The floor tray from above, floor facing up, with the guide pins and the screw holes visible along the wall stubs.">
  <figcaption>The floor tray from above (floor up, pins and screw holes visible). <cite>Rendered from the part geometry, not from a build. Render: Jan-Henning Grell (Soran82).</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/funnel-split-app-floor-tray-below-full-41ea766a195b.png" alt="The floor tray from below. The underside is one plane face with the countersunk screw seats in it.">
  <figcaption>The floor tray from below: the plane print-bed face with the countersunk screw seats. <cite>Rendered from the part geometry, not from a build. Render: Jan-Henning Grell (Soran82).</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/funnel-split-app-hood-below-full-3b5fdb9c68f3.png" alt="The hood from below, showing the joint side with the pin bores and the insert bores along the lower edge of each wall.">
  <figcaption>The hood from below: the joint side with the pin bores and the insert bores. <cite>Rendered from the part geometry, not from a build. Render: Jan-Henning Grell (Soran82).</cite></figcaption>
</figure>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/funnel-split-app-hood-section-full-718f3675af17.png" alt="A longitudinal section through the middle of the hood at y = 0.">
  <figcaption>A longitudinal section through the middle of the hood (y = 0). <cite>Rendered from the part geometry, not from a build. Render: Jan-Henning Grell (Soran82).</cite></figcaption>
</figure>
