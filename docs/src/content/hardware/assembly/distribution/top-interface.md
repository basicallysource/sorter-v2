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
contributors: [barthel, brickcyclealice]
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
  - part: brg-lazy-susan
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
  - part: hsi-m4
    qty: 8
  - part: hsi-m5
    qty: 24
  - part: hsi-m3
    qty: 12
  - part: scr-m5-35-fhcs
    qty: 6
  - part: scr-m5-30-shcs
    qty: 6
  - part: scr-m5-22-cs
    qty: 15
  - part: scr-m5-8-cs
    qty: 6
  - part: scr-m5-20-shcs
    qty: 24
  - part: scr-m5-16-shcs
    qty: 38
  - part: scr-m5-12-shcs
    qty: 4
  - part: scr-m4-12-cs
    qty: 8
  - part: scr-m3-35-bhcs
    qty: 2
  - part: scr-m3-10-shcs
    qty: 3
  - part: scr-m3-12-cs
    qty: 6
  - part: scr-m3-16-shcs
    qty: 2
  - part: scr-m3-8-cs
    qty: 5
  - part: scr-m3-6-cs
    qty: 1
  - part: tnut-m5-2020
    qty: 50
  - part: nut-m5
    qty: 6
  - part: nut-m3
    qty: 1
  - part: washer-m3-15
    qty: 1
---

The fasteners and quantities in the parts list come from the build notes and are called out inline at each step.

{% include fastener-legend.html %}

Several steps below refer to holes in the Top plate by name (S2 and S3 for the stepper mount, I1 to I6 and O1 to O6 for the interface brackets). This map shows which hole is which:

<figure>
  <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/top-plate-hole-map.756f0dae2288fdb2.jpg" alt="Hole map of the hexagonal top plate: three stepper holes S1 to S3 in a row left of the center opening, six inner-ring holes I1 to I6, six outer-ring holes O1 to O6, and five cable holes C1 to C5, colour-coded by group">
  <figcaption>Top plate hole map. S = stepper trio, I = inner ring, O = outer ring, C = cable holes.</figcaption>
</figure>

{% include step.html n="1" title="Preparation" %}

Before assembling anything, press the heat inserts into the parts that take them, while the parts are still loose. Fusing them in afterwards is much harder, for example once the Interface upper fixed section is mounted to the Top plate. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Interface upper fixed section:</strong> 4 × M4</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/prep-upper-fixed-section-inserts-full.5f320973aa8f4976.jpg" alt="The Interface upper fixed section ring, underside with the NEMA 23 bracket attached, showing four brass M4 heat inserts around its face">
    <figcaption>Underside, with the NEMA 23 bracket attached.</figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Interface NEMA 23 bracket:</strong> 6 × M5 (4 on the top edges, 2 underneath) and 1 × M3 (on the tail)</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/prep-nema23-inserts.51e9fc75c2c3840c.jpg" alt="The Interface NEMA 23 bracket held up, showing four brass M5 inserts on the top edges and one M3 insert on the long tail">
    <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/prep-nema23-inserts-underside.a2c5f24a51e32932.jpg" alt="The underside of the Interface NEMA 23 bracket, showing the two remaining brass M5 heat inserts">
    <figcaption>Top: four M5 on the edges and one M3 on the tail. Underside: the two remaining M5.</figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Top interface chute mount:</strong> 4 × M4 and 7 × M3</p>
  </div>
  <div class="prep-item-figure prep-item-figure-split">
    <figure>
      <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/prep-chute-mount-inserts-underside.d9429f336757fc52.jpg" alt="The underside of the white Top interface chute mount, showing brass M4 and M3 heat inserts around the ring">
      <figcaption>Underside: the 4 M4 and 5 of the M3. The other 2 M3 sit by the cable-clamp recess on the top face.</figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/prep-chute-mount-inserts-underside-grey.f48d2c86ebeb1716.jpg" alt="A closer grey view of the Top interface chute mount underside, showing two of the M3 inserts on the ring beside the recess for the Limit switch hammer screw">
      <figcaption>A closer look at two of the M3 inserts, next to the recess for the Limit switch hammer screw.</figcaption>
    </figure>
  </div>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Interface bracket:</strong> 3 × M5 (each of the 6)</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/prep-interface-bracket-inserts.d4d01073358fa475.jpg" alt="An Interface bracket held up, showing three brass M5 heat inserts: one on each long side and one on the tail end">
    <figcaption>One M5 on each long side and one on the tail end.</figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Limit switch housing:</strong> 2 × M3</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/prep-limit-switch-housing-inserts-grey.285c56f517498819.jpg" alt="The grey Limit switch housing, showing two brass M3 heat inserts on the angled face where the roller lever limit switch mounts, with the dowel pin hole above them">
    <figcaption>The two M3 inserts, where the roller lever limit switch mounts.</figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Limit switch hammer:</strong> 1 × M3</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/prep-limit-switch-hammer-inserts.8f73ff6876cebff2.jpg" alt="The Limit switch hammer held up, showing a single brass M3 heat insert in its round disc">
    <figcaption>One M3 insert in the round disc.</figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Cable cage bracket (cable mount):</strong> 1 × M3</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/prep-cable-cage-bracket-cable-inserts.72708f4941f1b0da.jpg" alt="The Cable cage bracket (cable mount) held up, showing a single brass M3 heat insert">
    <figcaption>The one M3 insert in the Cable cage bracket (cable mount).</figcaption>
  </figure>
