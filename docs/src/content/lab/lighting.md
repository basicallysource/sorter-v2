---
layout: default
title: How the cameras are lit
type: explanation
section: lab
slug: lab-lighting
kicker: Design and research, Lighting
lede: Each camera has its own lamp. This page explains why the light is soft and even, and what the cover and the LED strip are for.
permalink: /lab/lighting/
audience: curious builder or contributor
applies_to: hardware-v2
owner: docs
last_verified: 2026-10-15
---

The camera lamp is designed to give **even, soft light**, because direct light is hard for a camera to expose properly. How to build the lamps is on <a href="{{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}">Camera lamps</a>.

## How the light reaches the pieces

<ul class="bulleted-list">
  <li><strong>The LEDs shine at the reflector, not at the pieces.</strong> The strip is turned inwards, so its light bounces off the white reflector first. That makes it softer.</li>
  <li><strong>The strip is at the outer edge.</strong> It runs two turns round the edge of the reflector, away from the middle, so the LEDs are further from the pieces.</li>
  <li><strong>The aim was a lot of light, spread evenly.</strong> That is why the lamp uses an LED strip.</li>
</ul>

The same lamp is on all three channels, so each camera gets the same light. Two things follow, from the <a href="https://www.youtube.com/watch?v=fnBvE-yFbLc">30 August 2026 meeting</a>. The cameras all set their brightness in the same way. And light that falls on the next channel does not change that, because the light there is the same anyway. The meeting also reports no dark spots anywhere in the picture.

## The cover

The cover is there for looks. Without it, you can see the infill (the inside of the printed walls) through the walls of the reflector ([October 2026](https://discord.com/channels/1430279849171222682/1430279852015091804/1559738169296166949)). It does nothing to the light.

## Colour

Some people have asked whether a strip with better colour rendering (how true colours look under the light), or an LED ring, would give better colours. The answer ([October 2026](https://discord.com/channels/1430279849171222682/1430279852015091804/1560031742281392262)) is that colour is getting too much attention. Colour has looked right on every setup where three things were true:

<ul class="bulleted-list">
  <li>the light was about the colour of daylight;</li>
  <li>the camera's white balance (how it sets what counts as white) was close to correct;</li>
  <li>and, most important, the light was even and soft.</li>
</ul>

The seller says the strip has a colour rendering index (CRI) of 95 or more. The machine sets no minimum.

## Where to find it

<ul class="bulleted-list">
  <li>Building the lamps: <a href="{{ '/hardware/assembly/feeder/camera-lamp/lamp-arm/' | relative_url }}">Lamp arm</a></li>
  <li>The strip and its cables: <a href="{{ '/hardware/helpers/led-strip/' | relative_url }}">Preparing the LED strips</a></li>
</ul>
