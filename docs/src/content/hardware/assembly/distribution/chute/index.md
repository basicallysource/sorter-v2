---
layout: default
title: Chute
type: landing
section: hardware
slug: assembly-chute
kicker: Distribution — Chute
lede: The rotating chute that aims parts at the correct bin.
permalink: /hardware/assembly/distribution/chute/
author: spencer
warning: >-
  **AI-generated first draft.** The order and the descriptions below come from the machine
  assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=chute), not from an
  actual build. Each page carries its own note. Correct them as you build.
---

The chute is one per layer. Build the core first, since everything else bolts into its heat inserts.

1. **[Chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }})**. The printed body everything else mounts to, and the 18 heat inserts that hold it all together.
2. **[Funnel]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }})**. The funnel that guides parts into the bin, and the two brackets it hangs from. Its size decides that layer's bin set, so pick it before printing.
3. **[Door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }})**. The door itself, the bearing assembly it swings on, the servo adapter, and the [MG995 servo]({{ '/hardware/assembly/distribution/chute/mg995-servo/' | relative_url }}) that drives it. Built as a unit, then bolted on.
4. **[Layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }})**. The pair that joins this layer's chute to the one below.
5. **[PCB]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }})**. The layer adapter board that drives the servo.
