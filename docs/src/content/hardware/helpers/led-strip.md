---
layout: default
title: Preparing the LED strip
type: how-to
section: hardware
slug: helper-led-strip
kicker: Helpers — LED strip
lede: Cutting a length of 24 V strip and making the two cables that take it to the control board, joined by a barrel plug and socket. Three of each per machine.
permalink: /hardware/helpers/led-strip/
author: brickcyclealice
contributors: [effreek, reveryx, spencer, barthel]
og_image: https://assets.basically.website/sorter-parts/led-strip-connector-8mm-full-915e0ed03fdc.jpg
last_verified: 2026-09-30
parts_needed:
  - part: led-strip-24v
    qty: 1
  - part: led-strip-connector-8mm
    qty: 3
  - part: dc-plug-5521-male
    qty: 3
  - part: dc-jack-5521-inline
    qty: 3
  - part: dupont-lead-2p-1m
    qty: 3
tools_needed: [Side cutters, Wire strippers, "Soldering iron, solder and heatshrink", Multimeter, "Only if you make your own lead: crimp tool"]
---

A camera lamp's power is **two cables that meet at a barrel plug and socket**, so a lamp can come off without unwiring the board end. **This layout makes maintenance easier:** the power supply to a lamp can be disconnected right next to the lamp, so you can take a lamp down, swap it or work on it without touching the board end of its cable or the cables of the other lamps. **A machine takes three of each.** The quantities above are a whole machine's worth: one 5 m roll cuts into five lengths, and the Dupont leads come five to a pack.

<dl class="spec-list">
  <dt>Lamp pigtail</dt><dd>The strip, a clamp-on connector (or solder) and a male barrel plug on the plug's own short leads, about 150 mm (6 in). It stays with the lamp.</dd>
  <dt>Board cable</dt><dd>The Dupont lead, about a metre of 22 AWG red and black, with the Dupont plug that goes onto the board at one end and a female barrel socket at the other. It stays with the machine.</dd>
  <dt>Where they meet</dt><dd>The plug pushes into the socket. The Dupont end goes onto an LED port when the machine is wired up: step 4 of <a href="{{ '/hardware/electronics/connecting/' | relative_url }}">connecting the components</a>.</dd>
</dl>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Check the roll you bought is the <b>24 V</b> one. The listing in the catalog also sells a 12 V strip of the same width, and the board's LED headers feed 24 V.</p>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The socket goes on the board cable and the plug goes on the lamp, never the other way round.</b> The board side is live at 24 V whenever the power supply is on, and a socket has its contacts recessed where a plug's are not. Both are <b>5.5 x 2.1 mm, centre-positive</b>: the tip is +24 V and the sleeve is ground.</p>
</div>

{% include step.html n="1" title="Cut the strip to length, on a mark" %}

**Two turns of the [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }})'s reflector skirt**, which is about 920 mm of strip. One 5 m roll gives five lamps' worth.

**Take off any lead the roll came with.** Some rolls have a lead soldered to the end, and it may finish in a female connector. Cut the strip just past its solder joints, on a mark, so the lead and its connector go and the strip starts with bare pads. Measure from there.

**Cut only on the printed marks**, never between them: the solder pads are at the marks, so a cut anywhere else leaves nothing to connect to. **The marks are not the same pitch on every roll**, and 31 mm, 38 mm and 50 mm have all turned up on rolls people have bought, so work in marks rather than in millimetres: coil the strip dry inside the skirt and cut at the last mark before the free end reaches the start of the coil. That lands somewhere near 920 mm.

**Take the mark under two turns rather than the one over it.** Strip past two turns has nowhere to sit: it lifts out from under the cover and the light leaves the lamp at an odd angle. A small gap where the ends do not quite meet does not show.

Leave the blue protective film on until the strip is going where it lives. It is the only thing keeping grease off the adhesive.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/led-strip-cut-marks-plain-full-3351d6e9340e.png" alt="Diagram of a COB LED strip seen from above with a scissors symbol over each of two cut points, and the copper pads at each cut point labelled +24V on the top row and minus on the bottom">
  <figcaption>The cut points, with the pads that sit either side of them. Each cut leaves you half of a pad, printed <code>+24V</code> on one side. <cite>Manufacturer diagram (VOEWT).</cite></figcaption>
</figure>

## The lamp pigtail

It is the strip with the male barrel plug on it. The plug comes on a short lead of its own, and that lead is what goes onto the strip, by clamping or by soldering.

**Find the tip first.** Set the <a href="{{ '/hardware/helpers/multimeter/' | relative_url }}#continuity-for-tracing-a-cable">multimeter to continuity</a> and hold one probe on the plug's centre pin: the lead that beeps goes to the strip's <code>+24V</code> pad. Do not go by lead colour, because moulded plugs are not consistent about it. Then cut the plug's leads to about 150 mm (6 in).

{% include step.html n="2a" title="Either: clamp the plug's leads onto the pads" %}

The solderless connector is a hinged body with sprung contacts at each end: the strip goes in one end, the wire in the other, and nothing is stripped or tinned.

<ol class="numbered-steps">
  <li>Lift the lid at the strip end, slide the cut end in until the two copper pads sit under the contacts, and press it shut. The pad printed <code>+24V</code> takes the lead you found to be the tip.</li>
  <li>Clamp the plug's two leads into the other end, the tip lead on the <code>+24V</code> side. It bites through the insulation, so the leads do not need stripping either.</li>
</ol>

