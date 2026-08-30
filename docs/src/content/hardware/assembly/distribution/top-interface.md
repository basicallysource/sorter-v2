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
warning: >-
  **Steps 13 and 14 were rewritten to reference [Build the hex frame]({{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }})
  and to describe the interface-to-layer joint from CAD geometry, and neither
  has been checked against a build yet.** If something doesn't match what you
  see, treat it as unverified and flag it rather than assuming it's your
  mistake. The rest of the page is unaffected.
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
  - part: chute-stepper-idler-bearing-retainer-outer
    qty: 1
  - part: chute-stepper-idler-bearing-retainer-inner
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
  - part: hsi-m3
    qty: 16
  - part: hsi-m4
    qty: 8
  - part: hsi-m5
    qty: 24
  - part: scr-m3-6-cs
    qty: 1
  - part: scr-m3-8-cs
    qty: 9
  - part: scr-m3-10-shcs
    qty: 3
  - part: scr-m3-12-cs
    qty: 6
  - part: scr-m3-16-shcs
    qty: 2
  - part: scr-m3-35-bhcs
    qty: 2
  - part: scr-m4-12-cs
    qty: 8
  - part: scr-m5-8-cs
    qty: 6
  - part: scr-m5-12-shcs
    qty: 4
  - part: scr-m5-16-shcs
    qty: 50
  - part: scr-m5-20-shcs
    qty: 24
  - part: scr-m5-22-cs
    qty: 15
  - part: scr-m5-30-shcs
    qty: 6
  - part: scr-m5-35-fhcs
    qty: 6
  - part: nut-m3
    qty: 1
  - part: tnut-m5-2020
    qty: 56
  - part: nut-m5
    qty: 6
tools_needed: [Hex key, Soldering iron or heat-set insert press]
---

The top interface holds a chute that rotates on a lazy-susan bearing to aim incoming parts at whichever bin layer is currently selected. A NEMA 23 stepper drives the rotation through a small gear train (steps 6 and 9), and a limit switch and hammer (steps 4, 6, 8) give it a fixed reference point to home against, since the stepper alone has no way to know which way it is pointed. Everything on this page bolts onto the Top plate, which then sits on the hex frame built on the bin-frame page.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Have a <a href="{{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}">hex frame</a> ready by step 13.</strong> It's a required component of this page — step 13 places one onto the assembly, it doesn't build one. The rest of this page (steps 1-12, 14+) doesn't need it.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/hex-frame-finished-top-down-full-c6abfb4dad6e.jpg" alt="A finished hex frame from above, the alternating grey spoke and teal crossbeam pieces forming the inner ring inside the aluminum outer hexagon">
    <figcaption>A finished hex frame. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Have the <a href="https://parts-calculator.basically.website/lasercut">Top plate</a> laser-cut and ready by step 2.</strong> It's not printed or built on any page, it's ordered or hand-cut ahead of time — see the parts calculator's lasercut page for the DXF and hand-cut instructions.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/top-interface-top-plate-w1600-00182ea8156d.jpg" alt="The machine's hexagonal top plate, laser-cut, with cable holes and stepper mount holes visible">
    <figcaption>The Top plate.</figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Have the <a href="https://parts-calculator.basically.website/lasercut">Cable cage top</a> laser-cut and ready by step 10, and the Cable cage bottom by step 12.</strong> Same as the Top plate: laser-cut ahead of time, not built on this page.</p>
  </div>
  <div class="prep-item-figure prep-item-figure-split">
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/top-interface-cable-cage-top-full-9e4c43a620ca.png" alt="The Cable cage top, a laser-cut hexagonal plate with a keyed centre cutout">
      <figcaption>Cable cage top.</figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/top-interface-cable-cage-bottom-full-283aeb114195.png" alt="The Cable cage bottom, a laser-cut hexagonal plate with a large centre cutout">
      <figcaption>Cable cage bottom.</figcaption>
    </figure>
  </div>
</div>

The fasteners and quantities in the parts list come from the build notes and are called out inline at each step.

{% include fastener-legend.html %}

Several steps below refer to holes in the Top plate by name (S2 and S3 for the stepper mount, I1 to I6 and O1 to O6 for the interface brackets). This map shows which hole is which:

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-top-plate-hole-map-full-423bbae45ba3.png" alt="Hole map of the hexagonal top plate: three stepper holes S1 to S3 in a row left of the center opening, six inner-ring holes I1 to I6, six outer-ring holes O1 to O6, and five cable holes C1 to C5, colour-coded by group">
  <figcaption>Top plate hole map. S = stepper trio, I = inner ring, O = outer ring, C = cable holes. <cite>Render: Balloon.</cite></figcaption>
