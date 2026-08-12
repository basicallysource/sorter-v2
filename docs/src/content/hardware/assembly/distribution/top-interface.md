---
layout: default
title: Top interface
type: how-to
section: hardware
slug: assembly-top-interface
kicker: Distribution — Top interface
lede: The interface between the feeder and the bin tower.
permalink: /hardware/assembly/distribution/top-interface/
author: zed0
parts_needed:
  - part: interface-upper-fixed-section
    qty: 1
  - part: interface-rib
    qty: 5
  - part: interface-rib-switch
    qty: 1
  - part: interface-bracket
    qty: 6
  - part: interface-spacer
    qty: 6
  - part: interface-nema23-bracket
    qty: 1
  - part: interface-big-spacer
    qty: 1
  - part: limit-switch-housing
    qty: 1
  - part: limit-switch-dowel-pin
    qty: 1
  - part: limit-switch-hammer
    qty: 1
  - part: top-interface-split-spur-gear-3
    qty: 1
  - part: top-interface-split-spur-gear-1
    qty: 1
  - part: top-interface-split-spur-gear-2
    qty: 1
  - part: interface-spur-gear
    qty: 1
  - part: interface-idler-gear
    qty: 1
  - part: interface-cage-bracket
    qty: 5
  - part: interface-cage-bracket-cable
    qty: 1
  - part: top-plate
    qty: 1
  - part: cable-cage-top
    qty: 1
  - part: cable-cage-bottom
    qty: 1
  - part: cable-clamp-outer
    qty: 1
  - part: cable-clamp-inner
    qty: 1
  - part: ribbon-cable-clamp
    qty: 1
  - part: ext-bracket-left
    qty: 6
  - part: ext-bracket-cover
    qty: 6
  - part: extrusion-e
    qty: 6
  - part: extrusion-f
    qty: 6
  - part: lazy-susan
    qty: 1
  - part: brg-608-2rs
    qty: 1
  - part: motor-nema23
    qty: 1
  - part: pulley-20t-8mm
    qty: 1
  - part: endstop-mechanical
    qty: 1
  - part: cable-idc-2x8-long
    qty: 1
  - part: scr-m5-35-shcs
    qty: 6
  - part: scr-m5-25-shcs
    qty: 6
  - part: scr-m5-22-cs
    qty: 15
  - part: scr-m5-20-bhcs
    qty: 24
  - part: scr-m5-16-bhcs
    qty: 36
  - part: scr-m5-16-shcs
    qty: 2
  - part: scr-m5-12-shcs
    qty: 4
  - part: scr-m3-35-bhcs
    qty: 1
  - part: scr-m3-10-shcs
    qty: 2
  - part: tnut-m5-2020
    qty: 56
  - part: nut-m5
    qty: 6
  - part: nut-m3
    qty: 1
---

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>The fasteners and quantities in the parts list come from the build notes and are called out inline at each step. A few smaller screws are not recorded yet; those are marked <span class="fastener-todo">fastener not recorded</span> in the steps below. If you know one, please add its size.</p>
</div>

Several steps below refer to holes in the Top plate by name (S2 and S3 for the stepper mount, I1 to I6 and O1 to O6 for the interface brackets). This map shows which hole is which:

<figure>
  <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/top-plate-hole-map.756f0dae2288fdb2.jpg" alt="Hole map of the hexagonal top plate: three stepper holes S1 to S3 in a row left of the center opening, six inner-ring holes I1 to I6, six outer-ring holes O1 to O6, and five cable holes C1 to C5, colour-coded by group">
  <figcaption>Top plate hole map. S = stepper trio, I = inner ring, O = outer ring, C = cable holes.</figcaption>
</figure>


