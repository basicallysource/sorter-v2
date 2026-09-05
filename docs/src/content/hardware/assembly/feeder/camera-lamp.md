---
layout: default
title: Camera lamp
type: how-to
section: hardware
slug: assembly-camera-lamp
kicker: Feeder — Camera lamp
lede: The arm, the shaded lamp and the camera that hang over a C-channel.
permalink: /hardware/assembly/feeder/camera-lamp/
author: reveryx
contributors: [spencer]
og_image: https://assets.basically.website/sorter-docs/camera-lamp-on-channel-w1600-8d957377d671.jpg
warning: >-
  **AI-generated first draft, and the order of operations is a guess.** The parts, the
  joints and Spencer's photographs are real, from the [parts
  calculator](https://parts-calculator.basically.website/assembly?focus=camera-lamp); every
  hole diameter and screw count below is measured off the published STLs, and the 12 screws
  into 6 holes in Steps 2 and 3 are confirmed by ReveryX, who has the parts. What is missing
  is a build: nobody has written down how the arm mount attaches to the C-channel, which LED
  strip goes on the hooks, or how any of it is wired. Fill those in as you build.
parts_needed:
  - part: c-channel-arm-mount
    qty: 1
  - part: camera-lamp-arm
    qty: 1
  - part: arm-bracket-a
    qty: 1
  - part: arm-bracket-b
    qty: 1
  - part: camera-lamp-ring
    qty: 1
  - part: camera-clasp-bottom
    qty: 1
  - part: camera-clasp-top
    qty: 1
  - part: cam-ov9732
    qty: 1
  - part: lamp-inner-reflector
    qty: 1
  - part: inner-reflector-led-hook
    qty: 6
  - part: lamp-outer-cover
    qty: 1
  - part: scr-m3-12-cs
    qty: 12
  - part: scr-m3-8-cs
    qty: 2
---

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Build a <a href="{{ '/hardware/assembly/feeder/c-channel/' | relative_url }}">C-channel</a> before you start.</strong> The lamp hangs over one, on an arm that mounts to it. This page builds the lamp, not the channel.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/assembly-c-channel-stator-and-rotor-fitted-w1600-60758bbee2d5.jpg" alt="A finished C-channel seen from above: the white finned classification rotor sitting inside the grey stator ring, with the stepper motor projecting from the right-hand side">
    <figcaption>A finished C-channel, from the C-channel page. <cite>Photo: BrickCycleAlice.</cite></figcaption>
  </figure>
</div>

The camera lamp is one arm carrying one light and one camera over a channel. The light is a ring of LED strip inside a white reflector, under a grey cover, so what reaches the parts is bounced rather than aimed straight at them, and the camera looks straight down through the hole in the middle of the reflector.

It replaces the [light post]({{ '/hardware/assembly/feeder/light-post/' | relative_url }}) and the [overhead camera mount]({{ '/hardware/assembly/feeder/camera-mount/' | relative_url }}), which were the previous side-light-plus-rod-arm arrangement and are retired.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-on-channel-w1600-8d957377d671.jpg" alt="A camera lamp on the machine: a grey disc-shaped lamp on an angled arm hanging over the open top of a C-channel, the white reflector lit inside it, with the black bulk bucket behind">
  <figcaption>The finished thing, over a channel, lit. <cite>Photo: Spencer.</cite></figcaption>
</figure>

**The parts list above is one lamp's worth.** The catalog gives one to each of the four channels, so a machine takes four of everything on it: C1, C2 and C3 with the OV9732, and the classification channel with the [IMX415]({{ '/hardware/assembly/feeder/classification-chamber/' | relative_url }}) 4K module instead. Everything else is identical between the four.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Whether C1 really takes a camera is an open question.</b> The parts list gives C1 a full lamp including an OV9732, but the software has no C1 camera role at all: the crop zones are the second channel, the third channel and the classification channel, and nothing reads vision off the bulk channel. The lamp itself is not in doubt on any channel. If you are buying rather than printing, the third OV9732 is the one to hold off on (raised by BrickCycleAlice, 2026-09-05, unanswered).</p>
</div>

{% include fastener-legend.html %}

{% include step.html n="1" title="Preparation" %}

**No heat inserts anywhere on this assembly.** Every screw is self-tapping into printed plastic. Measured across all seven printed parts, the holes come in exactly two sizes: 2.8 mm, which is the thread-forming pilot, and 3.5 mm, which is clearance for a screw on its way into one of those pilots. There is nothing in the 4.2 mm range an insert would need.

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Colours.</strong> The <strong>Lamp inner reflector</strong> and its six <strong>LED hooks</strong> print ivory white, and that is not cosmetic: they are the reflector. The <strong>Lamp outer cover</strong> is ash grey. The arm, the mount, both brackets, the ring and both clasp halves follow the channel colour like the rest of that channel's parts.</p>
  </div>
  <figure class="prep-item-figure">
    <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-render-side-full-2a681306f3a9.png" alt="CAD render of the camera lamp in profile: the disc-shaped lamp overhanging at the top, carried on an arm that steps down at an angle to the C-channel arm mount, with a bracket along each joint">
    <figcaption>The whole thing in profile. <cite>Rendered from the part geometry, not from a build. Render: Spencer.</cite></figcaption>
  </figure>
</div>

<div class="prep-item">
  <div class="prep-item-body">
    <p><strong>Print counts, if you are printing for the whole machine:</strong> 4 each of the mount, arm, bracket A, bracket B, ring, both clasp halves, reflector and cover, and <strong>24</strong> LED hooks, six per lamp. The hooks are the ones people come up short on.</p>
  </div>
  <figure class="prep-item-figure">
    <div class="img-placeholder">Image coming</div>
  </figure>
</div>

{% include step.html n="2" title="Bracket the arm to the C-channel arm mount" %}

The arm and the mount butt together end to end, and brackets A and B hold the joint, one on each face. Each bracket has four 3.5 mm clearance holes in a 4.5 mm plate, two over the mount and two over the arm.

**The two brackets share their screw holes.** The mount and the arm each carry two 2.8 mm pilot holes that run 19.8 mm straight through the joint, so bracket A's screw enters one end and bracket B's the other, and eight screws go into four holes. Both pairs are 20 mm apart along the joint.

Drive all 8 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws, four per bracket, seated flush in the countersinks. Stop as soon as each head seats: you are cutting a thread in plastic, and the far half of the hole is somebody else's screw.

**12 mm is the length, and it is the only one that fits.** A countersunk screw's length is measured over its head, so 12 mm through a 4.5 mm bracket leaves about 7.5 mm of thread in the 19.8 mm hole and two screws coming from opposite ends stop roughly 5 mm short of each other. A 16 would put 11.5 mm in from each end, 23 mm of screw in a 19.8 mm hole, and the two would meet before either seated. ReveryX confirmed the M3 × 12 on an assembled arm, 2026-09-05.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-mounted-wide-w1600-247fb837f4f8.jpg" alt="A wider view of a camera lamp on the machine, showing the full length of the arm from the lamp down to the C-channel, with a bracket screwed along the joint and the LED leads cable-tied along the arm">
  <figcaption>The arm on the machine, bracket along the joint, leads running down it. <cite>Photo: Spencer.</cite></figcaption>
</figure>

{% include step.html n="3" title="Screw the camera lamp ring onto the arm" %}

The ring goes on the far end of the arm and is what the lamp and the camera hang from. It works the same way as the joint below it: four 3.5 mm clearance holes in the ring, two 2.8 mm pilot holes through the end of the arm, so the remaining 4 {% include fastener.html size="M3" variant="countersunk" length="12" %} screws go two per side into the same two holes. The ring straddles the arm.

That is all 12 of the M3 × 12 in the parts list: 8 at the mount joint, 4 here. **Six holes, a screw into each end of every one of them.** ReveryX confirmed that count against the parts on 2026-09-05; everything else about these two steps is off the STLs.

{% include step.html n="4" title="Clasp the camera between the two halves" %}

The camera board is held between the **Camera clasp bottom** and the **Camera clasp top**, which are both 6 mm plates that meet face to face with the board between them.

The two {% include fastener.html size="M3" variant="countersunk" length="8" %} screws go **up through the bottom half into the top half**: 3.5 mm clearance with a countersink on the underside of the bottom, 2.8 mm pilot 5 mm deep in the top. The two positions are on a diagonal, 43.2 mm apart.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Two screws, not four, and the length is the one thing here still worth checking.</b> The parts calculator lists 4 × M3 × 8 and flags the count as unconfirmed; there are only two screw positions in either STL. On the lengths: the bottom half is 6 mm thick, so an M3 × 8 countersunk reaches about 2 mm into the top half's 5 mm pilot, and an M3 × 10 would give 4 mm and still stop 2 mm short of the top face. Nobody has confirmed either against a build. Do not overtighten, and check the halves close flush on the board.</p>
</div>

The clasp is what carries the camera into the lamp: its two halves form a 4 mm spigot on the diagonal, which plugs into a 4.2 mm socket in the camera lamp ring. The ring has two of those sockets at the same radius; which one is intended, and whether the module is meant to come out again, is not recorded. <span class="fastener-todo">fastener not recorded</span>

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-camera-seated-w1600-eede61656118.jpg" alt="Looking down on the top of an assembled camera lamp: the grey cover with a circular opening at its centre, the camera board seated in the clasp inside it, its lead plugged in and running off to one side">
  <figcaption>The camera sits at the centre of the lamp, looking straight down through the reflector. <cite>Photo: Spencer.</cite></figcaption>
</figure>

{% include step.html n="5" title="Hook the LED strip onto the reflector" %}

Six **Inner reflector LED hooks** friction-fit into the rim of the **Lamp inner reflector**, evenly spaced 60° apart, one per 2.7 mm socket around its outside. Each hook retains the LED strip against the reflector. No screws.

**Not recorded:** which LED strip, how much of it, how it is joined and how it is wired back to the board. None of that is in the catalog yet, and the strip is not a part in the machine's list. What the photograph shows is strip run in a ring around the inside of the reflector, retained by the hooks, with the leads coming out and down the arm.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-lit-from-below-w1600-bb9d54f4f43e.jpg" alt="The lamp lit, photographed from underneath: a ring of LED strip glowing around the outside of the white reflector, the reflector's central funnel in the middle, and the arm behind it">
  <figcaption>Lit, from below. The strip rings the reflector and the light reaches the parts off the white. <cite>Photo: Spencer.</cite></figcaption>
</figure>

{% include step.html n="6" title="Cover the reflector" %}

The **Lamp outer cover** friction-fits down over the reflector, and that is the whole joint: it has no screw hole anywhere in its geometry. The reflector is 150 mm across, the cover 153 mm, and the cover stands about 1.5 mm proud of the reflector at the top so the camera clasp sits recessed in the opening at its centre.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-render-underside-full-0e2b1e5a0fb9.png" alt="CAD render of the camera lamp seen from below: the inside of the cover with the reflector dome, the LED hooks spaced around the rim, the camera at the centre, and the arm reaching up into it">
  <figcaption>From below, with the reflector inside the cover and the hooks around the rim. <cite>Rendered from the part geometry, not from a build. Render: Spencer.</cite></figcaption>
</figure>

{% include step.html n="7" title="Bring the three together" %}

Plug the clasped camera into the ring, then set the lamp on top. **The lamp is not fastened to the arm at all.** It sits on it under its own weight, which is how it is recorded and how it comes apart again for a print change.

Order matters here in one place only: the camera has to be in the clasp and the clasp in the ring before the cover goes over the top, because the cover closes around the clasp.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-render-top-full-edc4616e7088.png" alt="CAD render of the assembled camera lamp from above: the grey cover with the camera clasp and board in the central opening, a slot near the rim, and the arm coming in from the lower left">
  <figcaption>Assembled, from above. <cite>Rendered from the part geometry, not from a build. Render: Spencer.</cite></figcaption>
</figure>

{% include step.html n="8" title="Mount the arm on the C-channel" %}

**Not recorded, and not in the CAD either.** The C-channel arm mount carries exactly two holes, the pair the brackets use, and nothing that would fasten it to a channel, so how it is held there is a real gap rather than a missing sentence. The mount is 83 mm long and stands off the channel wall; the photographs show it against the outside of the channel with the arm rising over the rim. <span class="fastener-todo">fastener not recorded</span>

Write down what you did, and where the lamp ended up relative to the channel: height and overhang both change what the camera sees, and the [camera calibration]({{ '/sorter/camera-calibration/' | relative_url }}) step afterwards is software, not a way to fix a lamp in the wrong place.

Wiring, for both the LED strip and the camera, is on the [electronics]({{ '/hardware/electronics/' | relative_url }}) page. Build the other three lamps the same way, and see [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}) for how the channels themselves sit together.
