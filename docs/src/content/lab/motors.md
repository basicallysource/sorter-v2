---
layout: default
title: The motors
type: explanation
section: lab
slug: lab-motors
kicker: Design and research — Electronics
lede: The five stepper motors, what each one turns, how their driver chips are set up, and how the machine notices that one is blocked.
permalink: /lab/motors/
audience: curious builder or contributor
applies_to: hardware-v2
owner: docs
warning: >-
  **AI-generated first draft.** Written from the Pico firmware, the control program and the board's
  KiCad files, not from an actual build. The part names, pins and numbers are read from those files and
  have not been checked against a built machine.
---

A stepper motor turns in small, fixed steps, one for each pulse it is sent. The machine has five. They turn the feeder rotors and the chute. The servos that open the chute doors are a different kind of motor, covered on [The servos and the layer adapter boards]({{ '/lab/servos/' | relative_url }}). The Orange Pi decides what to do, the Pico makes the pulses, and a driver chip next to each motor turns the pulses into current in the motor's coils (the wire windings that make it turn).

## The five steppers

<ul class="bulleted-list">
  <li><strong>Three feeder channel rotors (C1, C2 and C3).</strong> Each turns the rotor that moves LEGO along its C-channel.</li>
  <li><strong>The carousel.</strong> This is the rotor of the classification channel (C4), which the software calls the carousel.</li>
  <li><strong>The chute.</strong> It turns the whole stack of distribution layers as one unit, so that the chute points at a column of bins. The gears between the motor and the stack are described on [How the sorter is put together]({{ '/lab/sorter/' | relative_url }}).</li>
</ul>

The four feeder motors are **NEMA 17** and the chute motor is a larger **NEMA 23**. NEMA is the standard that sets a motor's frame size and mounting holes, and the number is the width of its square face in tenths of an inch. The catalog lists them as follows:

<ul class="bulleted-list">
  <li><strong>NEMA 17:</strong> StepperOnline 17HE15-1504S, 42 × 42 mm face, 38 mm body, 42 Ncm holding torque (the force it holds against when it is not turning).</li>
  <li><strong>NEMA 23:</strong> StepperOnline 23HS32-4004S, 57 × 57 mm face, 82 mm body, 2.4 Nm holding torque.</li>
  <li><strong>Both:</strong> 1.8° per step, which is 200 steps for one turn, and two coils (bipolar, two phase).</li>
</ul>

The current and resistance of each coil, and the motors' place in the power budget, are in the device table on [Power distribution]({{ '/lab/power/' | relative_url }}). The motors run on the 24 V rail.

<ul class="bulleted-list">
  <li>Which socket each motor goes in: <a href="{{ '/hardware/electronics/connecting/' | relative_url }}">Connecting the components</a></li>
  <li>The cables and the coil order: <a href="{{ '/hardware/electronics/wire-harness/' | relative_url }}">Wire harness</a></li>
  <li>The motor entries: <a href="https://github.com/basicallysource/sorter-v2/blob/main/parts-calculator/catalog/parts.json"><code>parts-calculator/catalog/parts.json</code></a> (<code>motor-nema17</code>, <code>motor-nema23</code>)</li>
</ul>

## The drivers

There are five TMC2209 stepper drivers, one per motor, each a small module with a heatsink that plugs into a socket on the control board. Each motor socket is wired to the driver printed beside it, so that driver has to carry the address for that motor (a number set by jumpers on the board, see [Preparing the control board]({{ '/hardware/electronics/installation/control-board-prep/' | relative_url }})).

Movement and configuration use two separate paths. The Pico makes the step pulses and sets the direction on each driver's STEP and DIR pins, and the firmware speeds the motor up and slows it down smoothly. The TMC2209 itself is set up over its UART line (a serial connection that the Pico shares between the drivers): the motor current, the microstepping (dividing each step into smaller ones for smoother movement) and the stall detection. All five drivers also share one enable pin that has to be switched on before any motor will turn. The Pico pins for all of this are in the table on [What is connected to the Pico]({{ '/lab/pico/' | relative_url }}).

