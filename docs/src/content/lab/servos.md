---
layout: default
title: The servos and the layer adapter boards
type: explanation
section: lab
slug: lab-servos
kicker: Design and research — Electronics
lede: "How the chute doors are moved: the servo chip on the control board, the ribbon cable down the stack, and what each layer's adapter board does."
permalink: /lab/servos/
audience: curious builder or contributor
applies_to: hardware-v2
owner: docs
warning: >-
  **AI-generated first draft.** Written from the Pico firmware, the control program and the board's
  KiCad files, not from an actual build. The part names, pins and numbers are read from those files and
  have not been checked against a built machine.
---

Every distribution layer has a door. When the chute has turned to the right column of bins, the door of the right layer opens and the piece drops into the bin below it. One **servo** opens and closes each door. A servo is a motor that turns to an angle you tell it, and holds there, instead of turning round and round like the [stepper motors]({{ '/lab/motors/' | relative_url }}). It is told the angle by a signal, a stream of pulses, where the length of each pulse sets the angle.

The signals are made by one chip on the control board and travel down the stack on a ribbon cable. Each layer has a small board that picks its own signal off the ribbon and passes the rest on.

<ul class="bulleted-list">
  <li><strong>The servo:</strong> an MG995, one per layer.</li>
  <li><strong>The servo chip:</strong> a PCA9685 on the control board.</li>
  <li><strong>The ribbon cables:</strong> one long one from the control board to the first layer, and a short one from each layer to the next.</li>
  <li><strong>The layer adapter board:</strong> one per layer, which feeds the servo and passes the ribbon on.</li>
</ul>

## The servo

The MG995 is a standard-size hobby servo with metal gears. The catalog specifies the 180° positional version, which turns to any angle across a 180° range and not the continuous-rotation one. Its signal is a pulse from 500 to 2500 µs long, repeated 50 times a second, and 1500 µs is the centre. It runs on 6.5 V from the control board's "ServoV" rail, and its current figures and the load on that rail are on [Power distribution]({{ '/lab/power/' | relative_url }}). It has a 300 mm lead with a 3-wire plug: brown ground, red servo power, orange signal.

<ul class="bulleted-list">
  <li>The servo in its bracket, and the door it moves: <a href="{{ '/hardware/assembly/distribution/chute/door-module/' | relative_url }}">Door module</a></li>
  <li>Where the layers and doors sit in the whole machine: <a href="{{ '/lab/sorter/' | relative_url }}">How the sorter is put together</a></li>
  <li>The servo in the catalog: <a href="https://github.com/basicallysource/sorter-v2/blob/main/parts-calculator/catalog/parts.json"><code>parts-calculator/catalog/parts.json</code></a> (<code>servo-mg995</code>)</li>
</ul>

## The servo chip

The PCA9685 is a chip that makes up to 16 servo signals by itself. Once it has been told an angle it keeps sending that signal without any more help, so the Pico does not have to keep time for the servos. The Pico talks to it over I²C, a two-wire connection between chips, on the pins listed on [What is connected to the Pico]({{ '/lab/pico/' | relative_url }}). The chip answers at address 0x40 and has its own 25 MHz crystal.

<ul class="bulleted-list">
  <li><strong>Voltage levels:</strong> the Pico's I²C wires run at 3.3 V and the chip's at 5 V, so a small level-shifter chip (a PCA9306) sits between them.</li>
  <li><strong>The signals:</strong> the firmware sets the chip to 50 pulses a second. A pulse of 0.5 to 2.5 ms is 0 to 180°.</li>
  <li><strong>The outputs:</strong> 10 of the chip's 16 outputs go to the ribbon cable, each through a 220 Ω resistor.</li>
  <li><strong>At start-up:</strong> the firmware resets the chip, and sets every output to no pulse at all, which the firmware treats as safe for any servo.</li>
</ul>

