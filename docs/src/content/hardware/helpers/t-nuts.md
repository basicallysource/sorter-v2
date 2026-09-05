---
layout: default
title: Fitting T-nuts
type: how-to
section: hardware
slug: helper-t-nuts
kicker: Helpers — T-nuts
lede: How the machine's roll-in T-nuts go into the extrusion, and what changes if you buy a different style.
permalink: /hardware/helpers/t-nuts/
author: barthel
parts_needed:
  - part: tnut-m5-2020
tools_needed: [Hex key]
---

Every M5 screw that fastens a printed part to aluminum extrusion, rather than tapping into plastic, lands in one of these. The parts list calls for a **spring-loaded roll-in T-nut** for 2020 extrusion, and that choice is what lets the assembly pages ask for T-nuts at the step that uses them instead of making you plan them in advance.

## Roll-in

A roll-in T-nut goes into the slot **anywhere along its length**. Hold it so its long axis lines up with the slot opening, push it in, then turn it a quarter turn so the ends sit under the lips of the slot. A spring leaf or a spring-loaded ball on the back then holds it where you put it, so it stays in position while you line the part up and it does not fall out if you take the screw back out later.

Two things follow, and they are why the machine specifies this style:

- **You never have to fit one early.** No frame has to come apart, and no extrusion end has to be left open, to add a T-nut to a slot that is already built into the machine.
- **You can undo a joint without losing the nut.** Take the screws out, lift the part off, and the T-nuts are still sitting in the slot where they were.

<figure class="video-figure">
  <div class="video-embed video-embed-wide">
    <iframe
      src="https://www.youtube.com/embed/bGmanrPj7s0?start=68"
      title="How roll-in T-nuts go into extrusion"
      allow="encrypted-media; picture-in-picture; web-share"
      allowfullscreen
      loading="lazy"></iframe>
  </div>
  <figcaption>Starts at 1:08, where the roll-in T-nut comes up. The four variants it then shows (set screw, flex handle, ball spring, spring leaf) are all roll-in; this machine's is a spring one. <cite>Video: 80/20, linked by Marc.</cite></figcaption>
</figure>

## If you have a different style

Cheaper T-nuts are usually **slide-in**: a plain rectangular block with no spring, which can only be loaded from an open end of the extrusion and then slid along to where it is needed. They work, but they change the order you have to build in, because a slot that has a bracket on both ends can no longer take one.

If that is what you have, fit these before the frames close around them:

- **4 per A/G extrusion** on each [hex frame]({{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}), toward the outer end of the extrusion, for the [bin retainers]({{ '/hardware/assembly/distribution/bin-frame/bin-retainers/' | relative_url }}).
- **2 each into 3 of the 6 B/H spokes** of the bottom layer's frame, alternating around the ring, for the [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }})'s Lazy Susan mounts.

Slide-in nuts also do not hold their position on their own, so a nut you fitted early can drift along the slot before you get to the part that uses it. Fitting the part in the same session is easier than trying to line up a nut you cannot see.
