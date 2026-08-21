---
layout: default
title: Light post
type: how-to
section: hardware
slug: assembly-light-post
kicker: Feeder — Light post
lede: The vertical COB light that lights a C-channel for the overhead camera.
permalink: /hardware/assembly/feeder/light-post/
author: barthel
warning: >-
  **Skeleton page.** Written from the parts registry in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=light-post), not from a
  build. The parts and the two screws into the NEMA bracket are recorded; the rest of the
  order, the remaining screws and every photograph are still missing. Fill it in as you build.
parts_needed:
  - part: light-post
    qty: 1
  - part: light-post-cap
    qty: 1
  - part: light-post-cap-adapter
    qty: 1
  - part: led-cob-50mm-24v
    qty: 1
  - part: scr-m3-12-cs
    qty: 3
  - part: scr-m3-20-cs
    qty: 2
---

The light post is a vertical printed post carrying a 50 mm COB LED plate, which lights the channel from the side so the overhead camera sees parts against an even background. It bolts to a [C-channel]({{ '/hardware/assembly/feeder/c-channel/' | relative_url }})'s NEMA bracket.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

- **Build 2 per machine**, one each on the second and third feeder channels. The parts list above is one post's worth.
- The cap prints **white**; the post follows the feeder colour.
- Side lighting is deliberate. Overhead COB lighting was tried first and washed out the ArUco tags, see [feeder experiments]({{ '/lab/feeder-experiments/' | relative_url }}).

{% include step.html n="1" title="Assemble the post, adapter and cap" %}

The post, the Light post cap adapter and the Light post cap join with the 3 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws in the list above.

How the three screws split between the two joints is not recorded yet: <span class="fastener-todo">fastener not recorded</span>.

<div class="img-placeholder">Image coming</div>

{% include step.html n="2" title="Fit the COB plate" %}

The 50 mm COB plate mounts in the cap. How it is retained is not recorded yet: <span class="fastener-todo">fastener not recorded</span>.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The C-channel COB light boards need a current-limiting resistor.</b> <b>220&#8486;, 1/4 W, in series, one per board.</b> Wired straight to 24V a 50 mm COB plate pulls about 0.5A and melts its printed mount. A board fed from a basically board v1.3 LED header already has one on the board. Full detail: <a href="{{ '/hardware/electronics/#43--leds-from-basically-board-v13' | relative_url }}">LEDs, on the wire harness page</a>.</p>
</div>

{% include step.html n="3" title="Bolt the post to the NEMA bracket" %}

The post bolts to the C-channel's NEMA bracket with 2 {% include fastener.html size="M3" variant="countersunk" length="20" %} screws that thread straight into the printed post. No heat insert, no nut.

Which of the bracket's holes they use, and which way the post faces relative to the channel, are not recorded yet.

<div class="img-placeholder">Image coming</div>

{% include step.html n="4" title="Aim it" %}

Nothing is recorded yet about how the post is aimed or how high the plate sits above the channel. Both matter to the camera exposure, so record what worked when you build one.