<ul class="bulleted-list">
  <li>Chip driver: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/PCA9685.cpp"><code>PCA9685.cpp</code></a></li>
  <li>The chip's part of the schematic: <a href="https://github.com/basicallysource/sorter-v2/blob/main/electronics/KiCad/1_Distribution_Board/815.kicad_sch"><code>815.kicad_sch</code></a>, a sheet of the <a href="https://github.com/basicallysource/sorter-v2/tree/main/electronics/KiCad/1_Distribution_Board">control board's KiCad project</a></li>
</ul>

## How a servo is moved

The Orange Pi sends servo commands: move to an angle, set speed and acceleration limits, and release. The firmware does the moving. It works in tenths of a degree, speeds the servo up, then slows it down towards the target, and the signal is turned off when the servo arrives (the release), so the servo does not keep pushing and heat up. If a servo is blocked and never arrives, the firmware releases it anyway after at most 3.5 seconds.

Which angle is open and which is closed differs from one layer to the next, so the software has no machine-wide default. Each layer's open and closed angle is calibrated and saved, and a layer is only used once both are set. By default the servos are taken in order: the first layer's servo is the chip's first channel, the second layer's the second, and so on. The settings file can change that, and can reverse a servo.

The software has a second servo backend for a different kind of servo (the Waveshare bus servos). This page covers the PCA9685 one, which is the one the layer adapter boards and the MG995 on the hardware pages go with.

<ul class="bulleted-list">
  <li>Motion and release: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/Servo.cpp"><code>Servo.cpp</code></a></li>
  <li>Commands, Orange Pi side: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/hardware/sorter_interface.py"><code>hardware/sorter_interface.py</code></a></li>
  <li>Layer to servo assignment: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/machine_platform/servo_controller.py"><code>machine_platform/servo_controller.py</code></a></li>
  <li>The open and closed angles in the settings file: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/machine.example.toml"><code>software/machine.example.toml</code></a></li>
</ul>

## Why these servos and this wiring