</figure>

{% include step.html n="1" title="Preparation" %}

Before assembling anything, press all the heat inserts listed below into their parts while the parts are still loose — this covers every insert used on this page. Fusing them in afterwards is much harder, for example once the Interface upper fixed section is mounted to the Top plate. Later steps repeat each insert count as a reminder only; you don't need to press anything a second time. See [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}) for the technique.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Interface upper fixed section:</strong> 4 × M4</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-prep-upper-fixed-section-inserts-full-ful-4f73af3a5587.png" alt="The Interface upper fixed section ring, underside with the NEMA 23 bracket attached, showing four brass M4 heat inserts around its face">
    <figcaption>Underside, with the NEMA 23 bracket attached. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Interface NEMA 23 bracket:</strong> 6 × M5 (4 on the top edges, 2 underneath) and 1 × M3 (on the tail)</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-prep-nema23-inserts-full-5fda8f6ef8c0.png" alt="The Interface NEMA 23 bracket held up, showing four brass M5 inserts on the top edges and one M3 insert on the long tail">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-prep-nema23-inserts-underside-full-97cf1ce3e1b0.png" alt="The underside of the Interface NEMA 23 bracket, showing the two remaining brass M5 heat inserts">
    <figcaption>Top: four M5 on the edges and one M3 on the tail. Underside: the two remaining M5. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Top interface chute mount:</strong> 4 × M4 and 7 × M3</p>
  </div>
  <div class="prep-item-figure prep-item-figure-split">
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-prep-chute-mount-inserts-underside-full-ec67c0262221.png" alt="The underside of the white Top interface chute mount, showing brass M4 and M3 heat inserts around the ring">
      <figcaption>Underside: the 4 M4 and 5 of the M3. The other 2 M3 sit by the cable-clamp recess on the top face. <cite>Photo: BrickCycleAlice.</cite></figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-prep-chute-mount-inserts-underside-grey-w-52b54ffa44db.jpg" alt="A closer grey view of the Top interface chute mount underside, showing two of the M3 inserts on the ring beside the recess for the Limit switch hammer screw">
      <figcaption>A closer look at two of the M3 inserts, next to the recess for the Limit switch hammer screw. <cite>Photo: BrickCycleAlice.</cite></figcaption>
    </figure>
  </div>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Interface bracket:</strong> 3 × M5 (each of the 6)</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/top-interface-prep-interface-bracket-inserts-full-799264fe5508.jpg" alt="An Interface bracket held up, showing three brass M5 heat inserts: one near the top boss, one in the middle of the channel, and one at the bottom end">
    <figcaption>One M5 on each long side and one on the tail end, including the one in the channel that's easy to miss. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Limit switch housing:</strong> 2 × M3</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-prep-limit-switch-housing-inserts-grey-w1-ef9cced25713.jpg" alt="The grey Limit switch housing, showing two brass M3 heat inserts on the angled face where the roller lever limit switch mounts, with the dowel pin hole above them">
    <figcaption>The two M3 inserts, where the roller lever limit switch mounts. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Limit switch hammer:</strong> 1 × M3</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-prep-limit-switch-hammer-inserts-full-ff286afdd969.png" alt="The Limit switch hammer held up, showing a single brass M3 heat insert in its round disc">
    <figcaption>One M3 insert in the round disc. <cite>Photo: zed0.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Cable cage bracket (cable mount):</strong> 1 × M3</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-prep-cable-cage-bracket-cable-inserts-ful-9188d3883103.png" alt="The Cable cage bracket (cable mount) held up, showing a single brass M3 heat insert">
    <figcaption>The one M3 insert in the Cable cage bracket (cable mount). <cite>Photo: zed0.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Interface idler gear:</strong> 4 × M3, around the bearing pocket on the underside</p>
    <p>Build the bearing sub-assembly now too, while the gear is still loose — it is easier off the bracket than on it. Push a 608 2RS bearing into the pocket, fit the Chute stepper idler bearing retainer (inner) over the bearing's bore, then the Chute stepper idler bearing retainer (outer) over that, seated flush in the recess with its 4 holes lined up on the gear's 4 inserts. Secure it with 4 × {% include fastener.html size="M3" variant="countersunk" length="8" %} screws, the same M3 x 8 mm countersunk screw used on the Interface spur gear in step 9. See step 9 for how the idler gear then goes onto the bracket.</p>
  </div>
  <div class="prep-item-figure prep-item-figure-split">
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/assembly-top-interface-prep-idler-gear-inserts-full-82137b8be2a0.jpg" alt="The Interface idler gear alone, showing all 4 brass M3 heat inserts around the bearing pocket">
      <figcaption>The 4 M3 inserts around the bearing pocket, before the bearing goes in. <cite>Photo: BrickCycleAlice.</cite></figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/idler-exploded-3color-full-227310630981.png" alt="An exploded view from below of the idler gear stack in build order: the grey gear, the bearing highlighted in blue, and the inner and outer bearing retainer caps highlighted in red">
      <figcaption>Exploded, in build order: gear, bearing, inner cap, outer ring. <cite>Render: Balloon.</cite></figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/assembly-top-interface-prep-idler-gear-bearing-inserts-full-974df2574ede.jpg" alt="608 2RS bearing pressed into the centre of the grey Interface idler gear, with the 4 brass M3 heat inserts visible around it, before the bearing retainer caps go on">
      <figcaption>608 2RS bearing pressed into the pocket, inserts visible, caps not yet on. <cite>Photo: BrickCycleAlice.</cite></figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/idler-assembled-3color-full-7de4573e7301.png" alt="The Interface idler gear seen from below at an angle, assembled, with the bearing highlighted in blue showing through the centre and the outer and inner bearing retainer caps highlighted in red, the outer retainer's four countersunk screw holes visible">
      <figcaption>Assembled: bearing pocket recess with both retainer caps fitted. <cite>Render: Balloon.</cite></figcaption>
    </figure>
    <figure>
      <img class="doc-figure" src="https://assets.basically.website/sorter-parts/assembly-top-interface-prep-idler-gear-caps-mounted-full-ea79c7aa9a44.jpg" alt="The Interface idler gear with the bearing retainer caps mounted for real, the 4 screws seated flush in place of the heat inserts">
      <figcaption>The retainer caps mounted for real, matching the render above. <cite>Photo: BrickCycleAlice.</cite></figcaption>
    </figure>
  </div>