{% include step.html n="1" title="Attach the interface ribs to the upper fixed section" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/O_ApnzrWRsE?mute=1"
    title="Attaching the interface ribs to the interface upper fixed section"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Attach the Interface rib (switch gap) to the Interface upper fixed section, two positions counterclockwise of the notch for the stepper mount. Use two M5 × 16 mm button head screws, tapping directly into the plastic.

Attach the remaining 5 Interface ribs to the Interface upper fixed section, two M5 × 16 mm button head screws each, again tapping into the plastic.

Slot the Interface NEMA 23 bracket into the Interface upper fixed section and secure it with a screw from below <span class="fastener-todo">fastener not recorded</span>.

Attach the whole assembly to the bottom of the Top plate with M5 × 22 mm countersunk screws through holes S2 and S3 into the Interface NEMA 23 bracket.

{% include step.html n="2" title="Prepare the interface brackets" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/-mtU3WXP73M?mute=1"
    title="Preparing the interface brackets"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Align an Interface bracket with piece E (Interface spoke, long) of aluminum extrusion.

Place T-nuts in the extrusion, lined up with the 4 holes on the side of the Interface bracket.

Slide the extrusion into the Interface bracket, careful not to dislodge the T-nuts, and drive four M5 × 16 mm button head screws into them.

Repeat for all 6 Interface brackets.

{% include step.html n="3" title="Prepare the limit switch interface bracket" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/YzYzytRl3p4?mute=1"
    title="Preparing the limit switch interface bracket"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Push the Printed dowel pin into the Limit switch housing.

Attach a Roller lever limit switch with 2 screws <span class="fastener-todo">fastener not recorded</span> so the roller sits next to the dowel pin.

Align the switch housing with the extrusion of one of the prepared Interface brackets so the limit switch is on the same face as the sloped side of the bracket. Slide 2 T-nuts into the extrusion and fasten the Limit switch housing to the extrusion with two M5 × 16 mm socket head screws. Slide it as far toward the Interface bracket as possible for now; it gets aligned properly later.

{% include step.html n="4" title="Install the brackets" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/K7r15si5yxI?mute=1"
    title="Installing the interface brackets"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Slide a T-nut just into the end of the extrusion of the limit switch interface bracket. Slide the extrusion into the Interface rib (switch gap) and Interface upper fixed section, securing it loosely with a screw <span class="fastener-todo">fastener not recorded</span>. Slide the extrusion slightly in and out to align the holes on the Interface bracket with the holes on the Top plate, then tighten the screw.

Repeat with the 5 other prepared Interface brackets into the 5 other Interface ribs.

Flip the whole assembly and screw all 6 Interface brackets into place with M5 × 22 mm countersunk screws through holes I1 to I6 and O1 to O6.

{% include step.html n="5" title="Prepare the interface chute gear and mount" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/7oYiOXYF8rA?mute=1"
    title="Preparing the interface chute gear and mount"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Slot the Limit switch hammer into the Top interface chute mount, then screw it in place from below <span class="fastener-todo">fastener not recorded</span>.

Align the Chute gear on the Top interface chute mount with the notch by the screw for the Limit switch hammer. Attach it with 5 screws <span class="fastener-todo">fastener not recorded</span>.

Align the Top interface lazy Susan washer with the 4 inner heat inserts on the Top interface chute mount. Align the inner ring of the [Lazy Susan]({{ '/hardware/parts/lazy-susan/' | relative_url }}) with these 4 heat inserts too. Screw the Lazy Susan into position through the washer and into the Top interface chute mount <span class="fastener-todo">fastener not recorded</span>.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>These screws have to be very tight. Machine vibration can work them loose.</p>
</div>

Once complete, the free section of the Lazy Susan should rotate freely.

{% include step.html n="6" title="Attach the interface chute to the assembly" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/FxpaGbyANHA?mute=1"
    title="Attaching the interface chute to the assembly"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Place the Interface big spacer on the Interface upper fixed section with its 4 holes lined up with the 4 heat inserts.

Rotate the free part of the Lazy Susan on the assembled interface chute so that 3 of its holes line up with the holes in the Top interface chute mount. Place the assembly on top of the Interface big spacer with the 3 holes aligned with 3 of the heat inserts. Screw these together tightly <span class="fastener-todo">fastener not recorded</span>.

Rotate the Top interface chute mount 90 degrees relative to the Interface upper fixed section to reveal the 4th screw hole in the Lazy Susan (it should also line up with a hole in the Interface big spacer and a heat insert). Drive a screw <span class="fastener-todo">fastener not recorded</span> tightly through this hole.

Once done, check that the chute rotates freely relative to the Interface upper fixed section.

{% include step.html n="7" title="Adjust the limit switch" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/FxpaGbyANHA?start=160&mute=1"
    title="Adjusting the limit switch"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Loosen the screws attaching the Limit switch housing to the extrusion. Slide the housing so the Limit switch hammer rotates into place between the Roller lever limit switch and the Printed dowel pin in both directions of rotation. The switch clicks when it is being activated correctly. Avoid friction between the Limit switch hammer and the Printed dowel pin. Tighten the screws to keep the housing in this position.

{% include step.html n="8" title="Install the chute stepper motor" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/z-L7_pNB8A8?mute=1"
    title="Installing the chute stepper motor"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Slide the prepared [Timing pulley]({{ '/hardware/helpers/pulley-gear-mod/' | relative_url }}) over the shaft of the NEMA 23 stepper motor and tighten the two worm screws on its side. Slide the Interface spur gear onto the Timing pulley and secure it with 5 screws <span class="fastener-todo">fastener not recorded</span>, half tapped into the Interface spur gear and half bracing against the Timing pulley.

Push a 608 2RS bearing into the Interface idler gear.

Push the idler gear onto the Interface NEMA 23 bracket with the bearing facing outwards and secure it with a button head screw <span class="fastener-todo">fastener not recorded</span> (the video uses a screw with a washer).

Slot the NEMA 23 onto the Interface NEMA 23 bracket and secure it with four M5 × 12 mm screws.

At this point the chute should still rotate, but you will now feel resistance from the stepper motor.

{% include step.html n="9" title="Attach the cable cage top" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/NUDDwb5BZH8?mute=1"
    title="Attaching the cable cage top"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Slot the Cable cage top over the Top interface chute mount, with the corners of the hexagon aligning with the Interface brackets.

Place the Cable cage bracket (cable mount) on the Interface bracket opposite the Limit switch housing (this minimises the maximum travel of the cable). Screw it into the Interface bracket with an M5 × 25 mm socket head screw and a T-nut, clamping down the Cable cage top.

Screw the other 5 Cable cage brackets down over the other 5 corners of the Cable cage top with M5 × 25 mm socket head screws and T-nuts.

{% include step.html n="10" title="Put the cable in the cable cage" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/aCNjETS1X9A?mute=1"
    title="Installing the cable in the cable cage"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Place an M3 nut into the bottom of the Cable clamp (outer) (the video skips this), then push it into the recess in the Top interface chute mount. Fasten it with two M3 × 10 mm socket head screws.

Rotate the chute until it hits the limit switch.

Fold your IDC ribbon cable around the Cable clamp (inner), following the guides on the clamp. Slide the cable and clamp together into the Cable clamp (outer), leaving a significant tail to connect to the chute.

Guide the rest of the ribbon cable around the side of the Top interface chute mount, in the direction the chute can rotate, back to the Cable cage bracket (cable mount).

Screw the Ribbon cable clamp <span class="fastener-todo">fastener not recorded</span> lightly to the Cable cage bracket (cable mount), clamping the ribbon cable between the two.

Check that the chute can rotate fully to the limit switch in both directions, then tighten the Ribbon cable clamp screw. Use a long M3 × 35 mm screw through the Cable clamp (inner) into the M3 nut in the bottom of the Cable clamp (outer) to secure that end (the video uses a different type of screw here).

{% include step.html n="11" title="Attach the cable cage bottom" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/CE3OKs5nXSk?mute=1"
    title="Attaching the cable cage bottom"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Place the Cable cage bottom over the Top interface chute mount. Use 6 M5 × 35 mm socket head screws and M5 nuts to clamp the Cable cage bottom, Cable cage top, and Cable cage brackets together.

After this step the chute should still rotate to each of its limits.

{% include step.html n="12" title="Attach the framing" %}

Insert an extrusion piece F (Interface vertical support) into each of the Interface brackets. Hold each one in place with four M5 × 20 mm button head screws into four T-nuts.

<figure>
  <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/framing-1.ae2ef835181f63bd.jpg" alt="Six vertical extrusion supports bolted into the interface brackets, seen from above on the hexagonal top plate">
</figure>

Slide an Interface spacer onto each piece of extrusion, with the lip at the top facing toward the center of the assembly.

<figure>
  <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/framing-2.b6e8241ef78d74d0.jpg" alt="An interface spacer slid onto each vertical extrusion support, lips facing inward">
</figure>

Follow the first two stages of a regular layer, then place the regular layer assembly onto the interface assembly.

<figure>
  <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/framing-3.e49b6ce3304489d5.jpg" alt="A regular layer assembly lowered onto the interface assembly">
</figure>

Attach an External bracket cover to each of the External bracket sides, then fasten each one with 2 M5 × 16 mm screws tapped into the holes at the base of the External bracket sides, bracing against the extrusion.

The top interface is now complete.

<figure>
  <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/framing-4.28f9d54d3c156c6b.jpg" alt="The completed top interface: the hexagonal top plate on its framed leg structure with the chute opening in the centre">
</figure>