</div>

Printed parts elsewhere in the machine take inserts too. Each assembly page lists its own in a **Preparation** step like this one, so press them in as you reach that page.

{% include step.html n="2" title="Attach the interface ribs to the upper fixed section" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/O_ApnzrWRsE?mute=1"
    title="Attaching the interface ribs to the interface upper fixed section"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

**Heat inserts first:** press the 4 × M4 inserts into the Interface upper fixed section and the 6 × M5 and 1 × M3 inserts into the Interface NEMA 23 bracket before you assemble anything here.

Attach the Interface rib (switch gap) to the Interface upper fixed section, two positions counterclockwise of the notch for the stepper mount. Use two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws, tapping directly into the plastic.

Attach the remaining 5 Interface ribs to the Interface upper fixed section, two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws each, again tapping into the plastic.

Slot the Interface NEMA 23 bracket into the Interface upper fixed section and secure it from below with an {% include fastener.html size="M3" variant="countersunk" length="12" %} screw.

Attach the whole assembly to the bottom of the Top plate with {% include fastener.html size="M5" variant="countersunk" length="22" %} screws through holes S2 and S3 into the Interface NEMA 23 bracket.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/step2-ribs-upper-fixed-section.7d3f252818e7e1a9.jpg" alt="Six grey Interface ribs attached around the circular Interface upper fixed section">
    <figcaption>The 6 Interface ribs attached to the Interface upper fixed section.</figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/step2-nema23-bracket-underside.2b9fc415b05a6d76.jpg" alt="Underside of the Interface upper fixed section with the Interface NEMA 23 bracket seated in its notch">
    <figcaption>Underside, with the Interface NEMA 23 bracket seated in its notch.</figcaption>
  </figure>
</div>

{% include step.html n="3" title="Prepare the interface brackets" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/-mtU3WXP73M?mute=1"
    title="Preparing the interface brackets"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

**Heat inserts first:** each Interface bracket takes 3 × M5 inserts. Press them in before fitting the extrusion.

Align an Interface bracket with piece E (Interface spoke, long) of aluminum extrusion.

Place T-nuts in the extrusion, lined up with the 4 holes on the side of the Interface bracket.

Slide the extrusion into the Interface bracket, careful not to dislodge the T-nuts, and drive four {% include fastener.html size="M5" variant="socket-button" length="16" %} screws into them.

Repeat for all 6 Interface brackets.

{% include step.html n="4" title="Prepare the limit switch interface bracket" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/YzYzytRl3p4?mute=1"
    title="Preparing the limit switch interface bracket"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

**Heat inserts first:** the Limit switch housing takes 2 × M3 inserts. Press them in before assembling it.

Push the Printed dowel pin into the Limit switch housing.

Attach a Roller lever limit switch with two {% include fastener.html size="M3" variant="socket-button" length="16" %} screws (into the housing's 2 M3 inserts) so the roller sits next to the dowel pin.

Align the switch housing with the extrusion of one of the prepared Interface brackets so the limit switch is on the same face as the sloped side of the bracket. Slide 2 T-nuts into the extrusion and fasten the Limit switch housing to the extrusion with two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws. Slide it as far toward the Interface bracket as possible for now; it gets aligned properly later.

{% include step.html n="5" title="Install the brackets" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/K7r15si5yxI?mute=1"
    title="Installing the interface brackets"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Slide a T-nut just into the end of the extrusion of the limit switch interface bracket. Slide the extrusion into the Interface rib (switch gap) and Interface upper fixed section, securing it loosely with an {% include fastener.html size="M5" variant="countersunk" length="8" %} screw. Slide the extrusion slightly in and out to align the holes on the Interface bracket with the holes on the Top plate, then tighten the screw.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>The M5 × 8 mm is a snug fit here, it barely reaches the T-nut. Opening the countersink a little and tightening firmly gets the head to sit flush.</p>
</div>

Repeat with the 5 other prepared Interface brackets into the 5 other Interface ribs.

Flip the whole assembly and screw all 6 Interface brackets into place with {% include fastener.html size="M5" variant="countersunk" length="22" %} screws through holes I1 to I6 and O1 to O6.

**Alternative:** the Top plate's laser-cut holes are not countersunk, so a countersunk head does not seat flush. {% include fastener.html size="M5" variant="socket-button" length="20" %} screws work here instead.

{% include step.html n="6" title="Prepare the interface chute gear and mount" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/7oYiOXYF8rA?mute=1"
    title="Preparing the interface chute gear and mount"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

**Heat inserts first:** the Top interface chute mount takes 4 × M4 and 7 × M3 inserts, and the Limit switch hammer takes 1 × M3. Press them in before assembling.

Slot the Limit switch hammer into the Top interface chute mount, then secure it from below with an {% include fastener.html size="M3" variant="countersunk" length="6" %} screw (into the hammer's M3 insert).

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>The M3 × 6 mm screw head must sit completely flush with the printed Top interface chute mount. It lies inside the Lazy Susan's rotation path, so a raised head will catch.</p>
</div>

Align the Chute gear on the Top interface chute mount with the notch by the screw for the Limit switch hammer. Attach it with five {% include fastener.html size="M3" variant="countersunk" length="12" %} screws.

Align the Top interface lazy Susan washer with the 4 inner heat inserts on the Top interface chute mount. Align the inner ring of the [Lazy Susan]({{ '/hardware/parts/lazy-susan/' | relative_url }}) with these 4 heat inserts too. Screw the Lazy Susan into position through the washer and into the Top interface chute mount with four {% include fastener.html size="M4" variant="countersunk" length="12" %} screws.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>These screws have to be very tight. A drill or electric screwdriver will not get them there, so finish them with a hex key by hand. Machine vibration works a loose one out.</p>
</div>

Once complete, the free section of the Lazy Susan should rotate freely.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/step6-chute-mount-gear-side.6ea1334010316081.jpg" alt="Gear side of the assembled Top interface chute mount, showing the chute gear, Lazy Susan, and Limit switch hammer">
    <figcaption>Gear side, with the Chute gear, Lazy Susan, and Limit switch hammer installed.</figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/step6-chute-mount-underside.9820f5b75d239018.jpg" alt="Chute side of the assembled Top interface chute mount with the Limit switch hammer extending from the edge">
    <figcaption>Chute side of the assembled gear and mount.</figcaption>
  </figure>
</div>

{% include step.html n="7" title="Attach the interface chute to the assembly" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/FxpaGbyANHA?mute=1"
    title="Attaching the interface chute to the assembly"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Place the Interface big spacer on the Interface upper fixed section with its 4 holes lined up with the 4 heat inserts.

Rotate the free part of the Lazy Susan on the assembled interface chute so that 3 of its holes line up with the holes in the Top interface chute mount. Place the assembly on top of the Interface big spacer with the 3 holes aligned with 3 of the heat inserts. Screw these together tightly with three {% include fastener.html size="M4" variant="countersunk" length="12" %} screws.

Rotate the Top interface chute mount 90 degrees relative to the Interface upper fixed section to reveal the 4th screw hole in the Lazy Susan (it should also line up with a hole in the Interface big spacer and a heat insert). Drive a fourth {% include fastener.html size="M4" variant="countersunk" length="12" %} screw tightly through this hole.

Once done, check that the chute rotates freely relative to the Interface upper fixed section.

{% include step.html n="8" title="Adjust the limit switch" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/FxpaGbyANHA?start=160&mute=1"
    title="Adjusting the limit switch"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Loosen the screws attaching the Limit switch housing to the extrusion. Slide the housing so the Limit switch hammer rotates into place between the Roller lever limit switch and the Printed dowel pin in both directions of rotation. The switch clicks when it is being activated correctly. Avoid friction between the Limit switch hammer and the Printed dowel pin. Tighten the screws to keep the housing in this position.

{% include step.html n="9" title="Install the chute stepper motor" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/z-L7_pNB8A8?mute=1"
    title="Installing the chute stepper motor"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Slide the prepared [Timing pulley]({{ '/hardware/helpers/pulley-gear-mod/' | relative_url }}) over the shaft of the NEMA 23 stepper motor and tighten the two worm screws on its side. Slide the Interface spur gear onto the Timing pulley and secure it with five {% include fastener.html size="M3" variant="countersunk" length="8" %} screws, half tapped into the Interface spur gear and half bracing against the Timing pulley.

Push a 608 2RS bearing into the Interface idler gear.

Push the idler gear onto the Interface NEMA 23 bracket with the bearing facing outwards.

Slide an M3 × 15 mm washer onto an {% include fastener.html size="M3" variant="flat" length="35" %} screw, then drive that screw through the bearing and into the bracket. The washer sits between the screw head and the outer face of the bearing, spanning its 8 mm bore: the screw head on its own is narrower than the bore and drops down inside it, so the washer is what actually holds the idler gear onto the bracket. Tighten until the washer is seated, then check that the idler gear still spins freely.

The head has to be a low one here. A socket or button head stands proud enough that the Limit switch hammer can catch on it as the chute sweeps past, so use a flat (pancake) head, or a pan head if that is what you have. It is the same screw as the one on the Cable clamp in step 11, so buy two of the one head type.

Slot the NEMA 23 onto the Interface NEMA 23 bracket and secure it with four {% include fastener.html size="M5" variant="socket-button" length="12" %} screws.

At this point the chute should still rotate, but you will now feel resistance from the stepper motor.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/step9-timing-pulley-on-motor.fdc302e89a48e23f.jpg" alt="Timing pulley installed on the shaft of a NEMA 23 stepper motor">
    <figcaption>Timing pulley installed on the NEMA 23 shaft.</figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/step9-interface-spur-gear.7c03bd4052826aaa.jpg" alt="Grey Interface spur gear secured over the timing pulley with five countersunk screws">
    <figcaption>Interface spur gear secured over the Timing pulley with five M3 × 8 mm screws.</figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/step9-idler-gear-bearing.e4ae66ea7d10f086.jpg" alt="608 2RS bearing pressed into the centre of the grey Interface idler gear">
    <figcaption>608 2RS bearing pressed into the Interface idler gear.</figcaption>
  </figure>
</div>

{% include step.html n="10" title="Attach the cable cage top" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/NUDDwb5BZH8?mute=1"
    title="Attaching the cable cage top"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

**Heat inserts first:** the Cable cage bracket (cable mount) takes 1 × M3 insert. Press it in before assembling.

Slot the Cable cage top over the Top interface chute mount, with the corners of the hexagon aligning with the Interface brackets.

Screw the Cable cage bracket (cable mount), on the Interface bracket opposite the Limit switch housing (this minimises the maximum travel of the cable), securely to the tail end of that Interface bracket with an {% include fastener.html size="M5" variant="socket-button" length="30" %} screw into the M5 heat insert, clamping the Cable cage top firmly in place.

Screw the remaining Cable cage brackets to the other 5 corners of the Cable cage top with {% include fastener.html size="M5" variant="socket-button" length="30" %} screws.

{% include step.html n="11" title="Put the cable in the cable cage" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/aCNjETS1X9A?mute=1"
    title="Installing the cable in the cable cage"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Place an {% include fastener.html size="M3" variant="nut" %} into the bottom of the Cable clamp (outer) (the video skips this), then push it into the recess in the Top interface chute mount. Fasten it with two {% include fastener.html size="M3" variant="socket-button" length="10" %} screws.

Rotate the chute until it hits the limit switch.

Fold your IDC ribbon cable around the Cable clamp (inner), following the guides on the clamp. Slide the cable and clamp together into the Cable clamp (outer), leaving a significant tail to connect to the chute.

Guide the rest of the ribbon cable around the side of the Top interface chute mount, in the direction the chute can rotate, back to the Cable cage bracket (cable mount).

Screw the Ribbon cable clamp lightly to the Cable cage bracket (cable mount) with one {% include fastener.html size="M3" variant="socket-button" length="10" %} screw, clamping the ribbon cable between the two.

Check that the chute can rotate fully to the limit switch in both directions, then tighten the Ribbon cable clamp screw. Use a long {% include fastener.html size="M3" variant="flat" length="35" %} screw through the Cable clamp (inner) into the {% include fastener.html size="M3" variant="nut" %} in the bottom of the Cable clamp (outer) to secure that end.

{% include step.html n="12" title="Attach the cable cage bottom" %}

<div class="video-embed video-embed-wide">
  <iframe
    src="https://www.youtube.com/embed/CE3OKs5nXSk?mute=1"
    title="Attaching the cable cage bottom"
    allow="encrypted-media; picture-in-picture; web-share"
    allowfullscreen
    loading="lazy"></iframe>
</div>

Place the Cable cage bottom over the Top interface chute mount. Use 6 {% include fastener.html size="M5" variant="flat" length="35" %} screws and {% include fastener.html size="M5" variant="nut" %}s to clamp the Cable cage bottom, Cable cage top, and Cable cage brackets together.

After this step the chute should still rotate to each of its limits.

{% include step.html n="13" title="Attach the framing" %}

Insert an extrusion piece F (Interface vertical support) into each of the Interface brackets. Hold each one in place with four {% include fastener.html size="M5" variant="socket-button" length="20" %} screws into four T-nuts.

<figure>
  <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/framing-1.ae2ef835181f63bd.jpg" alt="Six vertical extrusion supports bolted into the interface brackets, seen from above on the hexagonal top plate">
</figure>

Slide an Interface spacer onto each piece of extrusion, with the lip at the top facing toward the center of the assembly.

<figure>
  <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/framing-2.b6e8241ef78d74d0.jpg" alt="An interface spacer slid onto each vertical extrusion support, lips facing inward">
</figure>

Follow the first two stages of [a regular layer]({{ '/hardware/assembly/distribution/bin-frame/regular-layers/' | relative_url }}), then place the regular layer assembly onto the interface assembly.

<figure>
  <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/framing-3.e49b6ce3304489d5.jpg" alt="A regular layer assembly lowered onto the interface assembly">
</figure>

Attach an External bracket cover to each of the External bracket sides, then fasten each one with 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws into the holes at the base of the External bracket sides, bracing against the extrusion. These holes run parallel to the extrusion profile, and the screws are self-tapping. See the [external bracket]({{ '/hardware/assembly/distribution/external-bracket/' | relative_url }}) instructions for building the bracket itself.

{% include step.html n="14" title="How the interface joins the top layer" %}

<figure>
  <a href="https://img.basically.website/originals/assembly/top-interface/framing-joint.ed0a06d244ffe45d.png" target="_blank" rel="noopener">
    <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/framing-joint.be2cac2fd31d13c3.jpg" alt="The interface assembly upside down on its top plate with six vertical extrusions standing out of it, each held in an interface bracket and sleeved by an interface spacer">
  </a>
  <figcaption>The interface framing before the top layer goes on, with one arm marked 1 to 3. Click the photo to open it full size.</figcaption>
</figure>

<figure class="figure-float-right">
  <a href="https://img.basically.website/originals/assembly/top-interface/joint-section.e96f8eb4493c6488.png" target="_blank" rel="noopener">
    <img src="https://img.basically.website/web/assembly/top-interface/joint-section.78eb670eb255aa81.jpg" alt="Vertical cross-section through one interface corner, showing the interface bracket and spacer in purple, piece F in grey running down into the top layer's bracket in blue">
  </a>
  <figcaption>The same corner in section, cut through the centre of the profile. Purple is the interface, blue the top layer's bracket, grey the extrusion. Click to enlarge. The interface parts are not exported in a shared frame with the layer parts, so the part lengths are measured but their heights come from seating each one on the part below it.</figcaption>
</figure>

This joint is not the same as the one between two layers, so it is worth naming what is different. There is **no External bracket — bottom vertical and no flange here**, and therefore none of the vertical screws that hold one layer to the next. Piece F is instead gripped at the interface end and clamped at the layer end, and it is sleeved the whole way between them, so no extrusion shows on a finished machine.

The numbers on the photo and the drawing:

<ol class="keyed-list">
  <li><strong>Interface bracket</strong>, one per corner, a 120 mm channel around the extrusion. Piece F is held in it by 4 {% include fastener.html size="M5" variant="socket-button" length="20" %} screws into {% include fastener.html size="M5" variant="t-nut" text="T-nuts" %}, the only place in the framing where a vertical is fixed with T-nuts rather than a self-tapping screw.</li>
  <li><strong>Interface spacer</strong>, a 129.7 mm sleeve, slid onto the extrusion with its lip at the top facing the centre. It takes no screws and simply sits between the bracket and the layer's collar.</li>
  <li><strong>Piece F</strong>, 274 mm cut (280 mm in CAD) against a layer's 154 mm, so the interface sits 120 mm further above the top layer than one layer's spacing.</li>
  <li><strong>The top layer's External bracket — side</strong>, with its cover, exactly the collar any layer has.</li>
  <li class="key-screw"><strong>Two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws</strong> at the base of that bracket brace it against the extrusion, the same screws and holes a layer's own vertical gets. Nothing else fastens the interface to the layer.</li>
</ol>

<div class="clear-float"></div>

The top interface is now complete.

<figure>
  <img class="doc-figure" src="https://img.basically.website/web/assembly/top-interface/framing-4.28f9d54d3c156c6b.jpg" alt="The completed top interface: the hexagonal top plate on its framed leg structure with the chute opening in the centre">
  <figcaption>The finished interface, seen from above with the top plate on.</figcaption>
</figure>
