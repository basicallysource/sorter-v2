---
layout: default
title: Power distribution
type: explanation
section: lab
slug: lab-power
kicker: Design and research — Electronics
lede: How 24 V gets from the wall to every part of the machine, what is fused where, and the ratings of the cables, connectors and devices on the way.
permalink: /lab/power/
audience: curious builder or contributor
applies_to: hardware-v2
owner: docs
warning: >-
  **AI-generated first draft.** Written from the Pico firmware, the control program and the board's
  KiCad files, not from an actual build. The part names, pins and numbers are read from those files and
  have not been checked against a built machine.
---

The whole machine runs from one 24 V power supply. The other voltages (12 V, 6.5 V, 5 V and 3.3 V) are made from the 24 V further down, mostly on the control board. Each of these voltages is called a rail, a wire inside the board that carries one voltage. There is no separate power board in this version, so the protection is light: two fuses on the control board and a fused inlet on the mains side (the wall-socket side).

This page describes the **basically board v1.3** and the cables as the [Wire harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) page draws them. Which plug goes in which socket is on [Connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}) and is not repeated here. **This page is not wiring instructions.** Mains voltage is lethal, and the mains side is built on [the PSU box page]({{ '/hardware/electronics/installation/psu-box/' | relative_url }}).

## From the wall to 24 V

<ul class="bulleted-list">
  <li><strong>Inlet:</strong> an IEC C14 inlet with an illuminated rocker switch (15 A, 250 V) and a 10 A fuse (5 × 20 mm). It is the machine's main switch and also its mains fuse.</li>
  <li><strong>Supply:</strong> a Mean Well LRS-350-24, 24 V at up to 14.6 A (350 W), with no minimum load. It is <strong>not universal input</strong>: a slide switch on the side of its case selects 115 V or 230 V, and the setting has to match your wall socket before you switch on for the first time.</li>
  <li><strong>Behaviour:</strong> the datasheet gives a typical inrush of 60 A at either mains voltage (a short surge of current at the moment you switch on). If the load is 110 to 140% of the rated power, the output switches itself off and on again repeatedly (hiccup mode) and recovers by itself when the load drops. The output voltage can be adjusted from 21.6 to 28.8 V with a small adjustable pot (a trimmer) beside the terminal block.</li>
</ul>

The supply has three +V and three -V screw terminals. Each +V/-V pair is wired to one panel-mount barrel jack (a round DC power socket) on the front of the PSU box, so the supply has **three 24 V outputs, all the same**.

## Three jacks, three loads

Each jack feeds one load through its own lead, and nothing else runs from the supply. The cooling fans are not on it either.

<ul class="bulleted-list">
  <li><strong><code>PWR1</code>, the control board:</strong> a lead from a barrel plug to <code>J1</code>, a JST VH header (a two-pin power connector on the board).</li>
  <li><strong><code>PWR2</code>, the USB hub:</strong> a lead to the hub's own DC input, which takes 7 to 36 V.</li>
  <li><strong><code>PWR3</code>, the Orange Pi:</strong> a lead to a 24 V to 5 V buck converter, whose USB-C lead (sealed in resin) then plugs into the Orange Pi. The converter takes 8 to 32 V in and gives 5 V at up to 5 A. It protects itself against reversed connection, too high a voltage, too high a current, overheating and short circuits. The Orange Pi asks for 5 V at 4 A over USB-C.</li>
</ul>

The board has two USB-C sockets that look the same, and only the one marked <code>PWR IN</code> takes power. The other is for data and for a screen, and the machine does not use it. The hub has its own 24 V feed (<code>PWR2</code>), so the Orange Pi does not power the hub, and it does not power the cameras or the Pico through it.

<ul class="bulleted-list">
  <li>The three leads and their drawings: <a href="{{ '/hardware/parts/harness-order/' | relative_url }}">Ordering the wire harness</a></li>
  <li>Making them: <a href="{{ '/hardware/helpers/psu-pigtail/' | relative_url }}">PSU pigtail</a>, <a href="{{ '/hardware/helpers/board-24v-lead/' | relative_url }}">board 24 V lead</a>, <a href="{{ '/hardware/helpers/pi-24v-lead/' | relative_url }}">Orange Pi 24 V lead</a></li>
  <li>The converter and the board in the catalog: <a href="https://github.com/basicallysource/sorter-v2/blob/main/parts-calculator/catalog/parts.json"><code>parts-calculator/catalog/parts.json</code></a> (<code>buck-24v-5v-usbc</code>, <code>sbc-orange-pi-5</code>)</li>
  <li>The harness data the drawings are generated from: <a href="https://github.com/basicallysource/sorter-v2/blob/main/electronics/wire_harness/power.yml"><code>electronics/wire_harness/power.yml</code></a></li>
