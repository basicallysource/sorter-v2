---
layout: default
title: Power distribution
type: explanation
section: design
slug: design-power
kicker: Design — Electronics
lede: How 24 V gets from the wall to every part of the machine, what is fused where, and the ratings of the cables, connectors and devices on the way.
permalink: /design/power/
last_verified: 2026-10-10
---

The whole machine runs from one 24 V supply. Everything else, the 12 V, 6.5 V, 5 V and 3.3 V rails, is made from that 24 V further down, mostly on the control board. There is no separate power board in this version, so the protection is light: two fuses on the control board and a fused inlet on the mains side.

This page describes the **basically board v1.3** and the cables as the [Wire harness]({{ '/hardware/electronics/wire-harness/' | relative_url }}) page draws them. Which plug goes in which socket is on [Connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}) and is not repeated here. **This page is not wiring instructions.** Mains voltage is lethal, and the mains side is built on [the PSU box page]({{ '/hardware/electronics/installation/psu-box/' | relative_url }}).

## From the wall to 24 V

<ul class="bulleted-list">
  <li><strong>Inlet:</strong> an IEC C14 inlet with an illuminated rocker switch (15 A, 250 V) and a 10 A fuse (5 × 20 mm). It is the machine's main switch and its mains fuse.</li>
  <li><strong>Supply:</strong> a Mean Well LRS-350-24, 24 V at up to 14.6 A (350 W), with no minimum load. It is <strong>not universal input</strong>: a slide switch on the side of its case selects 115 V or 230 V, and it has to match the wall before the first power-up.</li>
  <li><strong>Behaviour:</strong> the datasheet gives a typical inrush of 60 A at either mains voltage. The output trips into a self-recovering hiccup mode at 110 to 140% of rated power, and the output voltage can be trimmed from 21.6 to 28.8 V with a pot beside the terminal block.</li>
</ul>

The supply has three +V and three -V screw terminals. Each +V/-V pair is wired to one panel-mount barrel jack on the front of the PSU box, so the supply has **three 24 V outputs, all the same**.

## Three jacks, three loads

Each jack feeds one load through its own lead, and nothing else runs from the supply. The cooling fans are not on it either.

<ul class="bulleted-list">
  <li><strong><code>PWR1</code>, the control board:</strong> a 920 mm (36 in) lead from a barrel plug to the JST VH header <code>J1</code>.</li>
  <li><strong><code>PWR2</code>, the USB hub:</strong> a 310 mm (12 in) lead to the hub's own DC input, which takes 7 to 36 V.</li>
  <li><strong><code>PWR3</code>, the Orange Pi:</strong> a 150 mm (6 in) lead to a 24 V to 5 V buck converter, whose potted USB-C lead then plugs into the Orange Pi. The converter takes 8 to 32 V in and gives 5 V at up to 5 A, with reverse, over-voltage, over-current, over-temperature and short-circuit protection of its own. The Orange Pi asks for 5 V at 4 A over USB-C.</li>
</ul>

<ul class="bulleted-list">
  <li>The three leads and their drawings: <a href="{{ '/hardware/parts/harness-order/' | relative_url }}">Ordering the wire harness</a></li>
  <li>Making them: <a href="{{ '/hardware/helpers/psu-pigtail/' | relative_url }}">PSU pigtail</a>, <a href="{{ '/hardware/helpers/board-24v-lead/' | relative_url }}">board 24 V lead</a>, <a href="{{ '/hardware/helpers/pi-24v-lead/' | relative_url }}">Orange Pi 24 V lead</a></li>
  <li>The harness data the drawings are generated from: <a href="https://github.com/basicallysource/sorter-v2/blob/main/electronics/wire_harness/power.yml"><code>electronics/wire_harness/power.yml</code></a></li>
</ul>

## Inside the control board

24 V comes in at `J1`, through a fuse in each leg (`F1` on +24 V, `F2` on the return), and a reverse-polarity diode (`D2`) sits across the rail. From there:

<ul class="bulleted-list">
  <li><strong>24 V</strong> goes straight to the five stepper driver sockets as the motor supply, to the four LED ports, and to the three converters below.</li>
  <li><strong>5 V:</strong> a RECOM R-78 module (<code>U3</code>, 1 A) from 24 V. It feeds the Pico through its VSYS pin, the servo controller chip and the level shifters.</li>
  <li><strong>12 V:</strong> a RECOM R-78 module (<code>U4</code>, 2 A) from 24 V, brought out on header <code>J2</code> and also the input of the next stage.</li>
  <li><strong>6.5 V, "ServoV":</strong> a RECOM R-78 module (<code>U5</code>, 1.5 A) from the 12 V. It powers the servos, and runs down the ribbon cable to every layer's adapter board.</li>
  <li><strong>3.3 V</strong> comes from the Pico's own 3V3 output, not from a regulator on the board. It goes to the driver sockets.</li>
</ul>

All three converters are switching modules that replace a linear 78xx in the same three-pin footprint. A linear regulator dropping 24 V to 5 V at 1 A would burn about 19 W, which is why they are not used.