<ul class="bulleted-list">
  <li><strong>The MG995.</strong> The first version used small 9 g servos, which sometimes stalled under the weight of the doors (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1441422214745292864">November 2025</a>). A step to a slightly stronger servo was considered, but the choice was to go further, because it is better to downgrade later than to find out a servo is too weak (<a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1441422457511743542">same thread</a>). One designer thought the MG995 has too much torque and suggested smaller servos, and noted that a hobby servo's signal can only be updated 50 times a second (<a href="https://discord.com/channels/1430279849171222682/1457600314197672056/1458872173950271588">January 2026</a>).</li>
  <li><strong>Serial servos instead (planned).</strong> Servos that report their angle and load over a serial bus were proposed in <a href="https://discord.com/channels/1430279849171222682/1437436041685631129/1456688787257163860">January 2026</a>. They need no servo chip, only one adapter board, but one builder noted they cost about four times as much as an MG995. The decision was to <a href="https://discord.com/channels/1430279849171222682/1521832972385255507/1522004871606440017">go ahead with the MG995</a> and move to serial servos later, and that is still the plan: the machine described on this page is not changed yet. The software already has a second backend for them, as described above. What is known so far:
    <ul class="bulleted-list">
      <li>The candidate is the Waveshare SC15. It has two ports and daisy-chains with no breakout board. Dropping a stepper channel frees a Pico UART to drive the chain, and the PCA9685 and the servo connectors would go, so the control board could roughly halve. The Pico's two real UARTs are both used by the stepper drivers, so the firmware would need a software serial port (18 October 2026 meeting). FEETECH SCS15 servos, the same servo with another connector, were bought as an alternative source. They are untested so far.</li>
      <li>No PWM is needed, which simplifies the control board (<a href="https://discord.com/channels/1430279849171222682/1430279852015091804/1564279189585002649">October 2026</a>).</li>
      <li>They report back their actual angle and whether they are stalled (<a href="https://discord.com/channels/1430279849171222682/1430279852015091804/1564308322826461318">October 2026</a>).</li>
    </ul>
  </li>
  <li><strong>A slip ring instead of the cable chain.</strong> It was considered. One that fits was not easy to find in every part of the world, at a good cost, and the output at the bottom was important (<a href="https://discord.com/channels/1430279849171222682/1430279852015091804/1564232083835195493">October 2026</a>). It would also have to carry high power plus ten PWM signals, one per layer (<a href="https://discord.com/channels/1430279849171222682/1430279852015091804/1564232139489419275">same day</a>), and a ring big enough has to leave the 120 mm centre hole open (<a href="https://discord.com/channels/1430279849171222682/1430279852015091804/1564239498689126611">same day</a>). Serial servos would cut the signals to a few wires, so it may be worth another look then (<a href="https://discord.com/channels/1430279849171222682/1430279852015091804/1564232327133925377">same day</a>). Open points: whether the servos tolerate noise on the line while the ring turns, which could be handled by only talking while the ring is still (<a href="https://discord.com/channels/1430279849171222682/1430279852015091804/1564232488581201984">same day</a>), and that I²C over a slip ring is risky (<a href="https://discord.com/channels/1430279849171222682/1430279852015091804/1564272457878085717">same day</a>). Mounting the ring at the bottom also makes the bin tub harder to get in and out (<a href="https://discord.com/channels/1430279849171222682/1430279852015091804/1564243643735347300">same day</a>). Nothing is decided.</li>
  <li><strong>Hobby servos over solenoids.</strong> Solenoids on the flaps were thought about but never tried. Servos turned out cheaper, because hobby servos are made in huge numbers and solenoids do not come in the shape needed. A solenoid would also need a return spring (<a href="https://discord.com/channels/1430279849171222682/1430279852015091804/1564273779373248624">October 2026</a>, <a href="https://discord.com/channels/1430279849171222682/1430279852015091804/1564277519753019464">same day</a>).</li>
  <li><strong>6.5 V for the servos.</strong> The MG995 is rated from 4.8 to 7.2 V, which makes 5 V uncomfortably close to the bottom, and torque is much higher at 6.5 V with more margin (<a href="https://discord.com/channels/1430279849171222682/1437436041685631129/1474044287447470286">February 2026</a>). The servo rail is made by a switching converter, not a simple regulator, because a regulator would waste a lot of power at the 2 A or more that one servo needs at its peak (<a href="https://discord.com/channels/1430279849171222682/1457600314197672056/1458858986072707137">January 2026</a>).</li>
  <li><strong>Boards that are all identical.</strong> The idea of one flat cable down the stack, with a small passive board per layer that takes its own signal and passes the others on shifted by one place, came from <a href="https://discord.com/channels/1430279849171222682/1437436041685631129/1439995208342306906">November 2025</a>. It means every board is identical.</li>
  <li><strong>Ten layers.</strong> The layer count was a limit that the team accepted from the start: it was suggested that the estimated layer count for this version be the upper limit (<a href="https://discord.com/channels/1430279849171222682/1437436041685631129/1439995790667022486">November 2025</a>), and the maximum later stated is <a href="https://discord.com/channels/1430279849171222682/1436755462346510386/1450497603690168455">ten</a>. The chip has 16 outputs and the firmware reports 16 servos when it finds the chip, but only ten reach the ribbon cable. In <a href="https://discord.com/channels/1430279849171222682/1437436041685631129/1478977064181694548">March 2026</a> lowering the maximum to 8 layers was discussed.</li>
  <li><strong>The servo chip.</strong> The servo signals come from a PCA9685 chip, not from the Pico's own pulse outputs. One of the original designers gave three reasons (<a href="https://discord.com/channels/1430279849171222682/1558828457096384543/1559101147090780161">October 2026</a>): the Pico did not have enough free pins, the chip let the team prototype faster, and it was familiar, because it had already been used on the previous sorter. Driving the servos from the Pico directly would also have needed level shifters and extra microcontrollers, and the custom boards were still far away at the time. At the first schematic review the Pico's own outputs were suggested as an alternative (<a href="https://discord.com/channels/1430279849171222682/1455320439554441358/1455655933488140442">December 2025</a>), and the board designer wondered about them too (<a href="https://discord.com/channels/1430279849171222682/1437436041685631129/1455305746437767288">December 2025</a>). The chip started as an add-on module and is now on the control board, so a machine needs only one board (<a href="https://discord.com/channels/1430279849171222682/1437436041685631129/1494941858143404103">April 2026</a>).</li>
