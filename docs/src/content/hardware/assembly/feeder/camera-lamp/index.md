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
og_image: https://assets.basically.website/sorter-docs/camera-lamp-render-underside-full-0e2b1e5a0fb9.png
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

A lamp is built on the bench and hangs onto its channel at [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}), once the four channels are standing at their heights.

## The finished result

Each page ends in one of these.

<div class="img-row">
  <figure>
    <img src="https://assets.basically.website/sorter-docs/camera-lamp-render-underside-full-0e2b1e5a0fb9.png" alt="CAD render of the camera lamp seen from below: the inside of the cover with the reflector dome, the LED hooks spaced around the rim, the camera at the centre, and the arm reaching up into it">
    <figcaption><a href="{{ '/hardware/assembly/feeder/camera-lamp/lamp-arm/' | relative_url }}">Lamp arm</a>, from below. <cite>Rendered from the part geometry, not from a build. Render: Spencer.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-ov9732-lead-routing-w1600-e5c818271b94.jpg" alt="The lamp on channel 3 from a low angle: the camera board in the cover's opening, the red and black lamp leads cable-tied to the arm, and the rectangular slot in the cover below the board">
    <figcaption><a href="{{ '/hardware/assembly/feeder/camera-lamp/feeder-camera-lamp/' | relative_url }}">Feeder camera lamp</a>, on C3 with its leads tied down the arm. <cite>Photo: Daddy-O's Bricks - Bill.</cite></figcaption>
  </figure>
  <figure>
    <img src="https://assets.basically.website/sorter-docs/assembly-camera-lamp-imx415-lead-routing-w1600-ff6852248c3f.jpg" alt="The classification lamp, marked 4, from a lower angle: the camera cable standing up out of the board, the red and black lamp leads looped over the cover and cable-tied clear of it, and the rectangular slot in the cover below">
    <figcaption><a href="{{ '/hardware/assembly/feeder/camera-lamp/classification-camera-lamp/' | relative_url }}">Classification camera lamp</a>, on C4 with its cable standing up out of the board. <cite>Photo: Daddy-O's Bricks - Bill.</cite></figcaption>
  </figure>
</div>

Each lamp's strip is plugged into the board on [connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}), and the camera is on the [electronics]({{ '/hardware/electronics/' | relative_url }}) page. See [arranging C-channels]({{ '/hardware/assembly/feeder/arranging-c-channels/' | relative_url }}) for how the channels themselves sit together.
