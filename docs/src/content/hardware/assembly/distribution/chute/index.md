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
contributors: [alex, brickcyclealice]
warning: >-
  **Part AI-generated, part one builder's account.** The list of pages comes from the machine
  assembly tree in the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=chute), not from an
  actual build. The install order below is how alex built his machine, written down from what
  he described in Discord; nobody else has said whether they did it the same way. Each page
  carries its own note. Correct them as you build.
---

The chute is one per layer. Build the core first, since everything else bolts into its heat inserts.

1. **[Chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }})**. The printed body everything else mounts to, and the 18 heat inserts that hold it all together.
2. **[Funnel]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }})**. The funnel that guides parts into the bin, and the two brackets it hangs from. Its size decides that layer's bin set, so pick it before printing.
3. **[Door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }})**. The door itself, the bearing assembly it swings on, the servo adapter, and the [MG995 servo]({{ '/hardware/assembly/distribution/chute/mg995-servo/' | relative_url }}) that drives it. Built as a unit, then bolted on.
4. **[Layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }})**. The pair that joins this layer's chute to the one below.
5. **[PCB]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }})**. The layer adapter board that drives the servo.

## Installing the chutes in the machine

**The chutes do not go in as you build the layers.** Build the whole frame first, then put the chutes in one at a time. That is the correction alex gave when the interleaved order was suggested to him: "first build all the frame then add the chutes one by one without funnel."

{% include step.html n="1" title="Build the whole frame first, upside down" %}

Lay the [top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}) on the floor with its top plate down, then stack every [layer]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}) onto it. Finish the framing before any chute goes near it.

Building inverted pays for itself here: with the machine upside down, each layer's vertical screws are driven **downwards from above** rather than reached from underneath.

{% include step.html n="2" title="Put the chutes in one at a time" %}

With the frame finished, fit the chutes one after another rather than one per layer as the tower goes up. Each one goes in as a unit, the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}) with the parts above already bolted to it, and since the [layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}) join each chute to the one below, they go in in order.

{% include step.html n="3" title="Leave the funnels off" %}

The chutes go in **without their funnels fitted**. When the funnels go on afterwards is not recorded anywhere, so treat that as an open question rather than assuming it happens just before the Lazy Susan.

{% include step.html n="4" title="Bottom Lazy Susan, then the feeder" %}

The [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}) and its Lazy Susan go on after the chutes. The [feeder]({{ '/hardware/assembly/feeder/' | relative_url }}) is the very last thing on the machine, which is BrickCycleAlice's reading of the order and one alex confirmed for his own build.

If you built yours in a different order, that is worth saying: this is one machine, not a house method.
