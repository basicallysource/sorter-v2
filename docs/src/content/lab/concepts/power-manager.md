---
layout: default
title: Push-button power manager
type: explanation
section: lab
slug: lab-power-manager-concept
kicker: "Design and research: Variants, Concepts"
lede: "A proposal to start the machine with one button and shut it down cleanly, by switching a Mean Well HRPG-150-24 supply through its remote-control input, with the Orange Pi shutting itself down before the 24 V goes away."
permalink: /lab/concepts/power-manager/
audience: contributor or builder interested in changing the electronics
applies_to: hardware-v2
owner: docs
author: soran82
warning: >-
  **Concept, not built, not simulated, not tested.** The component values are calculated, the part
  numbers are suggestions, and the firmware was only syntax-checked against a stub. Nothing on the build
  pages changes because of this page. Mains wiring must only be done by a qualified electrician.
---

This page summarises a concept proposal, draft 0.1 of 2026-10-21. It was written from the Sorter V2 documentation and KiCad files and from the Mean Well HRPG-150 datasheet (2017-07-14), and the author prepared it with the help of an AI assistant. The full document, including the part-by-part schematics and all the source code (the ATtiny firmware and the Orange Pi scripts), is the [concept PDF](https://assets.basically.website/sorter-docs/sorter-v2-power-manager-concept-dd1d13ce7eb7.pdf). The Sorter V2 pages it was read from are themselves marked as drafts that were not checked against a built machine, so every project detail in it should be confirmed against the KiCad files and the firmware.

## 1. Summary

<ul class="bulleted-list">
  <li><strong>Goal:</strong> start the machine with one button and shut it down cleanly. The Orange Pi has to finish its shutdown before the 24 V supply is switched off.</li>
  <li><strong>Approach:</strong> a small power manager (an ATtiny214) runs from the always-on 5 V auxiliary output of the HRPG-150-24 and drives the supply's remote-control input.</li>
  <li><strong>Fail-safe:</strong> the HRPG remote input is "open = on, shorted = off", so the concept uses a normally-closed photo-MOS relay. If the power manager is dead or unpowered, the supply stays off.</li>
  <li><strong>Isolation:</strong> the auxiliary ground (AUXG) is isolated from the 24 V output, so the power manager talks to the Orange Pi through two optocouplers.</li>
  <li><strong>Status light:</strong> a plain RGB LED (common anode, no data protocol) on its own cable, separate from the button.</li>
  <li><strong>Servo flaps:</strong> no per-layer adapter boards. The servos plug into the 3-pin ports of a PCA9685 servo-driver module, which gives up to 16 layers per module.</li>
  <li><strong>Automatic shutdown (optional):</strong> an Orange Pi service switches the whole machine off when no new piece has been sorted for a configurable time, using the backend's existing shutdown endpoint and the same path as the button.</li>
</ul>

## 2. What it re-uses and what it adds

| Provided by the Sorter V2 project (re-used) | Added by this concept |
|---|---|
| The "basically board v1.3" control board: Raspberry Pi Pico, five TMC2209 stepper drivers, 5 V, 12 V and 6.5 V (ServoV) rails, four LED ports, two switch inputs | A power manager at the HRPG-150-24 auxiliary output (button, remote on/off, shutdown handshake) |
| A PCA9685 servo driver (16 channels, I2C 0x40) with MG995 servos on 6.5 V | Direct servo connection to the module ports (no layer adapter boards, no ribbon cables) |
| The 24 V to 5 V USB-C converter for the Orange Pi, the USB hub and the three PSU jacks | An RGB status LED and a button as a separate control panel |
| An Orange Pi 5 (8 GB) with SorterOS | Two small systemd services and a GPIO configuration on the Orange Pi, plus an optional automatic-shutdown service |

Out of scope: the mechanical design, the sorter software, the mains-side wiring inside the PSU box, and a PCB layout. The author suggests that, if the idea turns out to be of interest, the power manager could be built into the distribution board. That is a change to the board design and is not proposed here.

## 3. System architecture

### Power paths

<ul class="bulleted-list">
  <li>Mains goes through the PSU box (fused IEC inlet with switch) into the HRPG-150-24 (24 V, 6.5 A, 156 W).</li>
  <li>The 24 V output feeds three loads through separate leads: the control board, the USB hub and the 24 V to 5 V USB-C converter for the Orange Pi.</li>
  <li>The auxiliary output (5 V, at most 0.3 A) stays live while the supply is switched off. It powers the power manager and the status LED.</li>
  <li>On the control board, 24 V is converted to 5 V, 12 V and 6.5 V (ServoV). ServoV feeds the PCA9685 module and the servos.</li>
</ul>

### Control and signal paths

| Signal | From to | Level or medium | Notes |
|---|---|---|---|
| RC+ / RC- | Power manager to HRPG | CN100 pins 6 and 5, dry contact (photo-MOS) | open = supply on, closed = off |
| REQ_N | Power manager to Orange Pi | optocoupler U5, 3.3 V on the Pi side | a 500 ms low pulse means "shut down now" |
| PWROFF | Orange Pi to power manager | optocoupler U4 | high for at least 500 ms means "the Pi is about to halt" |
| USB | Orange Pi to USB hub to Pico | USB | the project's normal communication (steppers, servos, lamps) |
| I2C | Pico to PCA9685 module | 3.3 V to 5 V through the PCA9306 | servo angles, with the 50 Hz PWM generated by the module |
| PWM_0 to PWM_15 | PCA9685 to servo ports | 5 V PWM, 220 ohm per output | one port per layer |

<figure class="single-figure">
  <img class="doc-figure" src="https://assets.basically.website/sorter-docs/power-manager-overall-schematic-w1600-c7d504118686.jpg" alt="Overall schematic of the proposal. On the left the mains input feeds the HRPG-150-24, whose 24 V output runs to the converter for the Orange Pi, the USB hub and the control board. Below the supply, a boxed power manager holds the ATtiny214, a normally-closed relay on the remote-control pins, two optocouplers to the Orange Pi, and the button and RGB LED. On the right, the control board's Pico drives a PCA9685 servo module with up to sixteen servo ports, plus the stepper drivers and LED ports.">
  <figcaption>Overall schematic. Red is 24 V, orange is the 5 V auxiliary output, purple is ServoV, green is the 3.3 V standby rail, black grounds are the 24 V side and blue grounds are the isolated auxiliary ground. <cite>Drawn from the concept proposal, not from a build. Drawing: Jan-Henning Grell (Soran82). <a href="https://assets.basically.website/sorter-docs/power-manager-overall-schematic-full-f8dd7bbc888f.png">Full-size image</a>.</cite></figcaption>
</figure>

## 4. What the HRPG-150 datasheet says

The signal connector is CN100 (mating housing HRS DF11-6DS). The pins used are:

| CN100 pin | Signal | From the datasheet |
|---|---|---|
| 1 | -S | Remote sense negative, not used |
| 2 | +S | Remote sense positive, not used |
| 3 | AUXG | Auxiliary ground, isolated from the output terminals (+V and -V) |
| 4 | AUX | 4.75 to 5.25 V, at most 0.3 A, not controlled by remote on/off |
| 5 | RC- | Remote control ground |
| 6 | RC+ | 4 to 10 V or open = power on; 0 to 0.8 V or short = power off |

Other values used: output 21.6 to 28.8 V adjustable (24 V nominal), 6.5 A and 156 W, overload protection at 105 to 135 % with constant-current limiting and automatic recovery, inrush typically 35 A at 115 V and 70 A at 230 V, setup time about 3 s. The datasheet also says "The 5V standby must be connected with a minimum load of 0.03 A."

| Datasheet fact | Design consequence |
|---|---|
| RC open = on, short = off | A normal (normally-open) relay would switch the supply on as soon as mains is applied. U2 is a normally-closed photo-MOS relay (1-Form-B). Unpowered, the contact is closed and the supply stays off. |
| AUX minimum load 30 mA | Resistor R14 (150 ohm, 0.25 W) draws about 30 mA from the 4.6 V rail. The regulator, ATtiny, LED and U2 add to this and stay below 0.3 A. |
| AUXG isolated from -V | The standby ground is not tied to the 24 V ground, so the Orange Pi interface uses two optocouplers (U4 and U5). |
| Output adjustable to 28.8 V | The 24 V to 5 V converter accepts up to 32 V, so the adjustment range is uncritical. |
| Constant-current limiting at 105 to 135 % | An overload does not trip a fuse. The total load has to be kept clearly below 6.5 A (section 8). |

## 5. The power manager

### Circuit blocks

| Block | Parts | Function |
|---|---|---|
| Supply | D2 (SS14), U1 (MCP1700-3302), C3 and C4 (1 uF), C5 (100 nF) | 3.3 V logic rail from the auxiliary output, so the ATtiny runs whenever mains is present |
| Remote switch | U2 photo-MOS 1-Form-B (for example G3VM-61B1 or AQY412), R4 220 ohm | shorts RC+ and RC- while its LED is off (supply off); the ATtiny lights the LED to open the contact (supply on) |
| Controller | U3 ATtiny214 (SOIC-14), UPDI header J2 | state machine, debouncing, LED control |
| Pi interface | U4 and U5 (PC817), R7, R9, R12, R13 | isolated handshake: REQ_N to the Pi, PWROFF from the Pi |
| Minimum load | R14 150 ohm / 0.25 W | satisfies the 30 mA minimum load on the auxiliary output |
| Control panel | SW1 push button, LED2 RGB LED (common anode), D4 (SS14), R3, R10, R11, R2, D3, C6 | button input with ESD protection, status output, LED supply from the auxiliary output |

### Sequence

| State | Event | Action |
|---|---|---|
| Off | short button press | U2's LED turns on, the remote input opens, the supply starts (about 3 s setup), state on |
| On | short button press | REQ_N goes low for 500 ms; the Orange Pi runs `systemctl poweroff` |
| On | PWROFF high for at least 500 ms | state "shutdown", latched even if the line drops again |
| Shutdown | after 25 s | U2's LED turns off, the remote input is shorted, the supply is off |
| On | button held for 8 s | emergency off immediately (for a hung Pi); the LED shows red for 1.5 s |
| On | sorting finished (optional watchdog, section 7) | the Pi shuts itself down, PWROFF follows, and the supply is switched off 25 s later |

A Pi reboot does not set PWROFF, so the supply stays on. After a mains failure the system stays off until the button is pressed (a constant, `AUTO_START`, can change this). The 25 s delay covers the file-system sync and the kernel halt after the shutdown service has signalled PWROFF.

### Failure behaviour

| Situation | Result |
|---|---|
| Power manager unpowered or dead | U2's contact is closed, so the supply stays off |
| Mains returns after a failure | the supply stays off until the button is pressed |
| Orange Pi hangs | hold the button for 8 s (emergency off); there is no clean shutdown, so file-system recovery may be needed |
| Cable to the control panel cut | the button reads open (no press) and the LED is dark; the machine can still be shut down from the Pi |
| PWROFF glitch on the Pi pin during boot | ignored unless the signal stays high for 500 ms |

### Control panel: button and RGB LED

The push button has no LED. Status is shown by an external RGB LED with a common anode on its own 4-wire cable (+4.6 V, red, green, blue). Button and LED connectors are separate so that either part can be replaced independently.

The LED is supplied with about 4.6 V (the auxiliary output through a Schottky diode) and not 3.3 V, because green and blue LEDs have about 3 V forward voltage, which leaves almost no current from a 3.3 V pin. With the anode at 4.6 V each colour carries about 5 mA. The ATtiny pins switch the cathodes: pin low = colour on, pin high (3.3 V) = off, because only about 1.3 V then remains across the LED and its resistor. The three LED pins must never be left high-impedance, because a floating cathode would rise towards 4.6 V and feed the 3.3 V rail through the ATtiny's protection diode. The firmware writes high first and then makes the pins outputs.

| LED | Meaning |
|---|---|
| dark, short green blink every 3 s | supply off, power manager waiting |
| blue | starting, the first 45 s after power-on (the Orange Pi booting; the time is an assumption) |
| green | running |
| yellow (red and green) fast blinking | shutdown requested, the Pi is shutting down |
| red slow blinking | the Pi has signalled PWROFF, the supply switches off in 25 s |
| red for 1.5 s | emergency off |

## 6. The Orange Pi side

Two small systemd units run next to the Sorter software. The full source is in Appendix B of the [concept PDF](https://assets.basically.website/sorter-docs/sorter-v2-power-manager-concept-dd1d13ce7eb7.pdf).

<ul class="bulleted-list">
  <li><code>powerctl-req.service</code> waits for a falling edge on REQ_N (with <code>gpiomon</code>) and runs <code>systemctl poweroff</code>.</li>
  <li><code>powerctl-off.service</code> runs only on poweroff or halt (not on reboot), before <code>poweroff.target</code>, and sets PWROFF high for 2 s with <code>gpioset</code>.</li>
  <li><code>/etc/default/powerctl</code> holds the GPIO chip and line numbers, which depend on the pins chosen on the header (check with <code>gpioinfo</code>).</li>
</ul>

The scripts use the libgpiod 1.x command-line syntax, so with libgpiod 2.x the options have to be adapted. The Orange Pi GPIOs are 3.3 V and not 5 V tolerant.

## 7. Automatic shutdown when sorting has finished

The power manager does not need to know about the end of a sorting job. Any Linux shutdown of the Orange Pi ends in the same path as the button: the shutdown service signals PWROFF, and the supply is switched off 25 s later. The machine can therefore switch itself off after sorting if software on the Pi starts a normal shutdown.

The Sorter V2 backend already provides `POST /api/system/shutdown`, which powers the whole machine down. What it does not provide is a "finished" signal, so the optional `powerctl-auto` watchdog defines "finished" as "no new pieces for a while":

<ul class="bulleted-list">
  <li>It polls <code>GET /api/system/status</code> and <code>GET /api/pieces/overview</code> on the loopback interface every 30 s.</li>
  <li>It arms itself only after at least one piece has been distributed since it started, so a machine that was just switched on and is still idle is never shut down.</li>
  <li>If the piece counters stay unchanged for <code>IDLE_MIN</code> minutes (default 20), the hardware state is ready and no hardware error is active, a grace period of <code>GRACE_S</code> seconds (default 60) starts. Any new piece, state change or error during the grace period cancels it.</li>
  <li>After the grace period it calls the shutdown endpoint once.</li>
  <li>If the backend is unreachable, the idle timer restarts, so a crashed or restarting backend never causes a shutdown.</li>
</ul>

The feature is off by default (`AUTO_SHUTDOWN=0`) and starts in a dry-run mode (`DRY_RUN=1`) that only logs what it would do. A paused machine cannot be told apart from a finished one over the REST API, so `IDLE_MIN` has to be generous. The watchdog logic was tested against a fake backend (five scenarios) and not against a real Sorter V2 backend. A proper "run finished" event in SorterOS would be a better trigger than inferring the end from silence.

## 8. Servo flaps

The Sorter V2 design connects one MG995 servo per layer. The signals come from a PCA9685 chip or module (16 outputs, 50 Hz PWM, I2C address 0x40); in the project, ten outputs are routed on a ribbon cable to passive per-layer adapter boards. This concept drops the layer boards and plugs the servos directly into the module's 3-pin ports (brown GND, red V+, orange PWM).

<ul class="bulleted-list">
  <li><strong>Capacity:</strong> 16 ports per module, so up to 16 layers instead of 10. A second module (for example at address 0x41) would allow 20 layers in hardware, but the project firmware only addresses 0x40, so a firmware change would be needed.</li>
  <li><strong>ServoV rail:</strong> the rail is rated 1.5 A (6.5 V, from the 12 V rail). A stalled MG995 draws about 1.2 A, so two stalled servos overload it. The project firmware releases a servo after at most 3.5 s.</li>
  <li><strong>Cable length:</strong> the servo lead is 300 mm. Higher layers need extension leads (3-core, 22 AWG or thicker). The 100 uF capacitor of the adapter board is missing at the servo, so add 100 to 220 uF across V+ and GND at the plug for long leads.</li>
</ul>

## 9. Open points

| # | Open point | Priority | Next action |
|---|---|---|---|
| 1 | **Total power budget not verified.** A rough upper bound from the project's own ratings is about 120 to 130 W: Orange Pi branch up to 25 W, hub and cameras about 5 to 10 W (assumption), three lamps about 28 W, fan 1 W, four NEMA 17 steppers up to about 40 W at full holding current, the NEMA 23 about 5 W at the driver limit, servo rail up to about 10 W, plus converter losses. | High | Measure the real 24 V current in all machine states (homing, sorting, lamps at full brightness) before relying on a 156 W supply. |
| 2 | **Servo rail 1.5 A.** Several simultaneously stalled servos overload it. | High | Limit concurrent moves in software, or size a stronger 6.5 V converter on the control board. |
| 3 | **U2 part selection.** The HRPG datasheet does not give the open-circuit voltage or short-circuit current of the RC pins. | High | Measure RC+ and RC- on the actual supply, and check the relay's LED current and voltage ratings. |
| 4 | **Supply protection.** The project's board fuses are 10 A, but the HRPG delivers only 6.5 A and relies on current limiting from 105 %. | Medium | Add a 6 to 8 A fuse in the 24 V feed, or accept the limiting behaviour after the measurement in point 1. |
| 5 | **Pin numbers and firmware.** The ATtiny214 pin numbers were not checked against the datasheet, and the firmware was only syntax-checked against a stub. | Medium | Verify the pinout, compile with megaTinyCore, and test on a bench setup with an LED and a dummy load. |
| 6 | **Project documentation status.** Several project pages are labelled as AI-generated first drafts. | Medium | Confirm details against the KiCad files, the firmware and the published v1.3 board schematic. |
| 7 | **More than 16 layers.** Needs a second PCA9685 module and a firmware change. | Low | Decide whether 16 layers are sufficient. |
| 8 | **No PCB layout.** | Low | Create it after the points above are closed, and keep the board low voltage only. |
| 9 | **Definition of "finished".** The backend has no finished state, so the watchdog infers it from missing pieces and cannot tell a pause from the end of a job. | Medium | Keep `IDLE_MIN` generous, start with `DRY_RUN=1`, confirm the port and endpoints on the real machine, and consider a real run-finished event in SorterOS. |

The concept describes the Orange Pi's GPIO header as a 40-pin header. The plain Orange Pi 5 has a 26-pin header and the Orange Pi 5 Pro has a 40-pin one, so which two pins are free and what they are called depends on the board in the machine.

## 10. Suggested next steps

<ol class="numbered-list">
  <li>Measure the 24 V load of a running machine, then decide on the supply and the fuse (points 1 and 4).</li>
  <li>Bench-test the power manager with the real HRPG-150-24: measure RC+ and RC-, the auxiliary-output load, and the start and stop sequence with a dummy load.</li>
  <li>Compile and flash the firmware, and check the LED colours and timing.</li>
  <li>Install the Orange Pi services, set the GPIO lines, and test the button shutdown and the PWROFF path end to end.</li>
  <li>Test the optional automatic shutdown with <code>DRY_RUN=1</code> on a real machine, then enable it.</li>
  <li>Test the servo ports with the longest planned leads and the added capacitors.</li>
</ol>

## Sources

<ul class="bulleted-list">
  <li>The <a href="https://assets.basically.website/sorter-docs/sorter-v2-power-manager-concept-dd1d13ce7eb7.pdf">concept PDF</a> (19 pages, with the full schematics and source code).</li>
  <li>The Sorter V2 repository: the <a href="{{ '/lab/power/' | relative_url }}">Power distribution</a>, <a href="{{ '/lab/servos/' | relative_url }}">servo</a> and <a href="{{ '/lab/pico/' | relative_url }}">Pico</a> pages, the board's KiCad files, and the backend files <code>server/routers/system.py</code> (shutdown endpoint) and <code>server/routers/pieces.py</code> (pieces overview).</li>
  <li>The Mean Well HRPG-150 series datasheet (HRPG-150-SPEC, 2017-07-14).</li>
</ul>
