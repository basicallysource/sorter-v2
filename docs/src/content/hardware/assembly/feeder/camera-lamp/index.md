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

## The finished result

Each page ends in one of these.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/camera-lamp-render-underside-full-0e2b1e5a0fb9.png" alt="CAD render of the camera lamp seen from below: the inside of the cover with the reflector dome, the LED hooks spaced around the rim, the camera at the centre, and the arm reaching up into it">
    <figcaption><a href="{{ '/hardware/assembly/feeder/camera-lamp/lamp-arm/' | relative_url }}">Lamp arm</a>, from below. <cite>Rendered from the part geometry, not from a build. Render: Spencer.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/camera-lamp-on-channel-w1600-8d957377d671.jpg" alt="A camera lamp on the machine: a grey disc-shaped lamp on an angled arm hanging over the open top of a C-channel, the white reflector lit inside it, with the black bulk bucket behind">
    <figcaption><a href="{{ '/hardware/assembly/feeder/camera-lamp/feeder-camera-lamp/' | relative_url }}">Feeder camera lamp</a>, over its channel. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/camera-lamp-camera-seated-w1600-eede61656118.jpg" alt="Looking down on a camera seated at the centre of a lamp, its lens in the middle of the white reflector">
    <figcaption><a href="{{ '/hardware/assembly/feeder/camera-lamp/classification-camera-lamp/' | relative_url }}">Classification camera lamp</a>, camera seated. <cite>Photo: Spencer.</cite></figcaption>
  </figure>
</div>

Each lamp's strip is plugged into the board on [connecting the components]({{ '/hardware/electronics/installation/connecting/' | relative_url }}), and the camera is on the [electronics]({{ '/hardware/electronics/' | relative_url }}) page. See [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}) for how the channels themselves sit together.
