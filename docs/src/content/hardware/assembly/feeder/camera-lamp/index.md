---
layout: default
title: Camera lamps
type: landing
section: hardware
slug: assembly-camera-lamps
kicker: Feeder — Camera lamps
lede: The arm, the shaded lamp and the camera that hang over C2, C3 and the classification channel. One lamp arm, built three times, finished with the camera its channel needs.
permalink: /hardware/assembly/feeder/camera-lamp/
author: reveryx
contributors: [spencer, danny, brickcyclealice, barthel]
og_image: https://assets.basically.website/sorter-docs/camera-lamp-on-channel-w1600-8d957377d671.jpg
---

A camera lamp is one arm carrying one light and one camera over a channel. The light is a ring of LED strip inside a white reflector, under a grey cover, so the light reaches a part bounced off the white rather than aimed straight at it. The camera looks down through the hole in the middle of the reflector.

**All three lamps are built on the same arm.** Build the [lamp arm]({{ '/hardware/assembly/feeder/camera-lamp/lamp-arm/' | relative_url }}) three times, then finish each one with the camera module its channel needs. The camera and its clasp are the only difference between the three.

<ol class="numbered-steps">
  <li><strong><a href="{{ '/hardware/assembly/feeder/camera-lamp/lamp-arm/' | relative_url }}">Lamp arm</a></strong>. The arm and the ring it carries, the reflector with its ring of LED strip, and the cover that goes over the top. Build three.</li>
  <li><strong><a href="{{ '/hardware/assembly/feeder/camera-lamp/feeder-camera-lamp/' | relative_url }}">Feeder camera lamp (C2 and C3)</a></strong>. A lamp arm finished with the OV9732 720p module in its clasp. Build two.</li>
  <li><strong><a href="{{ '/hardware/assembly/feeder/camera-lamp/classification-camera-lamp/' | relative_url }}">Classification camera lamp (C4)</a></strong>. A lamp arm finished with the IMX415 4K module in its clasp. Build one.</li>
</ol>

**The bulk channel (C1) takes none**, because the machine does not look at it.

<div class="callout">
  <p><b>If you printed four sets, one is spare.</b> The parts list gave C1 a lamp of its own until 2026-09-08. It takes none.</p>
</div>

Build the lamps before the channels that carry them: two of the [C-channels]({{ '/hardware/assembly/feeder/c-channels/' | relative_url }}) pages need one to start. A lamp is built on the bench and hangs onto its channel later, once the channels are standing.

It replaces the light post and the overhead camera mount, the side-light-plus-rod-arm arrangement used before 2026-09-02. Both are retired and no longer documented.

## The finished result

Both camera pages end in one of these: an arm, a lamp and a camera over a channel, lit.

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/camera-lamp-on-channel-w1600-8d957377d671.jpg" alt="A camera lamp on the machine: a grey disc-shaped lamp on an angled arm hanging over the open top of a C-channel, the white reflector lit inside it, with the black bulk bucket behind">
  <figcaption>A finished lamp over its channel, lit. <cite>Photo: Spencer.</cite></figcaption>
</figure>

The strip is cut and wired on [Preparing the LED strip]({{ '/hardware/helpers/led-strip/' | relative_url }}), one per lamp before the arm is built. Wiring it back to the board is [Make your own LED drop]({{ '/hardware/electronics/led-drop/' | relative_url }}), and the camera is on the [electronics]({{ '/hardware/electronics/' | relative_url }}) page. See [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}) for how the channels themselves sit together.
