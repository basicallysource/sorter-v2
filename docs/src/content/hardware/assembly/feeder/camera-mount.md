---
layout: default
title: Overhead camera mount
type: how-to
section: hardware
slug: assembly-overhead-camera-mount
kicker: Feeder — Overhead camera mount
lede: The rod arm that hangs a detection camera over a C-channel.
permalink: /hardware/assembly/feeder/camera-mount/
author: barthel
warning: >-
  **Skeleton page.** Written from the parts registry in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=camera-mount), not from a
  build. The parts are recorded; the assembly order, every screw's position, the camera
  fixing and all photographs are missing. Fill it in as you build.
parts_needed:
  - part: camera-mount-part-6
    qty: 1
  - part: camera-mount-part-37
    qty: 1
  - part: camera-mount-part-37b
    qty: 1
  - part: camera-mount-rod-mount
    qty: 2
  - part: rod-steel-3-8
    qty: 2
  - part: scr-m3-12-cs
    qty: 3
  - part: nut-m3
    qty: 3
---

The overhead camera mount is a pair of 3/8 in steel rods clamped to a [C-channel]({{ '/hardware/assembly/feeder/c-channel/' | relative_url }}), carrying a printed arm that holds a detection camera above the channel.

The fasteners and quantities are in the parts list above and are called out inline at each step.

{% include fastener-legend.html %}

- **Build 2 per machine.** The parts list above is one arm's worth, so it takes 4 rod mounts and 4 rod pieces in total.
- **Rod is bought as stock and cut.** One 4 ft length of 3/8 in steel rod yields all four roughly 1 ft pieces. The exact cut length is not recorded yet.
- The camera these carry is the **OV9732 720p module**, which the parts registry lists as the C-channel and drop-plate detection camera. The 4K IMX415 is a different camera and belongs to the [classification chamber]({{ '/hardware/assembly/feeder/classification-chamber/' | relative_url }}).
- Two arms for three feeder channels is not a mistake: the software's `split_feeder` camera layout puts a camera on C2, on C3 and on the carousel, which lines up with the two arms and the two [light posts]({{ '/hardware/assembly/feeder/light-post/' | relative_url }}). That pairing is inferred from the parts counts and the software config, not from a build.

{% include step.html n="1" title="Cut the rods" %}

Cut two pieces of 3/8 in rod per arm. Length not recorded yet.

{% include step.html n="2" title="Clamp the rod mounts to the C-channel" %}

Two Rod-to-C-channel mounts (Part 33) hold the rods on the channel. Which holes on the channel they use, and what fastens them, is not recorded yet: <span class="fastener-todo">fastener not recorded</span>.

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Join the two arm halves" %}

Overhead camera mount A (part 37) and B (part 37b) join through the A/B connector (part 6), with the 3 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws and 3 M3 nuts in the list above. Which joint takes which screw is not recorded yet: <span class="fastener-todo">fastener not recorded</span>.

<div class="img-placeholder">Image coming</div>

{% include step.html n="4" title="Fit the camera and set the height" %}

Nothing is recorded yet about how the camera fastens to the arm, how high above the channel it sits, or how it is squared to the channel. All three change what the detection zones see, so record what worked. Zone setup itself is software, see the [camera calibration]({{ '/sorter/camera-calibration/' | relative_url }}) page.