**Match the width.** These are 8 mm COB connectors and nothing else will grip: a 10 mm body, or one meant for SMD strip, will not hold the pads against the contacts.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/led-strip-clamp-sequence-black-full-3e4b2ec3e816.png" alt="Two stages of clamping: above, the cut end of a COB strip lined up with the open connector, an arrow showing it going in, with red and black wire already in the far end; below, the connector pressed shut on the strip with the pair leaving it">
  <figcaption>The strip into the open connector, then the connector pressed shut on it. <cite>Manufacturer photos (LED strip connector product listing; seller not recorded).</cite></figcaption>
</figure>

{% include step.html n="2b" title="Or: solder the plug's leads to the pads" %}

Perfectly good, and what the strip is designed for. It needs no connector at all.

<ol class="numbered-steps">
  <li>Clear any coating off the two pads and melt a little solder onto each until it wets the copper.</li>
  <li>Strip 3 mm off each of the plug's leads and tin them the same way.</li>
  <li>Hold the lead on the pad and touch the iron to both for a second or two. The tip lead goes to <code>+24V</code>, the other to <code>-</code>.</li>
  <li>Insulate each joint, with heatshrink over the wire or a piece over the whole end, so the two cannot touch.</li>
</ol>

Keep the iron on the pad briefly. The strip's backing and the LED next to the pad do not like being cooked.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/led-strip-soldered-joint-clean-full-bdad7637dc9c.png" alt="The cut end of a COB LED strip with a red and a black wire soldered to its two pads, a piece of clear heatshrink over the joint, and the pair running away from the strip">
  <figcaption>A soldered end, insulated with clear heatshrink over the joint. <cite>Manufacturer photo (LED strip product listing; seller not recorded).</cite></figcaption>
</figure>

## The board cable

It is the Dupont lead with the female barrel socket on its far end. The lead comes from the pack with a plug on both ends, and the socket's own short leads are joined to it.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Cut the male plug off the lead first.</b> The bought lead has a plug on both ends: the <b>male</b> one has two pins sticking out of it, the <b>female</b> one has two holes. <b>Cut the male plug off</b> and join the socket there. The female end stays on: that is what pushes onto the board later.</p>
</div>

{% include step.html n="3" title="Join the socket's leads to the lead" %}

The socket's leads and the lead's wires are joined end to end, one joint per conductor, and there are two of them. Do one at a time so the two never touch.

<ol class="numbered-steps">
  <li><b>Find the tip of the socket.</b> Set the multimeter to continuity as above and hold one probe on the socket's centre pin: the lead that beeps is <b>+24 V</b>. The other is ground.</li>
  <li><b>Match the pairs.</b> The socket's <b>tip lead joins the lead's red wire</b>, and the socket's ground lead joins the black one. Red is the wire that goes to <code>+V</code> on the board, so this is the joint that keeps the polarity right.</li>
  <li>Slide a piece of heatshrink over each wire before anything is joined, about 25 mm long, and push it well back out of the heat. Stagger the two joints by a few millimetres so they cannot touch.</li>
  <li>Strip 5 mm off both ends of each pair, twist the strands of the two ends together so they lie side by side, and solder the joint until the solder has run into the strands.</li>
  <li>Slide the heatshrink over the joint and shrink it. Do the other conductor the same way.</li>
</ol>

**Check it before it goes anywhere.** Push the two cables together and set the multimeter to continuity. From the strip's `+24V` pad to the Dupont pin that goes to `+V` on the board should beep, and from `+24V` to the other pin should not. If it beeps the wrong way round, the two joints have crossed. If the two pins beep to each other, something is shorting.

## Choosing the parts

<dl class="spec-list">
  <dt>Which clamp-on connector</dt><dd><code>SBL-RA2P-8</code> is the one in the list above, and it is the one that takes your own wire. <code>SBL-RA2P-8-1</code> arrives with 4 in of tinned lead on it, so it gets spliced rather than clamped. <code>SBL-RA2P-8-DC</code> ends in a barrel <b>socket</b>, which is the wrong way round for the lamp pigtail. All are <b>8 mm COB only</b>.</dd>
  <dt>The barrel plug and socket</dt><dd>Buy each as a moulded part already on its own short leads, and splice or clamp to those. A screw-terminal plug works but is bulkier and comes loose. Both must be <b>5.5 x 2.1 mm</b>: a 2.5 mm plug looks the same and does not mate.</dd>
  <dt>If you own a crimp tool</dt><dd>You can make the board cable's lead instead of buying it: about a metre of 22 AWG stranded per run, one red and one black, plus a 2-pin 2.54 mm Dupont female housing and two crimps.</dd>
  <dt>Heatshrink</dt><dd>For the joints, in steps 2b and 3. Nothing else on this page needs insulating.</dd>
</dl>

## The finished result

Two cables that plug together. A two-turn length of strip, about 920 mm, with its male barrel plug on the end of a short lead, and a metre of red and black wire with a female barrel socket at one end and a 2-pin Dupont plug at the other. Three of each make a machine. Nothing is joined end to end along the strip, so its far end stays dead.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/led-strip-connector-8mm-full-915e0ed03fdc.jpg" alt="A length of 8 mm COB LED strip with a clear clamp-on connector on its cut end, a red and a black wire leaving the other side of the connector in a white sheath">
  <figcaption>The strip end of the pigtail: the cut end, the joint, and the lead that leaves it. <cite>Manufacturer photo (SuperBrightLEDs).</cite></figcaption>
</figure>

The Dupont end goes onto an LED port at [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 4.
