---
layout: default
title: Preparing the LED strip
type: how-to
section: hardware
slug: helper-led-strip
kicker: Helpers — LED strip
lede: Cutting a length of 24 V strip and making the cable that takes it to the control board, with an optional but recommended barrel plug and socket where the lamp comes off. Three of each per machine.
permalink: /hardware/helpers/led-strip/
author: brickcyclealice
contributors: [effreek, reveryx, spencer, barthel]
og_image: https://assets.basically.website/sorter-parts/led-strip-connector-8mm-full-915e0ed03fdc.jpg
last_verified: 2026-09-25
parts_needed:
  - part: led-strip-24v
    qty: 1
  - part: led-strip-connector-8mm
    qty: 3
  - part: dc-plug-5521-male-led
    qty: 3
  - part: dc-jack-5521-inline
    qty: 3
  - part: butt-connector-red-22-16
    qty: 8
  - part: dupont-lead-2p-1m
    qty: 3
  - part: sleeving-braided-6mm
    qty: 1
    note: Optional. About 1 m over each of the three board cables and 0.1 m over each of the three lamp pigtails.
tools_needed: [Side cutters, Wire strippers, "Multimeter (only if you fit the plug and socket)", "Insulated-terminal crimping pliers with a die for 22 to 16 AWG (0.33 to 1.3 mm²) wire, for the butt connectors", "Only if you solder instead of crimping or clamping: a soldering iron, solder and 3 mm adhesive-lined heat shrink (see Getting started)", "Only if you make your own Dupont cable: a crimp tool for open-barrel contacts", "Optional, for the sleeving: scissors and tape, or a hot knife"]
---

Each camera lamp needs a cable that takes 24 V from the control board to its strip. The best way to build it is **two cables that meet at a barrel plug and socket**. The plug and socket are **optional but recommended**. **They make maintenance easier:** the power supply to a lamp can be disconnected right next to the lamp, so you can take a lamp down, swap it or work on it without touching the board end of its cable or the cables of the other lamps. **A machine takes three of each.** The quantities above are a whole machine's worth: one 5 m roll cuts into five lengths, and the Dupont cables come five to a pack.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/led-two-cable-set-pin1-full-ad3551b6b708.png" alt="Diagram of two cables. Cable 1, the lamp pigtail: an LED strip, a clamp-on connector, and red and black wires ending in a barrel plug. Cable 2, the board cable: a barrel socket, two staggered butt connectors on its red and black wires, and a longer cable ending in a two-pin Dupont plug that goes to the board, red in pin 1 for +V and black in the other for GND.">
  <figcaption>The two cables: the lamp pigtail stays with the lamp, the board cable stays with the machine.</figcaption>
</figure>

**Pick your build:**

<ul class="bulleted-list">
  <li><b>Plug and socket:</b> fit them (recommended), or leave them out. Leaving them out makes one cable: skip steps 3 and 5, and the Dupont cable's cut end goes onto the strip in step 4.</li>
  <li><b>Strip end:</b> clamp it with a connector (step 4).</li>
  <li><b>Socket joints:</b> crimp them with butt connectors (step 5).</li>
</ul>

Nothing here needs soldering. If you would rather solder a joint, the connector cards in the parts list name it as the alternative.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Check the roll you bought is the <b>24 V</b> one. The board's LED headers feed 24 V.</p>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>The socket goes on the board cable and the plug goes on the lamp pigtail, never the other way round.</b> The board end is live at 24 V whenever the power supply is on, and a socket has its contacts recessed where a plug's are not. Both are <b>5.5 x 2.1 mm, centre-positive</b>: the tip is +24 V and the sleeve is ground.</p>
</div>

{% include step.html n="1" title="Cut the strip to length, on a mark" %}

**Two turns of the [camera lamp]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }})'s reflector skirt**, which is about 920 mm of strip. One 5 m roll gives five lamps' worth.

**Take off any wire the roll came with.** Some rolls have a wire soldered to the end, and it may finish in a female connector. Cut the strip just past its solder joints, on a mark, so the wire and its connector go and the strip starts with bare pads. Measure from there.

**Cut only on the printed marks**, never between them: the solder pads are at the marks, so a cut anywhere else leaves nothing to connect to. **The marks are not the same pitch on every roll**, so count marks rather than millimetres: coil the strip dry inside the skirt and cut at the last mark before the free end reaches the start of the coil. That lands somewhere near 920 mm.

**Take the mark under two turns rather than the one over it.** Strip past two turns has nowhere to sit: it lifts out from under the cover and the light leaves the lamp at an odd angle. A small gap where the ends do not quite meet does not show.