</ul>

## Why 24 V and these converters

<ul class="bulleted-list">
  <li><strong>One 24 V rail.</strong> The plan stated in <a href="https://discord.com/channels/1430279849171222682/1442165893290266707/1442175938283573329">November 2025</a> was a 24 V main rail, with converters from it to whatever voltages are needed.</li>
  <li><strong>The supply model.</strong> The supply is a Mean Well LRS-350-24, 350 W. We are currently trying to find out why this was decided this way, and will add the reason or an explanation later.</li>
  <li><strong>A boxed supply.</strong> An open-frame supply was ruled out because people should not be required to work with mains voltage (<a href="https://discord.com/channels/1430279849171222682/1437436041685631129/1440779058198745210">November 2025</a>).</li>
  <li><strong>The 6.5 V converter takes 12 V, not 24 V.</strong> The converter module cannot take 24 V directly (<a href="https://discord.com/channels/1430279849171222682/1509730904413569174/1509761538490372178">May 2026</a>). The modules were chosen because they were the easiest to be sure would just work, even though they are expensive singly (<a href="https://discord.com/channels/1430279849171222682/1437436041685631129/1525984596750110740">July 2026</a>).</li>
  <li><strong>Fuse guidance.</strong> The guidance given in the design discussion was that the main fuses can be cheap ordinary ones, meant only as protection against a disaster, with resettable fuses on the individual loads (<a href="https://discord.com/channels/1430279849171222682/1457600314197672056/1458980998816727132">January 2026</a>).</li>
</ul>

## Inside the control board

24 V comes in at `J1`, through a fuse in each wire (`F1` on the +24 V wire, `F2` on the return wire). A diode, `D2`, sits across the supply to protect the board if the supply is connected the wrong way round. From there:

<ul class="bulleted-list">
  <li><strong>24 V</strong> goes straight to the five stepper driver sockets to power the motors, to the four LED ports, and to the converters below.</li>
  <li><strong>5 V:</strong> a RECOM R-78 converter module (<code>U3</code>, 1 A) makes it from the 24 V. It feeds the Pico through its VSYS pin, the servo controller chip and the level shifters (small chips that translate between voltages).</li>
  <li><strong>12 V:</strong> a RECOM R-78 converter module (<code>U4</code>, 2 A) makes it from the 24 V. It is available on header <code>J2</code> and is also the input of the next stage.</li>
  <li><strong>6.5 V, "ServoV":</strong> a RECOM R-78 converter module (<code>U5</code>, 1.5 A) makes it from the 12 V. It powers the servos and runs down the ribbon cable to every layer's adapter board (see <a href="{{ '/lab/servos/' | relative_url }}">The servos and the layer adapter boards</a>).</li>
  <li><strong>3.3 V</strong> comes from the Pico's own 3V3 output, not from a separate voltage regulator on the board. It goes to the driver sockets.</li>
</ul>

All three converters are switching modules that fit where a simple linear 78xx regulator would go (the same three pins). A linear regulator that lowers 24 V to 5 V at 1 A would turn about 19 W into heat, which is why one is not used.

<ul class="bulleted-list">
  <li>The schematic: <a href="https://github.com/basicallysource/sorter-v2/blob/main/electronics/KiCad/1_Distribution_Board/Power.kicad_sch"><code>Power.kicad_sch</code></a>, with the LED ports on <a href="https://github.com/basicallysource/sorter-v2/blob/main/electronics/KiCad/1_Distribution_Board/Level_Shifters.kicad_sch"><code>Level_Shifters.kicad_sch</code></a></li>
  <li>Preparing the board before it is installed: <a href="{{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}">Preparing the control board</a></li>
</ul>

## The motors

The five stepper motors run on the 24 V rail, each through its own TMC2209 driver on the control board. Their sizes, how the drivers are set up and how much current each motor gets are on [The motors]({{ '/lab/motors/' | relative_url }}). Their electrical ratings are in the device table below.

## The lamps and the fan

The board has four LED ports, `J8` to `J11`. Each is the 24 V rail through a 180 Ω resistor on its +24 V pin, and a MOSFET (AO3400A, an electronic switch) on its ground pin that the Pico controls. So a lamp or fan always has 24 V on one side, and the board **switches the ground side** on and off. For brightness it does this very fast (PWM), and the share of time it is on sets how bright the lamp is. Two ports share each of the Pico's two PWM outputs, `J8` with `J9` and `J10` with `J11`, so dimming one dims its partner.

