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

The whole chute stack rotates as one unit, on the [top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }})'s Lazy Susan, driven by the stepper motor and gear train described there. The bins themselves don't move; each chute's door opens for a moment once it's rotated into position over the correct bin, dropping the part in. See [Door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}) and [Layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}) for how that opening is driven and timed.

1. **[Chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }})**. The printed body everything else mounts to, and the 18 heat inserts that hold it all together.
2. **[Funnel]({{ '/hardware/assembly/distribution/chute/funnel/' | relative_url }})**. The funnel that guides parts into the bin, and the two brackets it hangs from. You choose one of two sizes for each layer, which sets that layer's funnel and its bin set together, so make the choice before printing either.
3. **[Door module]({{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }})**. The door itself, the bearing assembly it swings on, the servo adapter, and the MG995 servo that drives it. Built as a unit, then bolted on.
4. **[Layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }})**. The pair that joins this layer's chute to the one below.
5. **[Layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }})**. The board that drives the servo.

## Installing the chutes in the machine

**Do not add the chutes while you build the layers.** Build the whole frame first, then add the chutes afterward, one at a time. alex was clear about this: "first build all the frame then add the chutes one by one without funnel."

{% include step.html n="1" title="Build the whole frame first, upside down" %}

Put the [top interface]({{ '/hardware/assembly/distribution/top-interface/' | relative_url }}) on the floor with its top plate facing down, then stack every [layer]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}) on top of it. Finish the whole frame before you add any chutes.

Building it upside down helps here: each layer's vertical screws can be driven **down from above** instead of reached from underneath.

{% include step.html n="2" title="Add the chutes one at a time" %}

Once the frame is finished, add the chutes one at a time, in layer order. Each chute goes in as a complete unit, the [chute core]({{ '/hardware/assembly/distribution/chute/chute-core/' | relative_url }}) with its own parts already attached. The [layer connectors]({{ '/hardware/assembly/distribution/chute/layer-connectors/' | relative_url }}) join each chute to the one below it, so working through the layers in order matters more than which direction you start from.

Plug each chute's ribbon cable in before you slot it into the frame if the harness is easier to reach on the bench; see [Layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}) for the connector.

{% include step.html n="3" title="Leave the funnels off" %}

Add the chutes **without their funnels**. Nobody has said yet when the funnels should go on, so don't assume it happens right before the Lazy Susan step below.

{% include step.html n="4" title="Bottom Lazy Susan, then the feeder" %}

The [bottom interface]({{ '/hardware/assembly/distribution/bin-frame/bottom-interface/' | relative_url }}) and its Lazy Susan go on after the chutes, and the [feeder]({{ '/hardware/assembly/feeder/' | relative_url }}) goes on last. Both BrickCycleAlice and alex built their machines in this order.

If you built yours in a different order, let us know. This is how one person built their machine, not an official method everyone has to follow.