Leave the blue protective film on until the strip is going where it lives. It is the only thing keeping grease off the adhesive.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/led-strip-cut-marks-plain-full-3351d6e9340e.png" alt="Diagram of a COB LED strip seen from above with a scissors symbol over each of two cut points, and the copper pads at each cut point labelled +24V on the top row and minus on the bottom">
  <figcaption>The cut points, with the pads that sit either side of them. Each cut leaves you half of a pad, printed <code>+24V</code> on one side. <cite>Manufacturer diagram (VOEWT).</cite></figcaption>
</figure>

{% include step.html n="2" title="Cut the male plug off the Dupont cable" %}

The cable comes from the pack with a plug on both ends: the **male** one has two pins sticking out of it, the **female** one has two holes. **Cut the male plug off.** The female end stays on: that is what pushes onto the board later. With the plug and socket, the socket joins here in step 5. Without them, this cut end goes straight onto the strip in step 4, and you skip steps 3 and 5.

If you own a crimp tool for open-barrel contacts, you can make this cable instead: about a metre of 22 AWG (0.33 mm²), one red and one black, with a 2-pin 2.54 mm Dupont female housing crimped on (how is at [Crimping connectors]({{ '/hardware/helpers/crimping/' | relative_url }})). Put the red wire's contact in the cavity next to the moulded arrow, so the arrow marks red on the cables you make.

**The housing does not tell you which way round it goes.** It has no key, so it pushes onto the board's two pins either way up, and only the wire colour decides the polarity: **the red wire goes over the pin the board prints `+V`**, which is the one on the square pad. **The small arrow moulded into the housing is not a polarity mark.** It sits beside one contact, but on the ready-made cables in the listing photo it is beside the black wire's contact, so do not use it to find red.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/led-dupont-orientation-full-d7b88c61fe57.png" alt="Two views of the Dupont housing from above on an LED port. Left, right: the red wire's cavity is over the pin on the square pad printed +V and the black wire's is over the round GND pin, with the moulded arrow beside the black one. Right, wrong: the housing turned half a turn, so red is over GND and the arrow has moved to the other side.">
  <figcaption>The same housing both ways round. The arrow turns with it, so it cannot tell you which is right.</figcaption>
</figure>

**Optional:** if you will sleeve the board cable, slide a 1 m length of braided sleeving over its two wires from the cut end now, before you join the socket in step 5 or clamp the wires onto the strip in step 4. A finished socket or clamp may not go through it, so it goes on first. If you make your own cable, slide it on before you crimp the housing. [Sleeving (optional)](#sleeving-optional) says how to cut and finish it.

{% include step.html n="3" title="Find the tip of the plug and of the socket" %}

Only if you are fitting the plug and socket. Set the <a href="{{ '/hardware/helpers/multimeter/' | relative_url }}#continuity-for-tracing-a-cable">multimeter to continuity</a> and hold one probe on the centre pin. The wire that beeps is the tip, which is **+24 V**. The other is ground. Do this for the plug and for the socket, and **do not go by wire colour**, because moulded plugs are not consistent about it.

Then cut the plug's wires to about 150 mm (6 in).

**Optional:** if you will sleeve the lamp pigtail, slide a 0.1 m length of braided sleeving over its two wires from the cut end now, before you clamp them onto the strip in step 4.

{% include step.html n="4" title="Clamp the wires onto the strip" %}

The solderless connector is a hinged body with sprung contacts at each end: the strip goes in one end, the wire in the other, and nothing is stripped or tinned.

<ol class="numbered-steps">
  <li>Lift the lid at the strip end, slide the cut end in until the two copper pads sit under the contacts, and press it shut.</li>
  <li>Clamp the plug's two wires into the other end (or, without the plug, the Dupont cable's two wires). The tip wire (or the red wire) goes on the <code>+24V</code> side. It bites through the insulation, so the wires do not need stripping either. The connector is made for 22 AWG (0.33 mm²) wire, so check your plug's leads are about that size, and tug each wire once the lid is shut.</li>
</ol>

**Match the width.** These are 8 mm COB connectors and nothing else will grip: a 10 mm body, or one meant for SMD strip, will not hold the pads against the contacts. Buy <code>SBL-RA2P-8</code>: the <code>-DC</code> variant ends in a barrel socket, which is the wrong way round on the lamp pigtail.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/led-strip-clamp-sequence-black-full-3e4b2ec3e816.png" alt="Two stages of clamping: above, the cut end of a COB strip lined up with the open connector, an arrow showing it going in, with red and black wire already in the far end; below, the connector pressed shut on the strip with the pair leaving it">
  <figcaption>The strip into the open connector, then the connector pressed shut on it. <cite>Manufacturer photos (LED strip connector product listing; seller not recorded).</cite></figcaption>
</figure>