The 180 Ω resistor is there for a bare LED board that does not limit its own current. The camera lamps use an LED strip that does limit its own current, so the resistor would only make them dimmer. Each port has a solder jumper (a spot you can bridge with solder) across its resistor, and the build bridges all four. The same bridge is what lets the 24 V fan run at full voltage from a port.

The three lamps each use about 920 mm of strip at roughly 10 W per metre, so about 9 W each. The housing fan is a 40 mm, 24 V fan on the fourth port. The Orange Pi's own heatsink fan is 5 V and plugs into the Orange Pi's FAN socket instead.

<ul class="bulleted-list">
  <li>Bridging the resistor jumpers: <a href="{{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}">Preparing the control board</a></li>
  <li>Which lamp or fan is on which port: <a href="{{ '/hardware/electronics/connecting/' | relative_url }}">Connecting the components</a></li>
  <li>The strip and its cables: <a href="{{ '/hardware/helpers/led-strip/' | relative_url }}">LED strip</a>, and the lamp itself: <a href="{{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}">Camera lamp</a></li>
</ul>

## What is fused where

<ul class="bulleted-list">
  <li><strong>Mains side:</strong> the 10 A fuse in the inlet. It comes before the power supply, so it does not protect anything on the 24 V side.</li>
  <li><strong>24 V side:</strong> the PSU jacks and their leads are not fused.</li>
  <li><strong>Control board:</strong> <code>F1</code> and <code>F2</code>, 1206 (a small surface-mount size) slow-blow fuses rated 10 A and 32 V DC, one in each wire of <code>J1</code>. Nothing after them is fused: not the LED ports, the driver sockets, or the 12 V, 6.5 V and 5 V outputs. The diode <code>D2</code>, which protects against a reversed supply, is rated 8 A, so it is the weaker part if the supply is ever connected the wrong way round.</li>
  <li><strong>Orange Pi branch:</strong> only the buck converter's own protection.</li>
</ul>

A 10 A fuse opens on a dead short, not on a modest overload. The supply's own overload point is roughly 16 to 20 A (110 to 140% of 14.6 A), and between a barrel jack's 5 A rating and that point nothing opens.

<ul class="bulleted-list">
  <li>Board fuse and diode parts: <a href="https://github.com/basicallysource/sorter-v2/blob/main/electronics/KiCad/1_Distribution_Board/Power.kicad_sch"><code>Power.kicad_sch</code></a></li>
</ul>

## Ratings: cables and connectors

The wire harness (the set of cables) uses tinned, stranded UL1007 wire rated 300 V. Wire sizes are given in AWG, where a smaller number means a thicker wire. The harness lists the size and colour of each cable, but not an ampere rating for the wire itself. On every two-wire power cable, red is +24 V and black is ground (the return wire). In the table, names such as `PSU1`, `PWR1` and `STP1` are the cable labels used on the wire harness page.

<table>
  <thead><tr><th>Part</th><th>Rating or spec</th><th>Where it is used</th></tr></thead>
  <tbody>
    <tr><td>18 AWG (0.82 mm²), red and black</td><td>UL1007, 300 V</td><td><code>PSU1</code> to <code>PSU3</code>, <code>PWR1</code></td></tr>
    <tr><td>22 AWG (0.33 mm²), red and black</td><td>UL1007, 300 V</td><td><code>PWR2</code>, <code>PWR3</code>, <code>LED2a</code> to <code>LED4a</code>, <code>LED2</code> to <code>LED4</code></td></tr>
    <tr><td>24 AWG (0.20 mm²), blue, green, red, black</td><td>UL1007, 300 V. Set by the JST-PH contact limit</td><td><code>STP1</code> to <code>STP4</code>, <code>CHU1</code></td></tr>
    <tr><td>IEC C14 inlet with switch and fuse</td><td>Switch 15 A 250 V, fuse 10 A</td><td>Mains side of the supply</td></tr>
    <tr><td>Insulated fork terminal, M3.5</td><td>18 AWG wire, 8 mm wide at most</td><td>Both leads of <code>PSU1</code> to <code>PSU3</code>, onto the supply's terminal block</td></tr>
    <tr><td>Barrel jack and plug, 5.5 × 2.1 mm</td><td>5 A or better, centre positive</td><td><code>PSU1</code> to <code>PSU3</code>, <code>PWR1</code> to <code>PWR3</code>, <code>LED2</code> to <code>LED4</code>, <code>LED2a</code> to <code>LED4a</code></td></tr>
    <tr><td>JST VH header <code>J1</code>, housing VHR-2N, contact SVH-21T-P1.1</td><td>7 A with 18 AWG wire in the shrouded header</td><td><code>PWR1</code> into the board</td></tr>
    <tr><td>Clamp-on LED strip connector, 8 mm</td><td>3 A maximum</td><td>One per camera lamp</td></tr>
    <tr><td>Dupont, JST-PH, #187 quick-connect</td><td>No current rating given</td><td>Dupont on <code>LED2a</code> to <code>LED4a</code> and <code>LIM1</code>, JST-PH on <code>STP1</code> to <code>STP4</code> and <code>CHU1</code>, #187 on the limit switch</td></tr>
  </tbody>
