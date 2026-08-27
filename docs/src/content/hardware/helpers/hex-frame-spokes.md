---
layout: default
title: Attaching the hexagonal frame's spokes
type: how-to
section: hardware
slug: helper-hex-frame-spokes
kicker: Helpers — Hexagonal frame spokes
lede: How the Frame 90° bracket, the B/H spoke and the Frame crossbeam actually go together — friction and alignment nubs, not screws or T-nuts.
permalink: /hardware/helpers/hex-frame-spokes/
author: barthel
contributors: [spencer, brickcyclealice]
warning: >-
  **AI-generated, DRAFT.** Written entirely from a Discord conversation — quoted
  throughout, with links to every message — not from a build, and not checked
  against a machine. It exists because [Regular layers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }})'s
  step 2, as currently published, instructs the opposite of what Spencer says
  the design actually is: drilling out the Frame 90° bracket's holes and
  fastening the spokes with M5 screws and T-nuts. That page has not yet been
  reconciled with this one. Until it is, treat both as unapproved for this
  part of the build, and check with barthel or Spencer before following
  either.
parts_needed:
  - part: frame-90deg-bracket
    qty: 12
  - part: frame-crossbeam
    qty: 6
  - part: ext-2020-bh
    qty: 6
---

This covers one part of building a hexagonal frame: attaching the six B/H spokes and their Frame crossbeams to the inside of the outer hexagon ring, using the Frame 90° bracket. It does not cover the outer ring itself (the A/G extrusions and External bracket — side, joined with M5 × 16 screws) — nothing here contradicts that part of [Regular layers, step 1]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}#step-1), which this page assumes is already built.

## No screws, no T-nuts, no drilling

Spencer confirmed this directly on 2026-08-26, after a Discord thread had gone the other way and ended up with the parts calculator marking the Frame 90° bracket as broken for a hole that "prints too tight" for an M5 screw:

> "Can we never ever ever put something in the docs that says to mod the part to fix a broken stl"
> "(Which was not actually broken, it was intentionally designed to avoid nuts"
> "Those parts dont need any hardware at all"
> — Spencer, [#balloon-general](https://discord.com/channels/1430279849171222682/1542144753641066616/1542194581125337181) ([2](https://discord.com/channels/1430279849171222682/1542144753641066616/1542194655964434644), [3](https://discord.com/channels/1430279849171222682/1542144753641066616/1542195024031129610))

Asked directly whether that meant *zero* hardware, he confirmed it does, for the Frame 90° bracket and the Frame crossbeam both:

> "They're just resting in there and the nubs align it with aluminum but nothing holds it. I left the holes at the time incase it wasn't sufficient. Lots of holes like that in the machine..."
> "This entire assembly has no hardware"
> — Spencer, [#balloon-general](https://discord.com/channels/1430279849171222682/1542144753641066616/1542299893329305701) ([2](https://discord.com/channels/1430279849171222682/1542144753641066616/1542300003501084813))

> "\[Frame crossbeam bolted, or also just sitting there?\]" / "Just sitting. Once the hex is together it holds itself"
> — BrickCycleAlice and [Spencer, #balloon-general](https://discord.com/channels/1430279849171222682/1542144753641066616/1542316381956087938)

So the holes cast into the Frame 90° bracket are a fallback Spencer left in the model in case the friction fit ever proves insufficient, not a feature the standard build uses. **Do not drill them out, and do not fasten through them with an M5 screw and T-nut as [the current Regular layers page]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}#step-2) says to.**

This is the production part, not a one-off experiment: it traces back to a "hot swap" layer-frame redesign Spencer demoed in [#distribution on 2026-06-04](https://discord.com/channels/1430279849171222682/1437144782819426537/1512229833139159100), built with no screws at all, confirming to mistermcghee that it was a drop-in fastener change for the existing brackets —

> "Yes, I just cant muster the thought of more nuts and screws"
> — [Spencer, #distribution](https://discord.com/channels/1430279849171222682/1437144782819426537/1512236943960838174)

— and he flagged the same caveat that applies here: fit depends on your own printer and extrusion's T-slot tolerance, tuned at the time to 0.2 mm layers on a Bambu printer. If a slot is too shallow the parts won't grip firmly; that's what the leftover holes are for, as a fallback to a screw and T-nut, not the default.

{% include fastener-legend.html %}

{% include step.html n="1" title="Fit the Frame 90° brackets" %}

<div class="img-placeholder">Image coming</div>

Rest 2 Frame 90° brackets against the inner face of one A/G extrusion of your assembled outer hexagon, at the point where a B/H spoke will land. Alignment nubs on the bracket key against the extrusion and hold it in place on their own — there is no screw or T-nut here.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><a href="https://discord.com/channels/1430279849171222682/1542144753641066616/1542316458355195904">Spencer's own note</a> on this: "The 90 deg brackets could probably use a tiny bit more friction, one might fall out when youre handling it before inserting into the outer frame." Handle the half-built frame gently until the spoke and crossbeam below are in and the hexagon is closed.</p>
</div>

{% include step.html n="2" title="Slide in the spoke and crossbeams" %}

<div class="img-placeholder">Image coming</div>

Slide piece B/H (Spoke / Interface spoke (short)) into the 2 Frame 90° brackets you just placed. It is held the same way, by fit against the brackets, not by a fastener.

Slide a Frame crossbeam into place on the spoke until it is level with the end of the extrusion. It also just sits there; nothing screws it down.

Perform these two steps 2 more times, on every 2nd side of the hexagon, then repeat for the remaining 3 sides, same as [Regular layers, step 2]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}#step-2) currently describes for the sequencing — that part of the existing page isn't in question, only its fasteners are.

{% include step.html n="3" title="Close the hexagon in two halves" %}

Spencer's own assembly tip, worth following exactly:

> "The trick is to do the two halves one at a time and then \[join\] them together. Dont try to make the entire hexagon one piece at a time, you wont be able to get the last one"
> — [Spencer, #balloon-general](https://discord.com/channels/1430279849171222682/1542144753641066616/1542316707970813993)

Build three spoke assemblies on one half of the hexagon, then the other three on the other half, and only then bring the two halves together. Once the hexagon is closed, the spokes and crossbeams hold themselves in place — "once the hex is together it holds itself."

## What this doesn't settle

- **No photo or video of this method exists yet.** Everything above is reasoned from what Spencer wrote, not from watching it built. If you build one of these and it doesn't hold the way this page describes, say so — the fallback is exactly what the holes are for: an M5 screw into a T-nut on the long side, matching what the old instructions said.
- **The outer hexagon ring (A/G + External bracket — side) is unaffected.** Its M5 × 16 self-tap / T-nut screws are a different part and a different joint; nothing here changes that step.
- **[Regular layers]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}) and [Top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}) both still describe the old drill-and-fasten method**, with a video and several photos of it, and their parts lists still count M5 × 12 screws and T-nuts for this joint. None of that has been reconciled with this page yet.