{% include step.html n="5" title="Crimp the socket's wires to the cable" %}

Only if you are fitting the plug and socket. The socket's wires and the Dupont cable's wires are joined end to end, one joint per wire, so there are two. **The socket's tip wire joins the cable's red wire**, and the socket's ground wire joins the black one. Red is the wire that goes to <code>+V</code> on the board, so this is the joint that keeps the polarity right. Do one joint at a time so the two never touch.

A butt connector is a vinyl-insulated barrel that takes one wire in each end, rated for 22 to 16 AWG (0.33 to 1.3 mm²) wire. Nothing is soldered. Three lamps need six; the list has eight, two for a crimp that goes wrong. More on crimping is at [Crimping connectors]({{ '/hardware/helpers/crimping/' | relative_url }}).

<ol class="numbered-steps">
  <li>Strip 7 mm off both wires of each joint, and twist the strands of each wire tight.</li>
  <li>Push the socket's wire into one end of a red butt connector, and the cable's wire of the same colour into the other, until the insulation of each wire meets the end of the barrel.</li>
  <li>Close each end of the barrel in the die of the insulated-terminal crimping pliers marked for 22 to 16 AWG (0.33 to 1.3 mm²), so each wire is crimped separately. Squeeze until the tool releases. Pull on each wire to check it holds.</li>
  <li>Stagger the two butt connectors by a few millimetres along the cable so they cannot touch.</li>
</ol>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/butt-crimp-steps-full-3537584b7c38.png" alt="Three stages: a wire with 7 mm of bare strands; a wire pushed into each end of a red butt connector; the connector held between the jaws of a crimping tool, the jaw marked 22 to 16.">
  <figcaption>Strip, push in, crimp each end in the marked die.</figcaption>
</figure>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Use insulated-terminal crimping pliers.</b> A crimp tool for open-barrel contacts, the kind that does Dupont and PH, has the wrong die and will not close a butt connector properly.</p>
</div>

{% include step.html n="6" title="Check it before it goes anywhere" %}

Set the multimeter to continuity. **With the plug and socket**, push the two cables together first.

<ol class="numbered-steps">
  <li>Touch one probe to the strip's <code>+24V</code> pad and the other to the hole in the Dupont housing that the red wire runs to. It should beep. That is the contact that goes over <code>+V</code> on the board.</li>
  <li>Move the second probe to the other hole in the housing. It should not beep.</li>
  <li>Put one probe in each of the two holes. It should not beep.</li>
</ol>

If the first test does not beep, or the second does, the two joints have crossed. If the third beeps, something is shorting.

## Sleeving (optional)

<div class="callout">
  <p><b>You can skip this and the lamp works the same.</b> The sleeving is on the parts list as optional. It keeps the two wires together as one tidy cable and protects them where the cable runs along the frame, and it is another way of securing the cables.</p>
</div>

**Where:** over the two wires of each board cable, from just short of the barrel socket (or of its butt connectors) to just short of the Dupont housing, about 1 m. The short lamp pigtail can have a 0.1 m length as well, from just short of the clamp to just short of the plug. Three of each per machine.

**How:**

<ol class="numbered-steps">
  <li>Push the braid together lengthwise to open it: it widens as it shortens. Feed both wires into it together, so neither is left outside.</li>
  <li>Cut it to length with a hot knife or a soldering iron with a blade tip, so the cut melts shut. Plain scissors leave the braid fraying. With no hot tool, wrap a turn of tape around the braid where you will cut, cut through the middle of the tape with scissors, and leave the tape on.</li>
  <li>Stop the sleeving 5 to 10 mm short of the socket, the plug, the clamp and the Dupont housing, so the sleeving never crowds into them and the joints can flex.</li>
  <li>Hold each end with a small piece of heat shrink or a turn of tape, so that the braid cannot creep back along the wires.</li>
</ol>

## The finished result

With the pair fitted, two cables that plug together. A two-turn length of strip, about 920 mm, with its male barrel plug on the end of a short pair of wires, and a metre of red and black wire with a female barrel socket at one end and a 2-pin Dupont plug at the other. Three of each make a machine. Without the pair it is one cable, the Dupont cable running straight to the strip. Nothing is joined end to end along the strip, so its far end stays dead.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-parts/led-strip-connector-8mm-full-915e0ed03fdc.jpg" alt="A length of 8 mm COB LED strip with a clear clamp-on connector on its cut end, a red and a black wire leaving the other side of the connector in a white sheath">
  <figcaption>The strip end of the pigtail: the cut end, the joint, and the wires that leave it. <cite>Manufacturer photo (SuperBrightLEDs).</cite></figcaption>
</figure>

The Dupont end goes onto an LED port at [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), step 4.