<ul class="bulleted-list">
  <li>The schematic: <a href="https://github.com/basicallysource/sorter-v2/blob/main/electronics/KiCad/1_Distribution_Board/Power.kicad_sch"><code>Power.kicad_sch</code></a>, with the LED ports on <a href="https://github.com/basicallysource/sorter-v2/blob/main/electronics/KiCad/1_Distribution_Board/Level_Shifters.kicad_sch"><code>Level_Shifters.kicad_sch</code></a></li>
  <li>Preparing the board before it is installed: <a href="{{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}">Preparing the control board</a></li>
</ul>

## The motors and their drivers

There are five TMC2209 drivers, one per stepper: four NEMA 17 (the three feeder channels and the carousel) and one NEMA 23 (the chute). The motor supply is the 24 V rail.

A stepper's rated current is a ceiling, not what it draws. A chopper driver sets the coil current and does not pull more from the supply than the motor needs, so a 4 A NEMA 23 on a 2 A driver is normal: it simply makes a fraction of its rated torque, and the chute is geared down 4.8:1.

**Two places set the real current, and they multiply.** The trim pot on each driver module sets a maximum, and the software then sets run and hold current (IRUN and IHOLD, 0 to 31) as fractions of that maximum. Leaving a pot high and also raising IRUN in software pushes the current up twice, so the two together can run a motor much hotter than either setting alone suggests. The defaults live in the backend:

<ul class="bulleted-list">
  <li>Feeder channel rotors: IRUN 4, IHOLD 1</li>
  <li>Carousel: IRUN 8, IHOLD 1</li>
  <li>Chute, and any stepper without its own entry: IRUN 16, IHOLD 4</li>
</ul>

Each can be overridden per stepper in the machine's TOML file.

<ul class="bulleted-list">
  <li>Defaults and the validation of overrides: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/irl/parse_user_toml.py"><code>irl/parse_user_toml.py</code></a></li>
  <li>The commented override example: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/machine.example.toml"><code>software/machine.example.toml</code></a></li>
  <li>Stepper cables and coil order: <a href="{{ '/hardware/electronics/wire-harness/' | relative_url }}">Wire harness</a></li>
</ul>

## The lamps and the fan

The board has four LED ports, `J8` to `J11`. Each is the 24 V rail through a 180 Ω resistor on its +24 V pin, and an N-channel MOSFET (AO3400A) on its ground pin that the Pico switches. So a lamp or fan is always at 24 V on one side and the board **switches the ground side**, with PWM for brightness. Two ports share each of the Pico's two PWM outputs, `J8` with `J9` and `J10` with `J11`, so dimming one dims its partner.

The 180 Ω resistor is there for a bare LED board with no current limiting of its own. The camera lamps use an LED strip that limits its own current, so the resistor would only cost brightness. Each port has a solder jumper across its resistor, and the build bridges all four. The same bridge is what lets the 24 V fan run at full voltage from a port.

The three lamps each use about 920 mm of strip at roughly 10 W per metre, so about 9 W each. The housing fan is a 40 mm, 24 V fan on the fourth port. The Orange Pi's own heatsink fan is 5 V and plugs into the Orange Pi's FAN socket instead.

<ul class="bulleted-list">
  <li>Bridging the resistor jumpers: <a href="{{ '/hardware/electronics/installation/control-board-prep/' | relative_url }}">Preparing the control board</a></li>
  <li>Which lamp or fan is on which port: <a href="{{ '/hardware/electronics/connecting/' | relative_url }}">Connecting the components</a></li>
  <li>The strip and its cables: <a href="{{ '/hardware/helpers/led-strip/' | relative_url }}">LED strip</a>, and the lamp itself: <a href="{{ '/hardware/assembly/feeder/camera-lamp/' | relative_url }}">Camera lamp</a></li>
</ul>

## What is fused where

<ul class="bulleted-list">
  <li><strong>Mains side:</strong> the 10 A fuse in the inlet. It is ahead of the supply, so it does not protect anything on the 24 V side.</li>
  <li><strong>24 V side:</strong> the PSU jacks and their leads are not fused.</li>
  <li><strong>Control board:</strong> <code>F1</code> and <code>F2</code>, 1206 slow-blow fuses rated 10 A and 32 V DC, one in each leg of <code>J1</code>. Nothing after them is fused: not the LED ports, the driver sockets, or the 12 V, 6.5 V and 5 V outputs. The reverse-polarity diode <code>D2</code> is rated 8 A, so it is the weaker part in a reversed-supply event.</li>
  <li><strong>Orange Pi branch:</strong> only the buck converter's own protection.</li>
</ul>

A 10 A fuse opens on a dead short, not on a modest overload. The supply's own overload point is roughly 16 to 20 A (110 to 140% of 14.6 A), and between a barrel jack's 5 A rating and that point nothing opens.

<ul class="bulleted-list">
  <li>Board fuse and diode parts: <a href="https://github.com/basicallysource/sorter-v2/blob/main/electronics/KiCad/1_Distribution_Board/Power.kicad_sch"><code>Power.kicad_sch</code></a></li>
