---
layout: default
title: Preparing the LED strip
type: how-to
section: hardware
slug: helper-led-strip
kicker: Helpers — LED strip
lede: Cutting a camera lamp's 950 mm ring of LED strip and getting two wires onto the cut end, with a clamp-on connector or with solder. Three per machine.
permalink: /hardware/helpers/led-strip/
author: brickcyclealice
contributors: [reveryx, spencer, effreek, barthel]
warning: >-
  **Neither way of making the joint is photographed on a build yet.** The length, where to cut and
  how the strip sits in the lamp all come from real builds. The strip in the photographs came off
  the end of the roll with its leads already fitted, so nobody has yet photographed a clamp-on
  connector or a soldered joint on one of these. Fill the gaps in as you build.
parts_needed:
  - part: led-strip-24v
    qty: 1
  - part: led-strip-connector-8mm
    qty: 1
  - part: dupont-lead-2p-1m
    qty: 1
tools_needed: [Side cutters, Multimeter, "Only if you solder: iron, solder and heatshrink"]
---

Every [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}) is lit by one ring of 24 V COB strip inside its reflector. A prepared strip is a 950 mm length with two wires on the cut end, ready to hook onto the reflector: that is this page, and it is the same job whichever lamp it ends up in.

**A machine needs three.** One 5 m roll cuts into five lengths, so a roll covers all three lamps, and the quantities above are one strip's worth of everything else.

<div class="callout">
  <p><b>You do not need a soldering iron.</b> A clamp-on connector bites the cut end of the strip at one end and your wire at the other, so the whole joint is two bought parts pressed together. Soldering to the pads is the alternative and is equally good, not a fallback.</p>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Check the roll you bought is the <b>24 V</b> one. The listing in the catalog also sells a 12 V strip of the same width, and the basically board's LED headers feed 24 V.</p>
</div>

Where a prepared strip goes next: [lamp arm]({{ '/hardware/assembly/feeder/camera-lamp/lamp-arm/' | relative_url }}) step 4 hooks it onto the reflector, and [Make your own LED drop]({{ '/hardware/electronics/led-drop/' | relative_url }}) takes the two wires back to an LED header on the board.

{% include step.html n="1" title="Cut 950 mm, on a mark" %}

**Cut 950 mm of strip for each lamp**, which is two turns around the inside of the reflector's skirt.

**Cut only on the printed marks**, never between them: the solder pads are at the marks, so a cut anywhere else leaves nothing to connect to. Take the nearest mark to 950 mm rather than the exact measurement.

Leave the blue protective film on until the strip goes into the reflector. It is the only thing keeping grease off the adhesive.

{% include step.html n="2" title="Either: clamp a connector onto the pads" %}

The solderless connector is a hinged body with sprung contacts at each end: the strip goes in one end, the wire in the other, and nothing is stripped or tinned.

<ol class="numbered-steps">
  <li>Lift the lid at the strip end, slide the cut end in until the two copper pads sit under the contacts, and press it shut. The pad printed <code>+24V</code> takes the red side.</li>
  <li>Clamp the wire into the other end, red to the <code>+24V</code> side. It bites through the insulation, so the wire does not need stripping either.</li>
</ol>

**Match the width.** These are 8 mm COB connectors and nothing else will grip: a 10 mm body, or one meant for SMD strip, will not hold the pads against the contacts.

The wire is the drop's own pair, a metre of 22 AWG red and black. Which lead that is, and the choice between the three variants of the connector body, are on the [LED drop]({{ '/hardware/electronics/led-drop/' | relative_url }}) page.

{% include step.html n="3" title="Or: solder the wires to the pads" %}

Perfectly good, and what the strip is designed for. It needs no connector at all.

<ol class="numbered-steps">
  <li>Clear any coating off the two pads and melt a little solder onto each until it wets the copper.</li>
  <li>Tin 3 mm of bared wire the same way.</li>
  <li>Hold the wire on the pad and touch the iron to both for a second or two. Red to <code>+24V</code>, black to <code>-</code>.</li>
  <li>Insulate each joint, with heatshrink over the wire or a piece over the whole end, so the two cannot touch.</li>
</ol>

Keep the iron on the pad briefly. The strip's backing and the LED next to the pad do not like being cooked.

{% include step.html n="4" title="The first length off the roll is already done" %}

A roll arrives with bare leads soldered to one end at the factory. Cut your first 950 mm so that end is on your piece and it needs neither a connector nor an iron: trim the leads to length when the drop is made up. The other two lamps take plain cut lengths from the middle of the roll, and those are the ones that need step 2 or step 3.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-strip-second-turn-w1600-e7a417c98b26.jpg" alt="Both turns of strip in the reflector skirt, one above the other, film gone, with the red and black leads leaving the reflector at one side">
  <figcaption>The roll's own lead end, on the strip that went into this lamp. <cite>Photo: BrickCycleAlice.</cite></figcaption>
</figure>

## What you end up with

A 950 mm length with a red and a black wire on one end and a dead end at the other, three of them for a machine. Nothing is joined end to end in a lamp, so the far end stays dead. Take each one to [lamp arm]({{ '/hardware/assembly/feeder/camera-lamp/lamp-arm/' | relative_url }}) step 4.

You can also do it the other way round and hook the strip in first, then make the joint with the strip already in the reflector. The joint is easier on the bench, which is why it is written this way.