</table>

In the board's 24 V path, the part with the lowest rating is the barrel jack at 5 A, then the VH header at 7 A, then the 10 A fuses. The order page asks for "5 A or better" on every barrel connector.

<ul class="bulleted-list">
  <li>The length, gauge and connectors of every cable: <a href="{{ '/hardware/parts/harness-order/' | relative_url }}">Ordering the wire harness</a></li>
  <li>The RFQ text with the wire spec: <a href="https://github.com/basicallysource/sorter-v2/blob/main/electronics/wire_harness/rfq.txt"><code>electronics/wire_harness/rfq.txt</code></a></li>
</ul>

## Ratings: devices

<table>
  <thead><tr><th>Device</th><th>Rating</th><th>Where it is in the machine</th></tr></thead>
  <tbody>
    <tr><td>Mean Well LRS-350-24</td><td>24 V, 14.6 A, 350 W. Mains draw 6.8 A at 115 V or 3.4 A at 230 V</td><td>The only supply; three outputs</td></tr>
    <tr><td>NEMA 17 stepper, StepperOnline 17HE15-1504S</td><td>1.5 A per phase, 2.3 Ω per phase</td><td>Three feeder channels and the carousel, on <code>STP1</code> to <code>STP4</code></td></tr>
    <tr><td>NEMA 23 stepper, StepperOnline 23HS32-4004S</td><td>4.0 A per phase, 0.65 Ω per phase</td><td>The chute, on <code>CHU1</code></td></tr>
    <tr><td>TMC2209 driver module</td><td>2 A RMS continuous, 2.8 A peak, 5 per machine</td><td>One per stepper, on the control board</td></tr>
    <tr><td>Camera lamp, 24 V COB LED strip</td><td>About 10 W per metre, so about 9 W per lamp</td><td>Three lamps, on three LED ports</td></tr>
    <tr><td>Housing fan, WINSINN 4010</td><td>24 V, 0.04 A</td><td>Fourth LED port</td></tr>
    <tr><td>Orange Pi 5</td><td>5 V at 4 A over USB-C</td><td><code>PWR3</code>, through the buck converter</td></tr>
    <tr><td>24 V to 5 V buck converter</td><td>8 to 32 V in, 5 V at 5 A (25 W) out</td><td>Between <code>PWR3</code> and the Orange Pi</td></tr>
    <tr><td>Powered USB hub, Waveshare USB3.2-Gen1-HUB-4U</td><td>7 to 36 V in</td><td><code>PWR2</code></td></tr>
    <tr><td>MG995 servo</td><td>4.8 to 7.2 V. 10 mA idle, 170 mA no load, 1.2 A stalled</td><td>Flaps, on the 6.5 V ServoV rail</td></tr>
    <tr><td>Board 5 V, 12 V and 6.5 V converters</td><td>1 A, 2 A and 1.5 A</td><td>Control board, <code>U3</code>, <code>U4</code>, <code>U5</code></td></tr>
  </tbody>
</table>

The one place a motor can ask for more than its supply gives is the 6.5 V ServoV rail. A stalled MG995 takes about 1.2 A against the converter's 1.5 A, so two flaps stalling together are over it. How the servos and their boards use that rail is on [The servos and the layer adapter boards]({{ '/lab/servos/' | relative_url }}).

<ul class="bulleted-list">
  <li>Every part's attributes: <a href="https://github.com/basicallysource/sorter-v2/blob/main/parts-calculator/catalog/parts.json"><code>parts-calculator/catalog/parts.json</code></a></li>
</ul>

## Load against supply

The supply can give 350 W. The three camera lamps are about 28 W of that, or about 1.2 A at 24 V. The motors draw what their drivers are set to give (see [The motors]({{ '/lab/motors/' | relative_url }})), and the Orange Pi branch tops out at the buck converter's 25 W. The supply, the jacks and the cables are well inside their ratings in normal use.
