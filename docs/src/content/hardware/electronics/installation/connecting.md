---
layout: default
title: Connecting the components
type: how-to
section: hardware
slug: electronics-connecting
kicker: Electronics — Connecting the components
lede: Every cable between the PSU, the control board and the Orange Pi, and the socket each end goes into.
permalink: /hardware/electronics/installation/connecting/
author: daddyosbricksbill
contributors: [spencer, effreek]
warning: >-
  **AI-generated first draft.** Written from the basically board v1.3 board files and the [wire
  harness]({{ '/hardware/electronics/' | relative_url }}) schedule, not from an actual build. The
  sockets and the pinouts are read from the board itself and are real. The order of the steps is
  not checked against a machine. One step involves mains voltage: read the page fully before you
  start.
parts_needed:
  - part: usb-hub-powered-24v
    qty: 1
  - part: buck-24v-5v-usbc
    qty: 1
  - part: cable-micro-usb
    qty: 1
  - part: cable-idc-2x8-long
    qty: 1
  - part: cable-idc-2x8-short
tools_needed: [Multimeter, Side cutters or a small screwdriver]
---

The [PSU box]({{ '/hardware/electronics/installation/psu-box/' | relative_url }}), the [control board housing]({{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}) and the [Orange Pi mount]({{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}) are all bolted to the frame, and every cable is already made. This page plugs them together. Nothing here needs a soldering iron.

If a cable is still missing, [make your own PSU pigtail]({{ '/hardware/electronics/psu-pigtail/' | relative_url }}) and [make your own LED drop]({{ '/hardware/electronics/led-drop/' | relative_url }}) build two of them, and the [wire harness]({{ '/hardware/electronics/' | relative_url }}) page has the length and gauge of the rest.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Keep the machine unplugged from the wall until the last step.</b> Screws 1, 2 and 3 inside the PSU box are live mains whenever it is plugged in. The PSU box stays closed from here on, so you never touch them on this page.</p>
</div>

## Every cable on this page

<table>
  <thead><tr><th>Cable</th><th>From, and its connector</th><th>To, and its connector</th></tr></thead>
  <tbody>
    <tr><td>24 V, control board</td><td>PSU box jack, male DC barrel</td><td>Board <code>J1</code>, JST-VH 2-pin</td></tr>
    <tr><td>24 V, USB hub</td><td>PSU box jack, male DC barrel</td><td>Hub DC input, male DC barrel</td></tr>
    <tr><td>24 V, Orange Pi</td><td>PSU box jack, male DC barrel</td><td>Buck converter, then USB-C into <code>PWR IN</code></td></tr>
    <tr><td>Rotor steppers (×4)</td><td>Board <code>J27</code> / <code>J31</code> / <code>J35</code> / <code>J39</code>, JST-PH 4-pin</td><td>The motor's own JST-PH 6-pin socket</td></tr>
    <tr><td>Chute stepper</td><td>Board <code>J24</code>, 4-pin Dupont on 2.54 mm pins</td><td>The motor's flying leads, crimped into the housing</td></tr>
    <tr><td>Chute limit switch</td><td>Board <code>J5</code>, 3-pin Dupont, 2 positions used</td><td>Two #187 push-on tabs on the switch</td></tr>
    <tr><td>Camera lamps (×3)</td><td>Board <code>J8</code> / <code>J9</code> / <code>J10</code>, 2-pin Dupont</td><td>Clamp-on connector on the LED strip</td></tr>
    <tr><td>Ribbon to the layers</td><td>Board <code>J17</code>, 16-pin IDC</td><td><code>J3</code> on the first layer board, 16-pin IDC</td></tr>
    <tr><td>Pico to hub</td><td>Micro USB on the Pico</td><td>USB-A on the hub</td></tr>
    <tr><td>Hub to Orange Pi</td><td>USB-A on the hub</td><td><code>UP USB3.0</code> on the Pi</td></tr>
    <tr><td>Cameras (×3)</td><td>The camera's own USB lead</td><td>USB-A on the hub</td></tr>
  </tbody>
</table>

The [wire harness]({{ '/hardware/electronics/' | relative_url }}) page calls the first three `W1`, `W2` and `W3`, the steppers `S1` to `S4` and `CH`, the lamps `L1` to `L3`, and the ribbon `RIB`.

## The control board, socket by socket

Everything in steps 2 to 6 plugs into this board. It is drawn from above, the way you look at it once the housing is open.

<figure class="harness-figure">
  <div class="diagram diagram-wide">
    <svg viewBox="0 0 930 660" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Top view of basically board v1.3 with every socket a cable plugs into labelled: the 24 V input J1, the four LED ports J8 to J11, the two switch headers J5 and J6, the five stepper outputs J23, J27, J31, J35 and J39, and the 16-pin ribbon header J17">
      <rect x="170.0" y="80.0" width="546.0" height="504.0" rx="21.0" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.5"/>
      <rect x="573.2" y="117.8" width="75.6" height="92.4" rx="3" fill="var(--bg)" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 3"/>
      <text x="611.0" y="168.0" font-size="10" text-anchor="middle" fill="var(--muted)">TMC2209</text>
      <rect x="573.2" y="220.3" width="75.6" height="92.4" rx="3" fill="var(--bg)" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 3"/>
      <text x="611.0" y="270.5" font-size="10" text-anchor="middle" fill="var(--muted)">TMC2209</text>
      <rect x="573.2" y="323.2" width="75.6" height="92.4" rx="3" fill="var(--bg)" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 3"/>
      <text x="611.0" y="373.4" font-size="10" text-anchor="middle" fill="var(--muted)">TMC2209</text>
      <rect x="573.2" y="426.1" width="75.6" height="92.4" rx="3" fill="var(--bg)" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 3"/>
      <text x="611.0" y="476.3" font-size="10" text-anchor="middle" fill="var(--muted)">TMC2209</text>
      <rect x="237.2" y="239.6" width="75.6" height="92.4" rx="3" fill="var(--bg)" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 3"/>
      <text x="275.0" y="289.8" font-size="10" text-anchor="middle" fill="var(--muted)">TMC2209</text>
      <rect x="376.6" y="81.7" width="88.2" height="222.6" rx="3" fill="var(--bg)" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 3"/>
      <text x="420.7" y="185.0" font-size="11" text-anchor="middle" fill="var(--muted)">Pico</text>
      <rect x="403.9" y="302.6" width="33.6" height="14.7" rx="1" fill="var(--surface)" stroke="var(--ink)" stroke-width="1"/>
      <text x="420.7" y="336.2" font-size="10" text-anchor="middle" fill="var(--ink)">micro USB</text>
      <rect x="236.8" y="92.2" width="11.3" height="32.3" rx="2" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <rect x="299.8" y="92.2" width="11.3" height="32.3" rx="2" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <path d="M242.2 92.2 L242.2 46" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="236.2" y="30" font-size="12" font-weight="700" text-anchor="end" fill="var(--ink)">J5 · HALL_SW_0</text>
      <text x="236.2" y="45" font-size="11" font-weight="400" text-anchor="end" fill="var(--muted)">chute limit switch</text>
      <path d="M305.5 92.2 L305.5 46" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="311.5" y="30" font-size="12" font-weight="700" text-anchor="start" fill="var(--ink)">J6 · HALL_SW_1</text>
      <text x="311.5" y="45" font-size="11" font-weight="400" text-anchor="start" fill="var(--muted)">second switch input, spare</text>
      <rect x="192.0" y="162.7" width="10.9" height="21.8" rx="2" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <rect x="191.8" y="207.9" width="10.9" height="21.8" rx="2" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <rect x="282.1" y="161.6" width="10.9" height="21.8" rx="2" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <rect x="281.1" y="207.3" width="10.9" height="21.8" rx="2" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <path d="M191.8 173.7 L160 173.7" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <path d="M191.8 218.6 L160 218.6" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="154" y="159.8" font-size="12" font-weight="700" text-anchor="end" fill="var(--ink)">J8 · LED_0_1</text>
      <text x="154" y="174.8" font-size="12" font-weight="700" text-anchor="end" fill="var(--ink)">J9 · LED_0_2</text>
      <text x="154" y="189.8" font-size="11" font-weight="400" text-anchor="end" fill="var(--muted)">both switched by GPIO 1</text>
      <path d="M282.1 172.4 L254.0 172.4 L254.0 252.2 L160 252.2" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <path d="M282.1 218.2 L266.6 218.2 L266.6 264.8 L160 264.8" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="154" y="243.8" font-size="12" font-weight="700" text-anchor="end" fill="var(--ink)">J10 · LED_1_1</text>
      <text x="154" y="258.8" font-size="12" font-weight="700" text-anchor="end" fill="var(--ink)">J11 · LED_1_2</text>
      <text x="154" y="273.8" font-size="11" font-weight="400" text-anchor="end" fill="var(--muted)">both switched by GPIO 6</text>
      <rect x="178.4" y="295.0" width="10.5" height="36.1" rx="2" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <rect x="202.8" y="266.5" width="10.5" height="36.1" rx="2" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <path d="M178.4 311.0 L160 311.0" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="154" y="311.0" font-size="12" font-weight="700" text-anchor="end" fill="var(--ink)">J39 / J40</text>
      <text x="154" y="326.0" font-size="11" font-weight="400" text-anchor="end" fill="var(--muted)">C-channel 2 rotor</text>
      <rect x="246.0" y="550.4" width="85.3" height="21.4" rx="2" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <path d="M287.6 571.8 L287.6 605.0" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="287.6" y="634.4" font-size="12" font-weight="700" text-anchor="middle" fill="var(--ink)">J17 · 16-pin ribbon</text>
      <text x="287.6" y="649.4" font-size="11" font-weight="400" text-anchor="middle" fill="var(--muted)">down to the layer boards</text>
      <rect x="317.0" y="490.8" width="63.0" height="10.5" rx="2" fill="var(--bg)" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 3"/>
      <text x="346.4" y="479.0" font-size="10" text-anchor="middle" fill="var(--muted)">J12 · unused PWM</text>
      <rect x="566.5" y="518.5" width="16.8" height="33.6" rx="2" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <path d="M583.3 535.3 L653.0 535.3" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="661.4" y="512.6" font-size="12" font-weight="700" text-anchor="start" fill="var(--ink)">J1 · 24 V in</text>
      <text x="661.4" y="527.6" font-size="11" font-weight="400" text-anchor="start" fill="var(--muted)">JST-VH, pin 1 = +24 V</text>
      <rect x="696.3" y="123.7" width="12.2" height="30.2" rx="2" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <path d="M708.4 138.8 L730.4 138.8" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="736.4" y="135.8" font-size="12" font-weight="700" text-anchor="start" fill="var(--ink)">J23 · JST-PH</text>
      <text x="736.4" y="150.8" font-size="11" font-weight="400" text-anchor="start" fill="var(--muted)">chute stepper</text>
      <rect x="696.3" y="226.2" width="12.2" height="30.2" rx="2" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <path d="M708.4 241.3 L730.4 241.3" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="736.4" y="238.3" font-size="12" font-weight="700" text-anchor="start" fill="var(--ink)">J27 · JST-PH</text>
      <text x="736.4" y="253.3" font-size="11" font-weight="400" text-anchor="start" fill="var(--muted)">C-channel 1 rotor</text>
      <rect x="696.3" y="329.1" width="12.2" height="30.2" rx="2" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <path d="M708.4 344.2 L730.4 344.2" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="736.4" y="341.2" font-size="12" font-weight="700" text-anchor="start" fill="var(--ink)">J31 · JST-PH</text>
      <text x="736.4" y="356.2" font-size="11" font-weight="400" text-anchor="start" fill="var(--muted)">C-channel 3 rotor</text>
      <rect x="696.3" y="432.0" width="12.2" height="30.2" rx="2" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <path d="M708.4 447.1 L730.4 447.1" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="736.4" y="444.1" font-size="12" font-weight="700" text-anchor="start" fill="var(--ink)">J35 · JST-PH</text>
      <text x="736.4" y="459.1" font-size="11" font-weight="400" text-anchor="start" fill="var(--muted)">4th channel rotor</text>
      <rect x="672.7" y="121.2" width="10.5" height="35.3" rx="2" fill="var(--bg)" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 3"/>
      <rect x="672.7" y="223.6" width="10.5" height="35.3" rx="2" fill="var(--bg)" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 3"/>
      <rect x="672.7" y="326.5" width="10.5" height="35.3" rx="2" fill="var(--bg)" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 3"/>
      <rect x="672.7" y="429.4" width="10.5" height="35.3" rx="2" fill="var(--bg)" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 3"/>
      <text x="916" y="596.6" font-size="10" text-anchor="end" fill="var(--muted)">Dashed outlines are parts already on the board. J24 / J28 / J32 / J36 carry the same stepper signals on 2.54 mm pins.</text>
    </svg>
  </div>
  <figcaption>basically board v1.3 from above. Red outlines are the sockets a cable plugs into on this page; the parts already fitted to the board are dashed.</figcaption>
</figure>

<div class="callout">
  <span class="callout-icon" aria-hidden="true">›</span>
  <p>The housing's openings reach the sockets along the edges of the board. If one of the sockets below will not reach with the cover on, take out the four countersunk screws, lift the cover, plug the cable in, and put the cover back. See <a href="{{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}">Control board housing</a>, step 6.</p>
</div>

{% include step.html n="1" title="24 V out of the PSU box" %}

The PSU box has three DC jacks on its connections plate. They are all the same 24 V, so it does not matter which lead goes in which jack. Push each of the three leads fully home.

<figure class="harness-figure">
  <div class="diagram diagram-wide">
    <svg viewBox="0 0 930 420" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="The Mean Well LRS-350-24 terminal block: screws 1 to 3 are live mains from the fused inlet switch, screws 4 to 6 are minus V and 7 to 9 are plus V, paired into three DC output jacks feeding the control board, the USB hub and the Orange Pi buck converter">
      <rect x="180" y="60" width="290" height="300" rx="4" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.5"/>
      <text x="210" y="100" font-size="13" font-weight="700" fill="var(--ink)">MEAN WELL</text>
      <text x="210" y="118" font-size="12" font-weight="700" fill="var(--ink)">LRS-350-24</text>
      <text x="210" y="136" font-size="11" fill="var(--muted)">24 V · 14.6 A</text>
      <rect x="400" y="72" width="52" height="276" rx="3" fill="var(--bg)" stroke="var(--ink)" stroke-width="1.2"/>
      <circle cx="426" cy="92" r="9" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.3"/>
      <text x="426" y="96" font-size="10.5" text-anchor="middle" fill="var(--ink)">1</text>
      <circle cx="426" cy="121" r="9" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.3"/>
      <text x="426" y="125" font-size="10.5" text-anchor="middle" fill="var(--ink)">2</text>
      <circle cx="426" cy="150" r="9" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.3"/>
      <text x="426" y="154" font-size="10.5" text-anchor="middle" fill="var(--ink)">3</text>
      <circle cx="426" cy="179" r="9" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.3"/>
      <text x="426" y="183" font-size="10.5" text-anchor="middle" fill="var(--ink)">4</text>
      <text x="392" y="183" font-size="11" text-anchor="end" fill="var(--muted)">-V</text>
      <circle cx="426" cy="208" r="9" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.3"/>
      <text x="426" y="212" font-size="10.5" text-anchor="middle" fill="var(--ink)">5</text>
      <text x="392" y="212" font-size="11" text-anchor="end" fill="var(--muted)">-V</text>
      <circle cx="426" cy="237" r="9" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.3"/>
      <text x="426" y="241" font-size="10.5" text-anchor="middle" fill="var(--ink)">6</text>
      <text x="392" y="241" font-size="11" text-anchor="end" fill="var(--muted)">-V</text>
      <circle cx="426" cy="266" r="9" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.3"/>
      <text x="426" y="270" font-size="10.5" text-anchor="middle" fill="var(--ink)">7</text>
      <text x="392" y="270" font-size="11" text-anchor="end" fill="var(--muted)">+V</text>
      <circle cx="426" cy="295" r="9" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.3"/>
      <text x="426" y="299" font-size="10.5" text-anchor="middle" fill="var(--ink)">8</text>
      <text x="392" y="299" font-size="11" text-anchor="end" fill="var(--muted)">+V</text>
      <circle cx="426" cy="324" r="9" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.3"/>
      <text x="426" y="328" font-size="10.5" text-anchor="middle" fill="var(--ink)">9</text>
      <text x="392" y="328" font-size="11" text-anchor="end" fill="var(--muted)">+V</text>
      <rect x="40" y="228" width="104" height="48" rx="3" fill="var(--bg)" stroke="var(--ink)" stroke-width="1.2"/>
      <text x="92" y="250" font-size="11.5" font-weight="700" text-anchor="middle" fill="var(--ink)">fused IEC</text>
      <text x="92" y="266" font-size="11.5" font-weight="700" text-anchor="middle" fill="var(--ink)">inlet switch</text>
      <text x="92" y="294" font-size="10.5" text-anchor="middle" fill="var(--muted)">already wired,</text>
      <text x="92" y="309" font-size="10.5" text-anchor="middle" fill="var(--muted)">nothing to make</text>
      <path d="M144 259 C 250 259, 300 92, 400 92" stroke="var(--ink)" stroke-width="1.2" fill="none"/>
      <path d="M144 252 C 250 252, 300 121, 400 121" stroke="var(--ink)" stroke-width="1.2" fill="none"/>
      <path d="M144 245 C 250 245, 300 150, 400 150" stroke="var(--ink)" stroke-width="1.2" fill="none"/>
      <text x="452" y="46" font-size="11" text-anchor="end" fill="var(--muted)">1 live, 2 neutral, 3 earth</text>
      <path d="M452 266 C 500 266, 510 113, 560 113" stroke="var(--ink)" stroke-width="1.4" fill="none"/>
      <path d="M452 179 C 500 179, 510 127, 560 127" stroke="var(--muted)" stroke-width="1.4" fill="none"/>
      <rect x="560" y="100" width="40" height="40" rx="4" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <circle cx="580" cy="120" r="10" fill="var(--bg)" stroke="var(--primary)" stroke-width="1.4"/>
      <circle cx="580" cy="120" r="3" fill="var(--primary)"/>
      <text x="616" y="118" font-size="12" font-weight="700" fill="var(--ink)">to the control board</text>
      <text x="616" y="134" font-size="11" fill="var(--muted)">J1 on the board, JST-VH end</text>
      <path d="M452 295 C 500 295, 510 201, 560 201" stroke="var(--ink)" stroke-width="1.4" fill="none"/>
      <path d="M452 208 C 500 208, 510 215, 560 215" stroke="var(--muted)" stroke-width="1.4" fill="none"/>
      <rect x="560" y="188" width="40" height="40" rx="4" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <circle cx="580" cy="208" r="10" fill="var(--bg)" stroke="var(--primary)" stroke-width="1.4"/>
      <circle cx="580" cy="208" r="3" fill="var(--primary)"/>
      <text x="616" y="206" font-size="12" font-weight="700" fill="var(--ink)">to the USB hub</text>
      <text x="616" y="222" font-size="11" fill="var(--muted)">the hub’s DC input</text>
      <path d="M452 324 C 500 324, 510 289, 560 289" stroke="var(--ink)" stroke-width="1.4" fill="none"/>
      <path d="M452 237 C 500 237, 510 303, 560 303" stroke="var(--muted)" stroke-width="1.4" fill="none"/>
      <rect x="560" y="276" width="40" height="40" rx="4" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <circle cx="580" cy="296" r="10" fill="var(--bg)" stroke="var(--primary)" stroke-width="1.4"/>
      <circle cx="580" cy="296" r="3" fill="var(--primary)"/>
      <text x="616" y="294" font-size="12" font-weight="700" fill="var(--ink)">to the Orange Pi</text>
      <text x="616" y="310" font-size="11" fill="var(--muted)">24 V to 5 V buck, then USB-C</text>
      <text x="580" y="66" font-size="11" text-anchor="middle" fill="var(--muted)">3 × female DC jack</text>
      <text x="580" y="82" font-size="11" text-anchor="middle" fill="var(--muted)">on the connections plate</text>
      <text x="325" y="392" font-size="11" text-anchor="middle" fill="var(--muted)">Screws 1, 2 and 3 are live mains whenever the machine is plugged in.</text>
      <text x="760" y="392" font-size="11" text-anchor="middle" fill="var(--muted)">Pairs: 7 with 4, 8 with 5, 9 with 6.</text>
    </svg>
  </div>
  <figcaption>Inside the PSU box. The mains side (screws 1 to 3) is already wired and stays closed. The three output pairs come out of the box as three DC jacks.</figcaption>
</figure>

The three leads go to the control board, the USB hub, and the buck converter that feeds the Orange Pi. Nothing else runs off the PSU: the two cooling fans do not. There is no spare jack.

{% include step.html n="2" title="24 V into the control board" %}

The board's power input is `J1`, the big 2-pin socket in one corner of the board. It is the only connector of that size on the board, and the plug only goes in one way up.

Pin 1 is +24 V and pin 2 is ground. Both pins are fused on the board.

{% include step.html n="3" title="The five stepper cables" %}

Each stepper has its own socket, and the socket decides which motor the software is driving. Plug them in as below.

<table>
  <thead><tr><th>Socket</th><th>Printed beside it</th><th>The motor that goes on it</th><th>Cable end</th></tr></thead>
  <tbody>
    <tr><td><code>J24</code></td><td><code>Stepper_A2</code></td><td>Chute stepper</td><td>4-pin Dupont on the 2.54 mm pins. The chute motor has bare leads, so they are crimped into a Dupont housing</td></tr>
    <tr><td><code>J27</code></td><td><code>Stepper_A3</code></td><td>C-channel 1 rotor</td><td>JST-PH 4-pin</td></tr>
    <tr><td><code>J31</code></td><td><code>Stepper_A4</code></td><td>C-channel 3 rotor</td><td>JST-PH 4-pin</td></tr>
    <tr><td><code>J35</code></td><td><code>Stepper_A5</code></td><td>Classification channel rotor (the software calls it the carousel)</td><td>JST-PH 4-pin</td></tr>
    <tr><td><code>J39</code></td><td><code>Stepper_A6</code></td><td>C-channel 2 rotor</td><td>JST-PH 4-pin</td></tr>
  </tbody>
</table>

Every socket has a row of 2.54 mm pins beside it carrying the same signals, so a cable with a Dupont end goes on those instead: `J24` beside `J23`, `J28` beside `J27`, and so on. `Stepper_A6` is on the far side of the board on its own; the other four are in a row along one edge.

Each socket is wired to the driver printed beside it, so that driver has to carry the address for that stepper. The addresses are set in [preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}), step 3.

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>Check the coils before you plug a motor in.</b> A stepper has two coils, two wires each, and the plug has four holes: holes 1 and 2 feed one coil, 3 and 4 the other. Put a multimeter across the wires that should be a pair. A pair reads a few ohms; two wires from different coils read open circuit. If holes 2 and 3 are the pair, pull those two contacts out of the housing and swap them, or the motor will buzz and barely turn. Full pinout: <a href="{{ '/hardware/electronics/steppers/' | relative_url }}">stepper connectors</a>.</p>
</div>

{% include step.html n="4" title="The chute limit switch" %}

The switch tells the machine where the chute is. Its cable ends in a 3-pin Dupont housing with only two positions filled, and it goes on `J5`, the header the board prints `HALL_SW_0`.

The filled positions are ground and signal. The empty one lines up with the 3.3 V pin, so the housing cannot go on backwards.

At the switch end, push the two #187 tabs onto the switch's `COM` and `NC` terminals. The switch has three tabs and one stays empty. Wired this way the circuit is closed while the lever is free and opens when the chute presses it, which is what the machine expects. If homing runs the wrong way round later, the setting is in the software, not the wiring.

{% include step.html n="5" title="The three camera lamps" %}

The board has four LED ports. The fan in the housing lid is already on one of them, so the three [LED drops]({{ '/hardware/electronics/led-drop/' | relative_url }}) from the [camera lamps]({{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}) take the other three.

<table>
  <thead><tr><th>Port</th><th>Printed on the board</th><th>What goes on it</th></tr></thead>
  <tbody>
    <tr><td><code>J8</code></td><td><code>LED_0_1</code></td><td>Camera lamp</td></tr>
    <tr><td><code>J9</code></td><td><code>LED_0_2</code></td><td>Camera lamp</td></tr>
    <tr><td><code>J10</code></td><td><code>LED_1_1</code></td><td>Camera lamp</td></tr>
    <tr><td><code>J11</code></td><td><code>LED_1_2</code></td><td>The housing fan, fitted on the housing page</td></tr>
  </tbody>
</table>

The board prints `+V` beside one pin of each port and `GND` beside the other. The red wire goes to `+V`.

<div class="callout">
  <span class="callout-icon" aria-hidden="true">›</span>
  <p><b>Four ports, two switches.</b> <code>J8</code> and <code>J9</code> turn on and off together, and so do <code>J10</code> and <code>J11</code>. So one lamp always comes on with the fan. Which lamp is on which output is picked in the software later, on the LED button for each channel.</p>
</div>

Leave the small solder jumpers next to the three lamp ports alone. Each port feeds +24 V through a resistor that the LED strip wants. The fan's port is the one that gets bridged, and that is done on the [housing]({{ '/hardware/electronics/installation/control-board-housing/' | relative_url }}) page.

{% include step.html n="6" title="The ribbon down to the layers" %}

One flat 16-pin ribbon runs from `J17` on the control board to the first layer board in the chute, and a shorter one runs from each layer board to the one below it. Both ends of every ribbon are keyed, so they only go in one way up.

<table>
  <thead><tr><th>Cable</th><th>From</th><th>To</th></tr></thead>
  <tbody>
    <tr><td>1 m ribbon</td><td>Control board <code>J17</code></td><td>First layer board, <code>J3</code></td></tr>
    <tr><td>30 cm ribbon, one per extra layer</td><td>A layer board, <code>J4</code></td><td>The next layer board down, <code>J3</code></td></tr>
  </tbody>
</table>

<div class="callout callout-warning">
  <span class="callout-icon" aria-hidden="true">⚠</span>
  <p><b>On a layer board, <code>J3</code> is the cable coming in and <code>J4</code> is the cable going on down.</b> The two look identical and only the designator is printed on the board. A board fed on <code>J4</code> gets no signal at all, and every layer below it moves the wrong flap.</p>
</div>

Each layer board's own servo plugs into `J5` on that board, three pins, signal and power and ground. That is covered on the [chute PCB]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}) page.

{% include step.html n="7" title="USB: the Pico, the hub and the Orange Pi" %}

The Orange Pi talks to the control board over USB, through the powered hub. The three cameras are on the same hub.

<figure class="harness-figure">
  <div class="diagram diagram-wide">
    <svg viewBox="0 0 930 580" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Top view of the Orange Pi 5 with the ports this build uses labelled: the USB-C marked PWR IN, the upper USB 3.0 port, the LAN socket, the microSD slot, the 26-pin header and the 2-pin FAN connector">
      <rect x="200.0" y="60.0" width="540.0" height="334.8" rx="6" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.5"/>
      <rect x="221.6" y="68.1" width="183.6" height="18.9" rx="2" fill="var(--bg)" stroke="var(--ink)" stroke-width="1"/>
      <text x="313.4" y="103.2" font-size="10" text-anchor="middle" fill="var(--muted)">26-pin header</text>
      <rect x="432.2" y="68.1" width="48.6" height="16.2" rx="2" fill="var(--bg)" stroke="var(--ink)" stroke-width="1"/>
      <text x="456.5" y="103.2" font-size="10" text-anchor="middle" fill="var(--muted)">debug UART</text>
      <rect x="194.6" y="108.6" width="59.4" height="59.4" rx="2" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <rect x="227.0" y="359.7" width="59.4" height="35.1" rx="2" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <rect x="300.4" y="365.1" width="38.3" height="29.7" rx="2" fill="var(--bg)" stroke="var(--ink)" stroke-width="1"/>
      <rect x="351.2" y="351.6" width="73.4" height="43.2" rx="2" fill="var(--bg)" stroke="var(--ink)" stroke-width="1"/>
      <rect x="453.8" y="362.4" width="47.5" height="32.4" rx="2" fill="var(--bg)" stroke="var(--ink)" stroke-width="1"/>
      <rect x="513.2" y="367.8" width="81.0" height="27.0" rx="2" fill="var(--bg)" stroke="var(--ink)" stroke-width="1"/>
      <rect x="605.0" y="367.8" width="64.8" height="27.0" rx="2" fill="var(--bg)" stroke="var(--ink)" stroke-width="1"/>
      <text x="387.9" y="340.8" font-size="10" text-anchor="middle" fill="var(--muted)">HDMI</text>
      <text x="477.6" y="340.8" font-size="10" text-anchor="middle" fill="var(--muted)">TYPE-C</text>
      <text x="553.7" y="354.3" font-size="10" text-anchor="middle" fill="var(--muted)">LCD</text>
      <text x="637.4" y="354.3" font-size="10" text-anchor="middle" fill="var(--muted)">CAM</text>
      <rect x="675.2" y="108.6" width="70.2" height="49.7" rx="2" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <rect x="675.2" y="158.3" width="70.2" height="49.7" rx="2" fill="var(--bg)" stroke="var(--ink)" stroke-width="1"/>
      <rect x="675.2" y="227.4" width="70.2" height="91.8" rx="2" fill="var(--bg)" stroke="var(--ink)" stroke-width="1"/>
      <rect x="675.2" y="332.7" width="70.2" height="51.3" rx="2" fill="var(--bg)" stroke="var(--ink)" stroke-width="1"/>
      <rect x="610.4" y="292.2" width="21.6" height="21.6" rx="2" fill="var(--surface)" stroke="var(--primary)" stroke-width="2"/>
      <path d="M256.7 394.8 L256.7 438.0" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="256.7" y="475.8" font-size="12" font-weight="700" text-anchor="middle" fill="var(--ink)">PWR IN</text>
      <text x="256.7" y="490.8" font-size="11" font-weight="400" text-anchor="middle" fill="var(--muted)">USB-C, from the</text>
      <text x="256.7" y="505.8" font-size="11" font-weight="400" text-anchor="middle" fill="var(--muted)">24 V to 5 V buck</text>
      <path d="M477.6 394.8 L477.6 438.0" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="477.6" y="475.8" font-size="10" text-anchor="middle" fill="var(--muted)">not the power port</text>
      <path d="M745.4 132.9 L785.4 132.9" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="791.4" y="114.0" font-size="12" font-weight="700" text-anchor="start" fill="var(--ink)">UP: USB 3.0</text>
      <text x="791.4" y="129.0" font-size="11" font-weight="400" text-anchor="start" fill="var(--muted)">to the USB hub</text>
      <path d="M745.4 183.1 L785.4 183.1" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="791.4" y="200.4" font-size="12" font-weight="700" text-anchor="start" fill="var(--ink)">DOWN: USB 2.0</text>
      <text x="791.4" y="215.4" font-size="11" font-weight="400" text-anchor="start" fill="var(--muted)">spare</text>
      <path d="M745.4 270.6 L785.4 270.6" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="791.4" y="286.8" font-size="12" font-weight="700" text-anchor="start" fill="var(--ink)">LAN</text>
      <text x="791.4" y="301.8" font-size="11" font-weight="400" text-anchor="start" fill="var(--muted)">wired network, optional</text>
      <path d="M745.4 357.0 L785.4 357.0" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="791.4" y="373.2" font-size="12" font-weight="700" text-anchor="start" fill="var(--ink)">USB 2.0</text>
      <text x="791.4" y="388.2" font-size="11" font-weight="400" text-anchor="start" fill="var(--muted)">spare</text>
      <path d="M194.6 138.3 L154.6 138.3" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="148.6" y="119.4" font-size="12" font-weight="700" text-anchor="end" fill="var(--ink)">microSD</text>
      <text x="148.6" y="134.4" font-size="11" font-weight="400" text-anchor="end" fill="var(--muted)">the SorterOS card,</text>
      <text x="148.6" y="149.4" font-size="11" font-weight="400" text-anchor="end" fill="var(--muted)">at software setup</text>
      <path d="M610.4 303.0 L594.4 303.0 L594.4 249.0 L459.2 249.0" stroke="var(--muted)" stroke-width="1" fill="none"/>
      <text x="448.4" y="238.2" font-size="12" font-weight="700" text-anchor="end" fill="var(--ink)">FAN · 5 V, 2-pin</text>
      <text x="448.4" y="253.2" font-size="11" font-weight="400" text-anchor="end" fill="var(--muted)">see the note below</text>
      <text x="313.4" y="122.1" font-size="10" text-anchor="middle" fill="var(--muted)">5 V on pins 2 and 4</text>
    </svg>
  </div>
  <figcaption>The Orange Pi 5 from above, in the same orientation as the photo on the <a href="{{ '/hardware/orange-pi-5/' | relative_url }}">Orange Pi 5</a> page. Only the sockets this build uses are marked.</figcaption>
</figure>

1. Plug the buck converter's USB-C lead into the socket the board prints `PWR IN`. **The Pi has two USB-C sockets that look the same, and the other one is not a power input.** Check that the converter is putting out 5 V before it goes anywhere near the Pi.
2. Run a USB cable from the Pico's micro USB socket to any port on the hub.
3. Run a USB cable from the hub to the port marked `UP USB3.0` on the Pi, the upper of the two stacked sockets.
4. Plug the three cameras into the three remaining hub ports.

That fills the hub: three cameras and the Pico, no spare port.

<div class="callout">
  <span class="callout-icon" aria-hidden="true">›</span>
  <p><b>They have to be data cables.</b> Many short USB cables carry power only and nothing will appear on the Pi. Use the powered hub as well: a hub running off the Pi's own power has been seen to brown the Pi out and crash it.</p>
</div>

{% include step.html n="8" title="Check it over, then plug it in" %}

Before the machine sees mains:

- All three DC leads are in their jacks, and the PSU box is closed.
- Every stepper plug is fully home, and no plug is hanging on one contact.
- The ribbon goes from the board to `J3` of the first layer board, and down the stack `J4` to `J3`.
- Nothing is resting on the fan blades.

Then plug the machine in and switch the inlet switch on. The red power light on the Orange Pi comes on. The fan in the housing lid does not run yet, because the software switches it.

Next: [software setup]({{ '/hardware/assembly/software-setup/' | relative_url }}), which flashes the Orange Pi and the control board and then asks you which output each lamp and each stepper is on.

## What is not recorded yet

- **The Orange Pi's fan.** The Pi has a 2-pin `FAN` connector of its own, and it is 5 V. The fan in the parts list for the [Orange Pi mount]({{ '/hardware/electronics/installation/orange-pi-mount/' | relative_url }}) is a 24 V one, which that connector cannot run. Which fan goes there, and where its lead lands, is still open.
