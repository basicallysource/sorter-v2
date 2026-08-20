---
layout: default
title: Classification chamber
type: how-to
section: hardware
slug: assembly-classification-chamber
kicker: Feeder — Classification chamber
lede: Where parts are imaged for classification.
permalink: /hardware/assembly/feeder/classification-chamber/
author: spencer
contributors: [barthel]
warning: >-
  **AI-generated first draft.** Written from the parts registry in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=classification-chamber),
  not from an actual build. The assembly order is not recorded anywhere yet, so this page
  lists what the chamber is made of rather than how it goes together. Correct it as you build.
parts_needed:
  - part: classification-dome
    qty: 1
  - part: rotor-finned
    qty: 1
  - part: camera-led-insert
    qty: 1
  - part: camera-extension
    qty: 1
  - part: camera-extension-mount
    qty: 1
  - part: cam-imx415
    qty: 1
---

The classification chamber is where a part is lit and photographed on its way through. It sits on the fourth [C-channel]({{ '/hardware/assembly/feeder/c-channel/' | relative_url }}), the classification-channel one.

The parts are in the list above. No fasteners are recorded for this stage yet.

{% include fastener-legend.html %}

- **One per machine.**
- The three chamber parts print **white** rather than charcoal, so the chamber bounces light onto the part instead of absorbing it.
- The Classification dome is large, roughly a full print bed.
- The camera sits on its own extension: a 50 mm extension tube and a clamp ring hold the 4K camera module. The overhead camera mount that hangs off the C-channels is a different part.

{% include step.html n="1" title="Build the classification C-channel" %}

Build the classification channel as a normal [C-channel]({{ '/hardware/assembly/feeder/c-channel/' | relative_url }}), but with the finned rotor rather than a faceted one, and in ash grey rather than charcoal.

{% include step.html n="2" title="Fit the insert, the camera and the dome" %}

Fit the Camera & LED insert, then the camera on its extension tube and mount ring, then close the chamber with the dome.

The fasteners for this stage are not recorded yet: <span class="fastener-todo">fastener not recorded</span>.

<div class="img-placeholder">Image coming</div>

{% include step.html n="3" title="Light the chamber" %}

The chamber is lit by a 24 V white/daylight LED strip, not by the 50 mm COB plate the feeder light posts use. Even, passive light is the point: the camera has to expose every part of the disc the same way. See [electronics]({{ '/hardware/electronics/' | relative_url }}) for how it is driven and for the current-limiting resistor.