</div>

{% include step.html n="2" title="Attach the interface ribs to the upper fixed section" %}

<figure class="video-figure">
  <div class="video-embed video-embed-wide">
    <iframe
      src="https://www.youtube.com/embed/O_ApnzrWRsE?mute=1"
      title="Attaching the interface ribs to the interface upper fixed section"
      allow="encrypted-media; picture-in-picture; web-share"
      allowfullscreen
      loading="lazy"></iframe>
  </div>
  <figcaption><cite>Video: zed0.</cite></figcaption>
</figure>

**Heat inserts first:** press the 4 × M4 inserts into the Interface upper fixed section and the 6 × M5 and 1 × M3 inserts into the Interface NEMA 23 bracket before you assemble anything here.

Attach the Interface rib (switch gap) to the Interface upper fixed section, two positions counterclockwise of the stepper-mount notch when viewed from above (see photo). Use two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws, tapping directly into the plastic.

Attach the remaining 5 Interface ribs to the Interface upper fixed section, two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws each, again tapping into the plastic.

Slot the Interface NEMA 23 bracket into the Interface upper fixed section and secure it from below with an {% include fastener.html size="M3" variant="countersunk" length="12" %} screw.

Attach the whole assembly to the bottom of the Top plate with {% include fastener.html size="M5" variant="countersunk" length="22" %} screws through holes S2 and S3 into the Interface NEMA 23 bracket.

**Alternative:** whether these need a countersunk head depends on how your Top plate was cut. If the S2/S3 holes have a countersink cut in, use a countersunk head; if they don't, {% include fastener.html size="M5" variant="socket-button" length="20" %} screws work here instead. Builder's call depending on their plate, the same as the I1-I6/O1-O6 screws in step 5.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/img-4305-full-931aaff1af40.jpg" alt="Close-up of a hand-cut plywood Top plate showing a countersunk screw hole near the S3 hole position">
    <figcaption>A hand-cut Top plate with the S2/S3 holes countersunk. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-step2-ribs-upper-fixed-section-w1600-4ebd47453115.jpg" alt="Six grey Interface ribs attached around the circular Interface upper fixed section">
    <figcaption>The 6 Interface ribs attached to the Interface upper fixed section. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-step2-nema23-bracket-underside-w1600-cb1666b20cca.jpg" alt="Underside of the Interface upper fixed section with the Interface NEMA 23 bracket seated in its notch">
    <figcaption>Underside, with the Interface NEMA 23 bracket seated in its notch. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="3" title="Prepare the interface brackets" %}