When the machine starts, the Orange Pi writes each driver's settings and checks that the driver accepted every one. The control program sets 8 microsteps and a top speed of 4000 steps per second for the feeder rotors and the carousel, and 3000 for the chute. A motor whose driver did not take its settings would run at the wrong current, so the control program raises a fault instead of carrying on.

<ul class="bulleted-list">
  <li>Step generation and motion: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/Stepper.cpp"><code>Stepper.cpp</code></a></li>
  <li>Driver setup over UART: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/TMC2209.cpp"><code>TMC2209.cpp</code></a> and <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/TMC_UART.cpp"><code>TMC_UART.cpp</code></a></li>
  <li>What the Orange Pi writes at start-up: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/irl/config.py"><code>irl/config.py</code></a></li>
</ul>

## How much current a motor gets

A stepper motor's rated current is a limit, not what it always draws. The driver controls the current in the motor's coils and does not take more from the supply than the motor needs. So a 4 A NEMA 23 motor on a 2 A driver is normal: it just produces a smaller share of its rated torque (turning force).

**Two places set the real current, and they multiply.** The small adjustable pot (trimmer) on each driver module sets a maximum. The software then sets the run current and the hold current, called IRUN and IHOLD, each a number from 0 to 31, as fractions of that maximum. If you leave the pot high and also raise IRUN in the software, the current goes up twice, so the motor can get much hotter than either setting alone suggests. The defaults are set in the control program:

<ul class="bulleted-list">
  <li>Feeder channel rotors: IRUN 4, IHOLD 1</li>
  <li>Carousel: IRUN 8, IHOLD 1</li>
  <li>Chute, and any stepper without its own entry: IRUN 16, IHOLD 4</li>
</ul>

Each can be changed for one stepper in the machine's settings file (a TOML file).

<ul class="bulleted-list">
  <li>Defaults and the validation of overrides: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/irl/parse_user_toml.py"><code>irl/parse_user_toml.py</code></a></li>
  <li>The commented override example: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/machine.example.toml"><code>software/machine.example.toml</code></a></li>
</ul>

## Stall detection

Each driver has a **DIAG** pin that carries one thing: stall detection (the TMC2209 calls this StallGuard). A stall is when the motor is blocked and cannot turn. The driver turns DIAG on when it senses that the motor is being held back while it turns. The firmware checks the pin every time it updates the motor's movement. When it is on, the firmware stops that stepper at once and remembers that it stalled. The Orange Pi asks the Pico for these stall records over USB, and it then raises a "stepper stall" incident, a message that stops the machine. It does not clear the incident on its own, because a person has to look at the machine.

The earlier v1.1 board has no DIAG routing, so a setting on the Orange Pi turns the whole stall check off.

<ul class="bulleted-list">
  <li>Firmware side: the stall check in <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/Stepper.cpp"><code>Stepper.cpp</code></a>, with the DIAG pin numbers in <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/firmware/sorter_interface_firmware/hwcfg_basically_v1_2.h"><code>hwcfg_basically_v1_2.h</code></a></li>
  <li>Orange Pi side: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/stepper_stall_monitor.py"><code>stepper_stall_monitor.py</code></a></li>
</ul>

## Why these motors and drivers

The reasons below are what was written down in the Discord and the engineering meetings. Where the reason is not known yet, the page says so.

