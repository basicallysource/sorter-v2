---
layout: default
title: Make your own LED drop
type: reference
section: hardware
slug: electronics-led-drop
kicker: Electronics — LED drop
lede: Wire a camera lamp's LED strip back to a 24V LED header on basically board v1.3, with or without a soldering iron.
permalink: /hardware/electronics/led-drop/
author: brickcyclealice
contributors: [effreek, barthel]
warning: >-
  **Not validated against a built machine.** The lamp end here is from a real build; the run
  back to the board is the LED drop off the harness notes, and the values marked **GUESS** in
  the [WireViz drawing]({{ '/hardware/electronics/wireviz/' | relative_url }}), including the
  wire gauge and which board pin is +24V, are guesses. Meter the header before you plug a lamp
  into it.
parts_needed:
  - part: led-strip-24v
    qty: 1
  - part: led-strip-connector-8mm
    qty: 1
  - part: dupont-lead-2p-1m
    qty: 1
tools_needed: [Side cutters, Multimeter, "Only if you solder: iron, solder and heatshrink", "Only if you make your own lead: crimp tool"]
---

Each [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}) needs one LED drop: a two-conductor run at 24V from an LED header on basically board v1.3 to the ring of strip inside the lamp. A machine has three lamps, so three drops, on C-channels 2 and 3 and the classification channel. Each one carries about 0.5A.

**The quantities above are for one drop, so a machine needs three of each**, except the strip: one 5 m roll cuts into all three rings, and the Dupont leads come five to a pack. So a machine is one roll, three connectors and one pack.

<dl class="spec-list">
  <dt>Board end</dt><dd>A 2-pin 2.54 mm Dupont plug onto one of the board's four LED headers, <code>J8</code> to <code>J11</code>.</dd>
  <dt>In between</dt><dd><b>On a v1.3 board it is Dupont straight to the strip</b>: one continuous pair of 22 AWG, about a metre, board to lamp, no connector in the middle. That is how the lamp Spencer photographed is built, and it is what Jon (who drew the harness) says to do.</dd>
  <dt>Optional unplug point</dt><dd>A 5.5 × 2.1 mm barrel pair partway along, so the lamp comes off the machine without unwiring, which splits the run into about 36 in of feed and about 6 in of pigtail. The harness notes still draw it that way. Fit it if you want it; nothing needs it.</dd>
  <dt>Lamp end</dt><dd>A solderless clamp-on connector, or solder, onto the two pads at the cut end of the strip.</dd>
</dl>

<div class="callout">
  <p><b>You do not need a soldering iron.</b> A clamp-on connector at the strip and a ready-made 2-pin Dupont pigtail at the board is a whole drop out of two bought parts, joined once in the middle. You do not need a crimp tool either unless you make the Dupont end yourself.</p>
</div>

## Choosing the parts

<dl class="spec-list">
  <dt>Which connector</dt><dd>Three variants of the same body, all SuperBrightLEDs, all <b>8 mm COB only</b>, 22 AWG, 3A. <code>SBL-RA2P-8</code> ($1.59) is the one in the list above: it bites the strip at one end and <b>your own wire</b> at the other, no wire supplied. <code>SBL-RA2P-8-1</code> ($1.69) is the same thing with 4 in of tinned lead already on it, so you splice rather than clamp. <code>SBL-RA2P-8-DC</code> ($2.79) ends in a 5.5 × 2.1 mm barrel socket, which is only useful if you fit the optional unplug point. <b>Match the width</b>: a 10 mm connector, or one for SMD strip, will not grip.</dd>
  <dt>If you would rather solder</dt><dd>Soldering wire straight to the strip's pads is the only other way to make this joint, and it needs no connector. It is at the end of this page. You do not have to: the clamp-on connector is the route this page is built around, and it needs no iron.</dd>
  <dt>If you own a crimp tool</dt><dd>You can make the lead yourself instead of buying it: about a metre of 22 AWG stranded per drop, one red and one black, plus a 2-pin 2.54 mm Dupont female housing and two crimps. Gauge is a <b>GUESS</b> in the harness notes.</dd>
  <dt>Barrel pair, if you want the unplug point</dt><dd>5.5 × 2.1 mm, one male and one female, <b>tip positive</b>. Buy only the mating half if your strip connector already brings one. The same size as the PSU outputs, so check you are not about to plug a lamp into a PSU jack. Not in the catalog, because a v1.3 board does not need it.</dd>
  <dt>Insulation</dt><dd>Heatshrink, or lever connectors (Wago 221) or solder-seal butt splices, only if you end up splicing something.</dd>
</dl>

<div class="callout">
  <span class="callout-icon" aria-hidden="true">›</span>
  <p><b>No current-limiting resistor on this drop.</b> The strip has its own, and board v1.3 already carries one in series with the +24V feed to each LED header. That is only true of the strip: a 50 mm COB plate needs its own resistor, see the <a href="{{ '/hardware/electronics/' | relative_url }}">wire harness</a> page.</p>
</div>

## Build it

1. **Cut the strip on a mark.** 950 mm for a lamp, cut where the strip is printed as cuttable, which leaves half of each copper pad on your piece. The full measurement is on the [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}) page, step 5.
2. **Clamp the connector onto the pads.** Lift the lid, slide the cut end in until the two pads sit under the sprung contacts, press it shut. The pad printed <code>+24V</code> takes the red side. Nothing to strip, nothing to solder. Soldering to the pads instead is below.
3. **Clamp the wire into the other end**, red to the <code>+24V</code> side, if you are using the strip-to-wire connector. It bites through the insulation, so the wire does not need stripping either.
4. **Run the pair out of the reflector and down the arm**, and cable-tie it along the arm so it is not hanging in the channel.
5. **At the board end, push the 2-pin Dupont housing onto an LED header.** Red to +24V, and check which pin that is with a meter first. If you are using the pre-crimped lead, cut its male plug off and the female end is already the plug you need; otherwise crimp a housing on yourself.
6. **Only if you want an unplug point**, cut the run where the arm meets the channel and put the barrel pair in, red to the tip. The lamp then comes off the machine there without unwiring anything.
7. **Set the output in software.** Settings, then the channel, then the LED button: pick which of the board's LED outputs this lamp is on, and set the brightness with the slider. Nothing lights until an output is assigned.

Repeat for all three lamps.

### Soldering to the pads instead

Perfectly good, and it is what the strip is designed for. Clear any coating off the two pads, melt a little solder onto each until it wets the copper, tin 3 mm of bared wire the same way, then hold the wire on the pad and touch the iron to both for a second or two. Red to <code>+24V</code>, black to <code>-</code>. Insulate each joint so the two cannot touch. Keep the iron on the pad briefly: the strip's backing and the LED next to the pad do not like being cooked.

## Reference

The drop's two segments are <code>L1</code>/<code>L1p</code> to <code>L3</code>/<code>L3p</code> in the wire schedule on the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page, and the drawings are on [WireViz drawings]({{ '/hardware/electronics/wireviz/' | relative_url }}). Both still split every drop at a barrel jack, because <code>leds.yml</code> has not been redrawn since the straight run became the recommendation.