<figure class="video-figure">
  <div class="video-embed video-embed-wide">
    <iframe
      src="https://www.youtube.com/embed/-mtU3WXP73M?mute=1"
      title="Preparing the interface brackets"
      allow="encrypted-media; picture-in-picture; web-share"
      allowfullscreen
      loading="lazy"></iframe>
  </div>
  <figcaption><cite>Video: zed0.</cite></figcaption>
</figure>

**Heat inserts first:** each Interface bracket takes 3 × M5 inserts. Press them in before fitting the extrusion.

These six brackets are what the vertical extrusion legs (piece F, step 13) will anchor into once the framing goes on.

Align an Interface bracket with piece E (Interface spoke, long) of aluminum extrusion.

Place T-nuts in the extrusion, lined up with the 4 holes on the side of the Interface bracket.

Slide the extrusion into the Interface bracket, careful not to dislodge the T-nuts, and drive four {% include fastener.html size="M5" variant="socket-button" length="16" %} screws into them.

<div class="callout">
  <span class="callout-icon" aria-hidden="true">💡</span>
  <p>Thread the four screws a couple of turns into the T-nuts before sliding the extrusion in, so they hang in place instead of sitting loose in the channel. Easier than aligning four free T-nuts by feel. <cite>Tip: BrickCycleAlice.</cite></p>
</div>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/img-4293-full-d11cce819ba3.jpg" alt="Four M5 screws threaded a few turns into T-nuts hanging in the Interface bracket's channel before the extrusion is slid in">
    <figcaption>Screws threaded into the T-nuts first, ready for the extrusion. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

Repeat for all 6 Interface brackets.

{% include step.html n="4" title="Prepare the limit switch interface bracket" %}

<figure class="video-figure">
  <div class="video-embed video-embed-wide">
    <iframe
      src="https://www.youtube.com/embed/YzYzytRl3p4?mute=1"
      title="Preparing the limit switch interface bracket"
      allow="encrypted-media; picture-in-picture; web-share"
      allowfullscreen
      loading="lazy"></iframe>
  </div>
  <figcaption><cite>Video: zed0.</cite></figcaption>
</figure>

**Heat inserts first:** the Limit switch housing takes 2 × M3 inserts. Press them in before assembling it.

This switch is the chute's home reference: because the stepper motor that will drive the chute (step 9) has no inherent sense of position, the machine homes against this switch and hammer on startup to know which bin the chute is aimed at.

Push the Printed dowel pin into the Limit switch housing.

Attach the Roller lever limit switch (the "endstop-mechanical" part in your kit) with two {% include fastener.html size="M3" variant="socket-button" length="16" %} screws (into the housing's 2 M3 inserts) so the roller sits next to the dowel pin.

Align the switch housing with the extrusion of one of the prepared Interface brackets so the limit switch is on the same face as the sloped side of the bracket. Slide 2 T-nuts into the extrusion and fasten the Limit switch housing to the extrusion with two {% include fastener.html size="M5" variant="socket-button" length="16" %} screws. Slide it as far toward the Interface bracket as possible for now; it gets aligned properly later.

<div class="callout">
  <span class="callout-icon" aria-hidden="true">💡</span>
  <p>Same trick as the Interface brackets above: thread the two screws into the T-nuts first, then slide the extrusion in with them already hanging in place. <cite>Tip: BrickCycleAlice.</cite></p>
</div>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/img-4301-full-9ca956feeb74.jpg" alt="Two T-nuts threaded onto their screws on the Limit switch housing's mounting face, ready for the extrusion">
    <figcaption>T-nuts threaded on before the extrusion goes in. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="5" title="Install the brackets" %}

<figure class="video-figure">
  <div class="video-embed video-embed-wide">
    <iframe
      src="https://www.youtube.com/embed/K7r15si5yxI?mute=1"
      title="Installing the interface brackets"
      allow="encrypted-media; picture-in-picture; web-share"
      allowfullscreen
      loading="lazy"></iframe>
  </div>
  <figcaption><cite>Video: zed0.</cite></figcaption>
</figure>

Slide a T-nut just into the end of the extrusion of the limit switch interface bracket. Slide the extrusion into the Interface rib (switch gap) and Interface upper fixed section, securing it loosely with an {% include fastener.html size="M5" variant="countersunk" length="8" %} screw. Slide the extrusion slightly in and out to align the holes on the Interface bracket with the holes on the Top plate, then tighten the screw.

