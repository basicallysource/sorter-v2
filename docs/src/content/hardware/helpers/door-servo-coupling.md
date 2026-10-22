---
layout: default
title: Coupling a chute door to its servo
type: how-to
section: hardware
slug: helper-door-servo-coupling
kicker: Helpers — Coupling a chute door
lede: Fitting the servo adapter between a chute door and its MG995, with the servo at 0° and the door fully open. Done at first setup, once per layer.
permalink: /hardware/helpers/door-servo-coupling/
og_image: https://assets.basically.website/sorter-docs/chute-v3-door-module-coupled-servo-side-full-ab81e16a36f1.png
author: brickcyclealice
contributors: [daddyosbricksbill]
tools_needed: ["Hex key, 2 mm", Small Phillips screwdriver]
warning: >-
  **AI-generated first draft.** Written from the door module page, the SorterOS code and three
  builders' broken servos, not from an actual build. Nobody has coupled a door this way yet, so
  the order of the steps is not checked against a machine.
---

Each chute door is coupled to its servo through the servo adapter you built on the [door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}) page, and bagged with the layer. This page fits it.

**Couple every door with its servo at 0&deg; and the door fully open.** Each time the machine starts, it swings every flap to 0&deg; on the way to opening it. A door coupled at any other angle gets driven into the chute wall at every start.

Do this in [first setup, step 6]({{ '/sorter/first-setup/' | relative_url }}#step-6-servo-configuration), once the layers are saved and the machine has homed, one layer at a time. It is easier with the bins and the funnel out of the section you are working through. To reach a layer's servo bracket, turn the chute with **CCW** and **CW** on **Settings → Chute**.

<ol class="numbered-steps">
  <li><strong>Take the bracket off the core.</strong> Take out its 3 screws and lift it clear, so the servo hangs free on its lead.</li>
  <li><strong>Set the servo to 0&deg;.</strong> On that layer in the flap panel, press the left arrow (<strong>Move toward a lower angle</strong>) until the angle between the arrows reads 0&deg;. The first press makes the shaft jump. Nothing is on it yet, so that does no harm.</li>
  <li><strong>Fit the adapter.</strong> Push it onto the servo's splined shaft, servo side first. Drive the small screw from the servo's bag into the middle of the horn, through the hex socket. It stops the horn creeping off the shaft.</li>
  <li><strong>Hold the door fully open</strong>, lying flat in the chute wall, and offer the bracket up to the core so the adapter's hex slides onto the hex end of the door's shaft. If it will not go on with the door flat, take the bracket away, take the screw out, pull the adapter off, turn it one tooth, and try again. It can take a few tries.</li>
  <li><strong>Bolt the bracket back on</strong> with the same 3 screws: 2 {% include fastener.html size="M3" variant="countersunk" length="12" %} through the side arm and 1 through the lower arm.</li>
  <li><strong>Check the direction.</strong> Press the right arrow (<strong>Move toward a higher angle</strong>) a few times. The door should lift away from the wall, towards closed. If it presses into the wall or clicks instead, go back to 0&deg; and couple it again from step 1, with the door fully closed instead of open.</li>
  <li><strong>Lock open and closed</strong> for that layer, as first setup step 6 says. Open is at or just above 0&deg;.</li>
</ol>

Never turn the door by hand once it is coupled. Move it only with the arrows.

## The finished result

Every layer's door coupled, its bracket bolted on, and the layer reading **Calibrated** in the flap panel with open at or just above 0&deg;.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/chute-v3-door-module-coupled-servo-side-full-ab81e16a36f1.png" alt="Render of a door module on its chute core seen from the servo side: the blue servo bracket on the long wall, the pink and purple servo adapter between the bracket and the bearing cover, the purple race under the opening and the orange door lying open inside it">
  <figcaption>A coupled module from the servo side, door open. The servo itself has no model, so the bracket shows empty. <cite>Rendered from the part geometry, not from a build. Render: Balloon.</cite></figcaption>
</figure>

Back to [first setup, step 6]({{ '/sorter/first-setup/' | relative_url }}#step-6-servo-configuration).