</ul>

## Ratings: cables and connectors

The harness uses tinned, stranded UL1007 wire rated 300 V. It gives gauge and colour for each cable but no ampere rating for the wire itself. Red is +24 V and black is ground on every two-conductor power cable.

<table>
  <thead><tr><th>Part</th><th>Rating or spec</th><th>Where it is used</th></tr></thead>
  <tbody>
    <tr><td>18 AWG (0.82 mm²), red and black</td><td>UL1007, 300 V</td><td><code>PSU1</code> to <code>PSU3</code> (100 mm), <code>PWR1</code> (920 mm)</td></tr>
    <tr><td>22 AWG (0.33 mm²), red and black</td><td>UL1007, 300 V</td><td><code>PWR2</code> (310 mm), <code>PWR3</code> (150 mm), <code>LED1a</code> to <code>LED3a</code> (920 mm), <code>LED1</code> to <code>LED3</code> (150 mm)</td></tr>
    <tr><td>24 AWG (0.20 mm²), blue, green, red, black</td><td>UL1007, 300 V. Set by the JST-PH contact limit</td><td><code>STP1</code> to <code>STP4</code> (1 m), <code>CHU1</code> (300 mm tail)</td></tr>
    <tr><td>IEC C14 inlet with switch and fuse</td><td>Switch 15 A 250 V, fuse 10 A</td><td>Mains side of the supply</td></tr>
    <tr><td>Insulated fork terminal, M3.5</td><td>18 AWG wire, 8 mm wide at most</td><td>Both leads of <code>PSU1</code> to <code>PSU3</code>, onto the supply's terminal block</td></tr>
    <tr><td>Barrel jack and plug, 5.5 × 2.1 mm</td><td>5 A or better, centre positive</td><td><code>PSU1</code> to <code>PSU3</code>, <code>PWR1</code> to <code>PWR3</code>, <code>LED1</code> to <code>LED3</code>, <code>LED1a</code> to <code>LED3a</code></td></tr>
    <tr><td>JST VH header <code>J1</code>, housing VHR-2N, contact SVH-21T-P1.1</td><td>7 A with 18 AWG wire in the shrouded header</td><td><code>PWR1</code> into the board</td></tr>
    <tr><td>Clamp-on LED strip connector, 8 mm</td><td>3 A maximum</td><td>One per camera lamp</td></tr>
    <tr><td>Dupont, JST-PH, #187 quick-connect</td><td>No current rating given</td><td>Dupont on <code>LED1a</code> to <code>LED3a</code> and <code>LIM1</code>, JST-PH on <code>STP1</code> to <code>STP4</code> and <code>CHU1</code>, #187 on the limit switch</td></tr>
  </tbody>
</table>

The weakest rated link in the board's 24 V path is the barrel jack at 5 A, then the VH header at 7 A, then the 10 A fuses. The order page asks for "5 A or better" on every barrel line.

<ul class="bulleted-list">
  <li>Gauges, lengths and connectors for every cable: <a href="{{ '/hardware/parts/harness-order/' | relative_url }}">Ordering the wire harness</a></li>
  <li>The RFQ text with the wire spec: <a href="https://github.com/basicallysource/sorter-v2/blob/main/electronics/wire_harness/rfq.txt"><code>electronics/wire_harness/rfq.txt</code></a></li>
</ul>

## Ratings: devices

<table>
  <thead><tr><th>Device</th><th>Rating</th><th>Where it is in the machine</th></tr></thead>
  <tbody>
    <tr><td>Mean Well LRS-350-24</td><td>24 V, 14.6 A, 350 W. Mains draw 6.8 A at 115 V or 3.4 A at 230 V</td><td>The only supply; three outputs</td></tr>
    <tr><td>NEMA 17 stepper, StepperOnline 17HE15-1504S</td><td>1.5 A per phase, 2.3 Ω per phase. Default IRUN 4 (channels) and 8 (carousel)</td><td>Three feeder channels and the carousel, on <code>STP1</code> to <code>STP4</code></td></tr>
    <tr><td>NEMA 23 stepper, StepperOnline 23HS32-4004S</td><td>4.0 A per phase, 0.65 Ω per phase. Default IRUN 16</td><td>The chute, on <code>CHU1</code></td></tr>
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

The one place a motor can ask for more than its supply gives is the 6.5 V ServoV rail. A stalled MG995 takes about 1.2 A against the converter's 1.5 A, so two flaps stalling together are over it.

<ul class="bulleted-list">
  <li>Every part's attributes: <a href="https://github.com/basicallysource/sorter-v2/blob/main/parts-calculator/catalog/parts.json"><code>parts-calculator/catalog/parts.json</code></a></li>
</ul>

## Load against supply

The supply can give 350 W. The three camera lamps are about 28 W of that, or about 1.2 A at 24 V. The motors draw what their drivers are set to give (see above), and the Orange Pi branch tops out at the buck converter's 25 W. The supply, the jacks and the cables are well inside their ratings in normal use.