<div class="callout">
  <span class="callout-icon" aria-hidden="true">💡</span>
  <p>Keep this loose for now, the bracket also gets fixed through the Top plate in the next step. Check by looking straight through the Top plate's own screw hole, not by feel alone. <cite>Tip: BrickCycleAlice.</cite></p>
</div>

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/img-4311-full-f9e44da3df95.jpg" alt="Looking down through one of the Top plate's screw holes, with light visible through it into the extrusion channel below">
    <figcaption>What a clear sightline through the hole looks like. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>The M5 × 8 mm is a snug fit here, it barely reaches the T-nut. Opening the countersink a little and tightening firmly gets the head to sit flush.</p>
</div>

Repeat with the 5 other prepared Interface brackets into the 5 other Interface ribs.

Flip the whole assembly and screw all 6 Interface brackets into place with {% include fastener.html size="M5" variant="countersunk" length="22" %} screws through holes I1 to I6 and O1 to O6.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Alternative: the Top plate's laser-cut holes are not countersunk, so a countersunk head does not seat flush. {% include fastener.html size="M5" variant="socket-button" length="20" %} screws work here instead.</p>
</div>

<div class="callout">
  <span class="callout-icon" aria-hidden="true">💡</span>
  <p>Go back and fully tighten the M5 × 8 mm screws left loose earlier in this step, now that each bracket is also bolted through its I/O holes. This is also where a hand-cut Top plate's I/O holes show up as inaccurate, if they do; widen them if a bolt is binding. <cite>Tip: BrickCycleAlice.</cite></p>
</div>

{% include step.html n="6" title="Prepare the interface chute gear and mount" %}

<figure class="video-figure">
  <div class="video-embed video-embed-wide">
    <iframe
      src="https://www.youtube.com/embed/7oYiOXYF8rA?mute=1"
      title="Preparing the interface chute gear and mount"
      allow="encrypted-media; picture-in-picture; web-share"
      allowfullscreen
      loading="lazy"></iframe>
  </div>
  <figcaption><cite>Video: zed0.</cite></figcaption>
</figure>

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
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-step6-chute-mount-gear-side-w1600-c3ac0c996f20.jpg" alt="Gear side of the assembled Top interface chute mount, showing the chute gear, Lazy Susan, and Limit switch hammer">
    <figcaption>Gear side, with the Chute gear, Lazy Susan, and Limit switch hammer installed. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-step6-chute-mount-underside-w1600-ef7ef1645c43.jpg" alt="Chute side of the assembled Top interface chute mount with the Limit switch hammer extending from the edge">
    <figcaption>Chute side of the assembled gear and mount. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="7" title="Attach the interface chute to the assembly" %}

<figure class="video-figure">
  <div class="video-embed video-embed-wide">
    <iframe
      src="https://www.youtube.com/embed/FxpaGbyANHA?mute=1"
      title="Attaching the interface chute to the assembly"
      allow="encrypted-media; picture-in-picture; web-share"
      allowfullscreen
      loading="lazy"></iframe>
  </div>
  <figcaption><cite>Video: zed0.</cite></figcaption>
</figure>

Place the Interface big spacer on the Interface upper fixed section with its 4 holes lined up with the 4 heat inserts.

Rotate the free part of the Lazy Susan on the chute mount assembly from step 6 so that 3 of its holes line up with the holes in the Top interface chute mount. Place the assembly on top of the Interface big spacer with the 3 holes aligned with 3 of the heat inserts. Screw these together tightly with three {% include fastener.html size="M4" variant="countersunk" length="12" %} screws.

Rotate the Top interface chute mount 90 degrees relative to the Interface upper fixed section to reveal the 4th screw hole in the Lazy Susan (it should also line up with a hole in the Interface big spacer and a heat insert). Drive a fourth {% include fastener.html size="M4" variant="countersunk" length="12" %} screw tightly through this hole.

Once done, check that the chute rotates freely relative to the Interface upper fixed section.

{% include step.html n="8" title="Adjust the limit switch" %}

<figure class="video-figure">
  <div class="video-embed video-embed-wide">
    <iframe
      src="https://www.youtube.com/embed/FxpaGbyANHA?start=160&mute=1"
      title="Adjusting the limit switch"
      allow="encrypted-media; picture-in-picture; web-share"
      allowfullscreen
      loading="lazy"></iframe>
  </div>
  <figcaption><cite>Video: zed0.</cite></figcaption>
