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
---

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><strong>AI-generated first draft.</strong> Written from the parts registry in the <a href="https://parts-calculator.basically.website/assembly?focus=classification-chamber">parts calculator</a>, not from an actual build. The assembly order is not recorded anywhere yet, so this page lists what the chamber is made of rather than how it goes together. Correct it as you build.</p>
</div>

The classification chamber is where a part is lit and photographed on its way through. It sits on the fourth [C-channel]({{ '/hardware/assembly/feeder/c-channel/' | relative_url }}), the classification-channel one, and its printed parts are white rather than charcoal, so they bounce light onto the part instead of absorbing it.

**Parts, one machine's worth:**

| Part | Qty | Notes |
|---|---|---|
| Classification dome | 1 | Large, roughly a full print bed. White |
| Rotor (finned) | 1 | White. The classification channel's rotor, in place of the feeder's faceted one |
| Camera and LED insert | 1 | White. Carries the camera and the light |

The camera itself is on its own extension: a 50 mm extension tube and a clamp ring hold the 4K camera module, one per machine. The overhead camera mount that hangs off the C-channels is a different part.

{% include step.html n="1" title="Build the classification C-channel" %}

Build the classification channel as a normal [C-channel]({{ '/hardware/assembly/feeder/c-channel/' | relative_url }}), but with the finned rotor rather than a faceted one, and in ash grey rather than charcoal.

{% include step.html n="2" title="Fit the insert, the camera and the dome" %}

Fit the camera and LED insert, then the camera on its extension tube and mount ring, then close the chamber with the dome.

The fasteners for this stage are not recorded yet: <span class="fastener-todo">fastener not recorded</span>.

<div class="img-placeholder">Image coming</div>

The chamber is lit by a 24 V white/daylight LED strip, not by the 50 mm COB plate the feeder light posts use. Even, passive light is the point: the camera has to expose every part of the disc the same way. See [electronics]({{ '/hardware/electronics/' | relative_url }}) for how it is driven and for the current-limiting resistor.
