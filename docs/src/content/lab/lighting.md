---
layout: default
title: How the cameras are lit
type: explanation
section: lab
slug: lab-lighting
kicker: Design and research, Lighting
lede: Each camera has its own lamp, built to give soft, even light and not a lot of bright light from one direction. This page covers the reflector, the LED strip and the cover, and why the light is arranged the way it is.
permalink: /lab/lighting/
audience: curious builder or contributor
applies_to: hardware-v2
owner: docs
last_verified: 2026-10-14
---

<div class="notice">
  <strong>Optional background</strong>
  <p>You do not need this page to build the lamps. The build pages are linked at the bottom.</p>
</div>

The machine looks at the pieces with three cameras, one over each of C2, C3 and the classification channel (C4). A camera does not need a lot of light as much as it needs light that is **even and soft**. The camera lamp is designed around that: an LED strip, a white reflector and a cover, all the same on every channel.

## How the light reaches the pieces

<ul class="bulleted-list">
  <li><strong>The LEDs do not point at the pieces.</strong> The LEDs shine inwards, towards the reflector, and not straight down. The light that reaches a piece has bounced off the white reflector first. Direct light is hard for a camera to expose properly, and the bounced light is easier for it.</li>
  <li><strong>The strip is at the outer edge.</strong> It runs two turns round the skirt of the reflector, away from the middle, which gives the LEDs extra distance.</li>
  <li><strong>A strip, for a lot of light spread evenly.</strong> That was the aim of the design. The strip is a 24 V, 8 mm wide, 6000 K daylight white strip, and one 5 m roll is cut into the strips for all three lamps.</li>
  <li><strong>The reflector is white, and has to be.</strong> The reflector and its six LED hooks print white because a coloured one would tint the light, and so every picture the camera takes. The parts calculator marks those two parts as the ones whose colour matters.</li>
</ul>

## The cover

The cover goes over the reflector and the strip. It is grey on the outside, and the inside of the lamp stays white (the reflector). The cover is there because, without it, the infill inside the printed walls of the reflector can be seen through the walls ([the designer's answer, October 2026](https://discord.com/channels/1430279849171222682/1430279852015091804/1559738169296166949)). It is a matter of looks and has no part in how the light is spread, which is why the build pages let the cover be any colour and ask for white only on the reflector and the hooks.

## The same lamp on every channel

All three lamps are the same, so the three cameras get the same light. Two things follow, from the <a href="https://www.youtube.com/watch?v=fnBvE-yFbLc">30 August 2026 meeting</a>:

<ul class="bulleted-list">
  <li>The cameras can all expose in the same way.</li>
  <li>If some light from one lamp falls on the next channel, it does not change how the camera there exposes, because the light on every channel is already the same.</li>
</ul>

The same meeting reports that the whole scene is even, with no dark spots anywhere in it. The lamp took the place of the large white dome and the earlier light posts, see <a href="{{ '/lab/sorter/' | relative_url }}">How the sorter is put together</a>.

## What the light needs for good colour

Higher colour rendering strips and LED rings have been suggested in the Discord, because colour recognition depends on the light. The designer's answer ([October 2026](https://discord.com/channels/1430279849171222682/1430279852015091804/1560031742281392262)) is that colour is being given too much weight. Colour has looked right on every setup where three things were true:

<ul class="bulleted-list">
  <li>the light was roughly daylight coloured;</li>
  <li>the white balance of the camera was close to correct;</li>
  <li>and, above all, the light was even and soft.</li>
</ul>

The strips were kept because they spread a lot of light evenly. The strip in the parts catalog is claimed by its seller to have a colour rendering index (CRI) of 95 or more, and the machine sets no minimum CRI.

## What the camera looks at

The light also falls on the channel, so the colour of the channel matters too. The stator, both rotors and the rotor cap are marked in the parts calculator as grey, because the cameras look at them. A white rotor is a suspect when a camera underexposes, as it did on one machine ([October 2026](https://discord.com/channels/1430279849171222682/1430279852015091804/1559291261276397699), a suspicion, not a confirmed cause).

## Where to find it

<ul class="bulleted-list">
  <li>Building the lamps: <a href="{{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}">Camera lamps</a> and <a href="{{ '/hardware/assembly/feeder/camera-lamp/lamp-arm/' | relative_url }}">Lamp arm</a></li>
  <li>The strip and its cables: <a href="{{ '/hardware/helpers/led-strip/' | relative_url }}">Preparing the LED strips</a></li>
  <li>The strip and the lamp parts, with their colours: <a href="https://github.com/basicallysource/sorter-v2/blob/main/parts-calculator/catalog/parts.json"><code>parts-calculator/catalog/parts.json</code></a></li>
</ul>