<ul class="bulleted-list">
  <li><strong>A NEMA 23 for the chute.</strong> The chute has to turn the whole stack of layers, ten layers high, a full turn in under three seconds. That figure is a throughput target that one of the engineers proposed at the <a href="https://www.youtube.com/watch?v=7Z1wlY-plNo&t=1146s">5 December 2025 meeting</a> ("if we want to keep any throughput"), not a measured requirement, and the meeting planned to pick a motor with about twice the torque it takes. At the <a href="https://www.youtube.com/watch?v=TOuqbUtFj0I&t=4734s">10 January 2026 meeting</a> it was restated as the ring turning in three seconds, worked out as 25 to 30 rpm at the chute, which through the 5 to 1 gearing of the time is about 150 rpm at the motor. A NEMA 17 prototype could not reach that speed. At the same meeting an earlier pencil calculation was quoted: a ten-layer stack needs at least the largest NEMA 17 that StepperOnline sells. A gearbox was ruled out because it trades away the speed that is needed. The decision was to go to a NEMA 23, with the remark that it is easier to go down in size later than up, and with the point that the larger frame also opens up many more motors to choose from. The feeder channels stayed on NEMA 17.</li>
  <li><strong>The chute motor model.</strong> The chute uses a 4 A, 2.4 Nm NEMA 23 (StepperOnline 23HS32-4004S), the same model the designer already had. The January meeting compared against a smaller NEMA 23 (0.9 Nm, 2 A), and the 2.4 Nm model first shows up in the Discord on <a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1488161457517498378">30 March 2026</a>, when a builder bought it. Their reason, given afterwards in the <a href="https://discord.com/channels/1430279849171222682/1558831358263038024/1559098205034254357">design question thread</a>: it is the same motor the designer had, the price difference to the smaller NEMA 23 on the bill of materials was under four dollars, and they would rather have torque to spare than too little, since the chute is a large mass that is moving all the time. That is a buyer's reasoning on the model, not a torque calculation or a test, and no calculation or test choosing 2.4 Nm has been found. The 4 A is the motor's limit, not a current the driver has to supply (see "How much current a motor gets" above).</li>
  <li><strong>TMC2209 drivers.</strong> They were proposed in <a href="https://discord.com/channels/1430279849171222682/1437436041685631129/1442957384895955119">November 2025</a> because Klipper supports Trinamic drivers, and another builder replied that for NEMA 17 motors the Trinamic drivers are hard to beat. Another point was that the drivers are standard 3D printer parts, so they are easy to source. One designer noted that separate enclosed drivers would mean extra wiring and harnesses, and suggested socketed driver modules instead.</li>
  <li><strong>The same driver on the chute.</strong> The chute's NEMA 23 also runs on a TMC2209 "for now", because no limit had been hit on the chute yet (<a href="https://discord.com/channels/1430279849171222682/1437436041685631129/1539252532402987088">August 2026</a>).</li>
  <li><strong>Stall detection with the driver's own DIAG pin.</strong> The purpose, from the <a href="https://www.youtube.com/watch?v=PBEk7i_vIVY">29 March 2026 meeting</a>: if a motor stalls, the software knows it has lost its position, and can try to home it again or ask the user to come and look. For catching a jammed chute it was called <a href="https://discord.com/channels/1430279849171222682/1437144782819426537/1494035284977778820">"our only strategy"</a>, because the alternatives would be cameras or other sensors on every layer. No written decision compares it with an encoder. An encoder on the chute motor is being tried as a variant, on <a href="{{ '/lab/variants/' | relative_url }}">Tested variants</a>.</li>
</ul>

## The chute stepper and its home position

The Orange Pi homes the chute stepper, meaning it turns the chute back to the limit switch (on [What is connected to the Pico]({{ '/lab/pico/' | relative_url }})) to find the known starting angle, and then turns it to the angle of a bin. The firmware counts the steps, and the Orange Pi works in degrees. A stalled chute loses its home position, so it has to be homed again before sorting continues.

<ul class="bulleted-list">
  <li>Chute homing and aiming, Orange Pi side: <a href="https://github.com/basicallysource/sorter-v2/blob/main/software/sorter/backend/subsystems/distribution/chute.py"><code>subsystems/distribution/chute.py</code></a></li>
  <li>What you do with it as an operator: <a href="{{ '/sorter/chute-calibration/' | relative_url }}">Chute calibration</a></li>
</ul>