</figure>

Loosen the screws attaching the Limit switch housing to the extrusion. Slide the housing so the Limit switch hammer passes between the Roller lever limit switch and the Printed dowel pin in both directions of rotation, without touching the dowel pin. Rotate the chute slowly to each limit by hand: you should feel and hear the switch click just before the hammer would otherwise hit the dowel pin. If the hammer rubs against the dowel pin, slide the housing slightly further away and re-test. Tighten the screws to keep the housing in this position.

{% include step.html n="9" title="Install the chute stepper motor" %}

<figure class="video-figure">
  <div class="video-embed video-embed-wide">
    <iframe
      src="https://www.youtube.com/embed/z-L7_pNB8A8?mute=1"
      title="Installing the chute stepper motor"
      allow="encrypted-media; picture-in-picture; web-share"
      allowfullscreen
      loading="lazy"></iframe>
  </div>
  <figcaption><cite>Video: zed0.</cite></figcaption>
</figure>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>This video predates the idler gear's bearing retainer caps. It shows the idler gear built the old way, with a loose washer under the M3 × 35 screw instead of the two printed caps from step 1.</p>
</div>

The idler gear bridges the gap between the spur gear on the motor shaft and the chute's ring gear (built in step 6), so the motor can sit off to the side of the chute mount rather than driving it directly.

Slide the prepared [Timing pulley]({{ '/hardware/helpers/pulley-gear-mod/' | relative_url }}) over the shaft of the NEMA 23 stepper motor and tighten its two set screws (grub screws). Slide the Interface spur gear onto the Timing pulley and secure it with five {% include fastener.html size="M3" variant="countersunk" length="8" %} screws: three tapped into the Interface spur gear and two bracing against the Timing pulley (exact split may vary — check the hole pattern in the photo).

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-step9-timing-pulley-on-motor-w1600-0b0a8e04d17c.jpg" alt="Timing pulley installed on the shaft of a NEMA 23 stepper motor">
    <figcaption>Timing pulley installed on the NEMA 23 shaft. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-step9-interface-spur-gear-w1600-7dcec28e692a.jpg" alt="Grey Interface spur gear secured over the timing pulley with five countersunk screws">
    <figcaption>Interface spur gear secured over the Timing pulley with five M3 × 8 mm screws. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

Push the prepared Interface idler gear — bearing, inner retainer cap, and outer retainer already fitted, see step 1 — onto the Interface NEMA 23 bracket with the bearing facing outwards.

Drive an {% include fastener.html size="M3" variant="countersunk" length="20" %} screw through the middle of the gear and into the bracket. The inner retainer cap sits between the screw head and the bearing, spanning the 8 mm bore, so the screw head on its own (narrower than the bore) has something to clamp against. Tighten until it's seated, then check that the idler gear still spins freely.

The head has to be low here — countersunk (flat/pancake) is the only head type confirmed to clear the Limit switch hammer as it sweeps past. If you only have a pan head on hand, check clearance by hand-rotating the chute past this screw before closing everything up. The screw self-taps straight into the printed NEMA 23 bracket; it does not reach through to the plywood Top plate underneath, which is why 20 mm is enough.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-parts/img-4329-full-5511485c850a.jpg" alt="The Interface idler gear seated on the NEMA 23 bracket with an M3 countersunk screw driven flush through its centre">
    <figcaption>The M3 × 20 mm countersunk screw seated flush. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

Slot the NEMA 23 onto the Interface NEMA 23 bracket and secure it with four {% include fastener.html size="M5" variant="socket-button" length="12" %} screws.

At this point the chute should still rotate, but you will now feel resistance from the stepper motor. Rotate the chute fully in both directions by hand: it should turn smoothly against that resistance, with no catch or scrape as the idler screw head passes the Limit switch hammer.

<div class="img-row">
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-step9-idler-gear-no-motor-w1600-c46506452340.jpg" alt="The Interface idler gear tapped onto the NEMA 23 bracket, meshed with the chute's ring gear, before the stepper motor is fitted">
    <figcaption>The idler gear on the bracket, before the motor goes on. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
  <figure>
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-step9-idler-gear-nema23-meshed-w1600-15fd629cfae4.jpg" alt="The NEMA 23 stepper motor installed, its spur gear meshed with the idler gear and the chute's ring gear">
    <figcaption>The finished step: stepper, spur gear and idler all meshed. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