</ul>

## The ribbon cables

The signals and the servo power travel on 16-pin flat ribbon cables (two rows of eight pins, 2.54 mm apart, with a keyed plug at each end so it only goes in one way up). The cable has the same layout everywhere:

<ul class="bulleted-list">
  <li><strong>Three wires</strong> carry the 6.5 V servo power.</li>
  <li><strong>Three wires</strong> carry ground.</li>
  <li><strong>Ten wires</strong> carry the ten servo signals, one for each output of the chip that reaches the ribbon.</li>
</ul>

There are two kinds. The long one (1.2 to 1.5 m, called `RIB1`) runs from the control board to the first layer. A short one (300 mm, called `RIB2`) links each layer to the next. A machine uses two short ones for three layers, or four for five layers. Which socket each end goes into is on [Connecting the components]({{ '/hardware/electronics/connecting/' | relative_url }}) and on the [layer adapter board]({{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}) page.

## What a layer adapter board does

The layer adapter board is the in-house board with one servo on it. It has two identical ribbon sockets, `J3` for the cable coming in and `J4` for the cable going on to the next layer, and a 3-pin header `J5` for the layer's servo. Its job is to give this layer's servo its own signal, and to pass everything else on.

<ul class="bulleted-list">
  <li><strong>Power and ground pass straight through.</strong> The three power wires and the three ground wires on <code>J3</code> are connected to the same ones on <code>J4</code>, so every layer gets the 6.5 V.</li>
  <li><strong>The first signal goes to the servo.</strong> Of the ten signals on <code>J3</code>, the first one is joined to the servo header <code>J5</code>, through a 0 Ω resistor, which is only a link that can be removed or swapped. A 10 kΩ resistor to ground keeps that wire at 0 V whenever nothing is driving it.</li>
  <li><strong>The other nine signals move up one place.</strong> They pass to <code>J4</code>, each one position earlier than it came in. So the second signal on the cable arrives at the next board as its first signal, and that board sends it to its own servo.</li>
  <li><strong>The end of the chain is held low.</strong> That shift leaves one empty place at the end of <code>J4</code>. A solder jumper, <code>JP1</code>, which is bridged, ties it to ground.</li>
  <li><strong>Capacitors smooth the power.</strong> A 100 µF, a 1 µF and a 100 nF capacitor sit across the 6.5 V, to smooth that supply.</li>
</ul>

Because every board passes on the signals shifted by one, all the boards are identical and need no setting. The first layer's servo always takes the first signal, the second layer's takes the second, and so on. It also means a board fed on `J4` instead of `J3` gets no signal, and every layer below it moves the wrong door. With ten signals on the cable, one chain of boards can serve up to ten layers.

The board has some extra pin headers that carry the same signals and power: two 10-pin ones, `J1` and `J2`, which match `J3` and `J4`, and two 4-pin ones, `J6` and `J7`, for the power. The assembly pages use only `J3`, `J4` and `J5`.

<ul class="bulleted-list">
  <li>Mounting the board and plugging in the cables and the servo: <a href="{{ '/hardware/assembly/distribution/chute/pcb/' | relative_url }}">Layer adapter board</a></li>
  <li>The board's schematic and layout: <a href="https://github.com/basicallysource/sorter-v2/tree/main/electronics/KiCad/0_Adapter_Board"><code>electronics/KiCad/0_Adapter_Board</code></a></li>
  <li>The ribbon cables in the catalog: <a href="https://github.com/basicallysource/sorter-v2/blob/main/parts-calculator/catalog/parts.json"><code>parts-calculator/catalog/parts.json</code></a> (<code>cable-idc-2x8-long</code>, <code>cable-idc-2x8-short</code>, <code>layer-adapter-board-basically</code>)</li>
</ul>