{% include step.html n="10" title="Attach the cable cage top" %}

<figure class="video-figure">
  <div class="video-embed video-embed-wide">
    <iframe
      src="https://www.youtube.com/embed/NUDDwb5BZH8?mute=1"
      title="Attaching the cable cage top"
      allow="encrypted-media; picture-in-picture; web-share"
      allowfullscreen
      loading="lazy"></iframe>
  </div>
  <figcaption><cite>Video: zed0.</cite></figcaption>
</figure>

Because the chute above rotates but the wiring below it doesn't, the ribbon cable has to flex through the full range of rotation without catching or fraying; the cable cage (top, bottom, and clamps) is a guided channel that lets it do that safely as the chute sweeps between its limit switches.

**Heat inserts first:** the Cable cage bracket (cable mount) takes 1 × M3 insert. Press it in before assembling.

Slot the Cable cage top over the Top interface chute mount, with the corners of the hexagon aligning with the Interface brackets.

Screw the Cable cage bracket (cable mount) to the tail end of the Interface bracket opposite the Limit switch housing, using an {% include fastener.html size="M5" variant="socket-button" length="30" %} screw into the M5 heat insert. This clamps the Cable cage top firmly in place. (Mounting it opposite the limit switch minimizes how far the cable has to travel.)

Screw the remaining Cable cage brackets to the other 5 corners of the Cable cage top with {% include fastener.html size="M5" variant="socket-button" length="30" %} screws.

{% include step.html n="11" title="Put the cable in the cable cage" %}

<figure class="video-figure">
  <div class="video-embed video-embed-wide">
    <iframe
      src="https://www.youtube.com/embed/aCNjETS1X9A?mute=1"
      title="Installing the cable in the cable cage"
      allow="encrypted-media; picture-in-picture; web-share"
      allowfullscreen
      loading="lazy"></iframe>
  </div>
  <figcaption><cite>Video: zed0.</cite></figcaption>
</figure>

Place an {% include fastener.html size="M3" variant="nut" %} into the bottom of the Cable clamp (outer) (the video skips this), then push it into the recess in the Top interface chute mount. Fasten it with two {% include fastener.html size="M3" variant="socket-button" length="10" %} screws.

Rotate the chute until it hits the limit switch.

Fold your IDC ribbon cable around the Cable clamp (inner), following the guides on the clamp. Slide the cable and clamp together into the Cable clamp (outer), leaving a significant tail to connect to the chute.

Guide the rest of the ribbon cable around the side of the Top interface chute mount, in the direction the chute can rotate, back to the Cable cage bracket (cable mount).

Screw the Ribbon cable clamp lightly to the Cable cage bracket (cable mount) with one {% include fastener.html size="M3" variant="socket-button" length="10" %} screw, clamping the ribbon cable between the two.

Check that the chute can rotate fully to the limit switch in both directions, then tighten the Ribbon cable clamp screw. Use a long {% include fastener.html size="M3" variant="flat" length="35" %} screw through the Cable clamp (inner) into the {% include fastener.html size="M3" variant="nut" %} in the bottom of the Cable clamp (outer) to secure that end.

{% include step.html n="12" title="Attach the cable cage bottom" %}

<figure class="video-figure">
  <div class="video-embed video-embed-wide">
    <iframe
      src="https://www.youtube.com/embed/CE3OKs5nXSk?mute=1"
      title="Attaching the cable cage bottom"
      allow="encrypted-media; picture-in-picture; web-share"
      allowfullscreen
      loading="lazy"></iframe>
  </div>
  <figcaption><cite>Video: zed0.</cite></figcaption>
</figure>

Place the Cable cage bottom over the Top interface chute mount. Use 6 {% include fastener.html size="M5" variant="flat" length="35" %} screws and {% include fastener.html size="M5" variant="nut" %}s to clamp the Cable cage bottom, Cable cage top, and Cable cage brackets together.

After this step the chute should still rotate to each of its limits.

{% include step.html n="13" title="Attach the framing" %}

Insert an extrusion piece F (Interface vertical support) into each of the Interface brackets. Hold each one in place with four {% include fastener.html size="M5" variant="socket-button" length="20" %} screws into four T-nuts.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p>Do not push piece F all the way through the bracket. Leave its end roughly 20 mm short of the far end of the channel: that is far enough in to cover both pairs of T-nut screws, and it leaves enough of the extrusion standing out to reach past the screws at the base of the layer's External bracket — side later in this step. <a href="{{ '/hardware/assembly/distribution/top-interface/' | relative_url }}#step-14">Step 14</a> shows the whole corner in section.</p>
</div>

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-framing-1-full-b8dacf182230.jpg" alt="Six vertical extrusion supports bolted into the interface brackets, seen from above on the hexagonal top plate">
  <figcaption><cite>Photo: zed0.</cite></figcaption>
</figure>

Slide an Interface spacer onto each piece of extrusion, with the lip at the top facing toward the center of the assembly.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-framing-2-w1600-f626512783f3.jpg" alt="An interface spacer slid onto each vertical extrusion support, lips facing inward">
  <figcaption><cite>Photo: zed0.</cite></figcaption>
</figure>

Build a [hex frame]({{ '/hardware/assembly/distribution/bin-frame/hex-frame/' | relative_url }}), then place it onto the interface assembly.

Roll 6 {% include fastener.html size="M5" variant="t-nut" text="T-nuts" %} into this hex frame's own extrusions while you are here, 2 each for the PSU box, the control board housing and the Orange Pi mount. All three bolt onto this frame later, and the layout render on [installing the electronics]({{ '/hardware/electronics/installation/' | relative_url }}) shows where each one sits. Their screws and the rest of their hardware are listed on those pages, not here.

<div class="callout">
  <p><b>No problem if you forget them.</b> The {% include fastener.html size="M5" variant="t-nut" text="T-nut" %} this build specifies is the spring-loaded roll-in kind, which drops into the slot anywhere along its length, so these six can still go in later without taking the frame apart.</p>
</div>

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-framing-3-full-b9ae16940954.jpg" alt="A hex frame lowered onto the interface assembly">
  <figcaption><cite>Photo: zed0.</cite></figcaption>
</figure>

Attach an External bracket cover to each of the External bracket sides, then fasten each one with 2 {% include fastener.html size="M5" variant="socket-button" length="16" %} screws into the holes at the base of the External bracket sides, bracing against the extrusion. These holes run parallel to the extrusion profile, and the screws are self-tapping. There is no External bracket — bottom vertical at this joint; see [step 14](#step-14) for what's different here.

{% include step.html n="14" title="How the interface joins the top layer" %}

<figure>
  <a href="https://assets.basically.website/sorter-docs/assembly-top-interface-framing-joint-full-ed0a06d244ff.png" target="_blank" rel="noopener">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-framing-joint-full-ed0a06d244ff.png" alt="The interface assembly upside down on its top plate with six vertical extrusions standing out of it, each held in an interface bracket and sleeved by an interface spacer">
  </a>
  <figcaption>The interface framing before the top layer goes on, with one arm marked 1 to 3. Click the photo to open it full size. <cite>Photo: zed0.</cite></figcaption>
</figure>

<figure class="figure-float-right">
  <a href="https://assets.basically.website/sorter-docs/assembly-top-interface-joint-section-full-e96f8eb4493c.png" target="_blank" rel="noopener">
    <img src="https://assets.basically.website/sorter-docs/assembly-top-interface-joint-section-full-e96f8eb4493c.png" alt="Vertical cross-section through one interface corner, showing the interface bracket and spacer in purple, piece F in grey running down into the top layer's bracket in blue">
  </a>
  <figcaption>The same corner in section, cut through the centre of the profile. Purple is the interface, blue the top layer's bracket, grey the extrusion. Click to enlarge. The interface parts are not exported in a shared frame with the layer parts, so the part lengths are measured but their heights come from seating each one on the part below it. <cite>Drawn from the part geometry rather than from a build, by Balloon.</cite></figcaption>
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

**Piece F does not reach the top of the Interface bracket, and it comes nowhere near the top plate.** How deep it goes is not stated anywhere in the build, but it is fixed at both ends by what has to be screwed: the lower end has to reach past the two screws at the base of the layer's bracket, and the upper end has to cover the bracket's second pair of T-nut screws, whose bosses sit about 90 mm above the bracket's underside. A 274 mm piece cannot do both and also reach the top of a 120 mm bracket, so it stands about 6 mm past the upper screws and stops roughly 23 mm short of the top of the bracket. That is what the drawing shows.

<div class="clear-float"></div>

The top interface is now complete.

<figure>
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-top-interface-framing-4-full-b9ae16940954.jpg" alt="The completed top interface: the hexagonal top plate on its framed leg structure with the chute opening in the centre">
  <figcaption>The finished interface, seen from above with the top plate on. <cite>Photo: zed0.</cite></figcaption>
</figure>
