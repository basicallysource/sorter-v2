---
title: Software architecture decisions
type: explanation
audience: contributor understanding the software stack
applies_to: sorter 2.x
owner: lab
last_verified: 2026-04-14
section: lab
slug: lab-software-architecture-decisions
kicker: Lab — Research Area
lede: Why Sorter V2 uses a dumb-firmware / smart-host split, what alternatives were evaluated, and the design principles that guide the stack.
permalink: /lab/software-architecture-decisions/
---

## The question

Why does Sorter V2 use a Klipper-inspired architecture with dumb firmware and a smart host, and what was rejected along the way?

## Why this matters

The firmware/host split is the most load-bearing architectural decision in the project. It determines where logic lives, how fast features can ship, which hardware is supported, and how contributors divide work. Understanding why this split exists prevents re-debating settled questions.

## The mental model

Two layers, strict separation:

| Layer | Hardware | Responsibility | Language |
|-------|----------|---------------|----------|
| **Firmware** | RP2040 (Raspberry Pi Pico) | Real-time: 10kHz step generation, 1kHz motion control, sensor reads, PWM | C++ |
| **Host** | Raspberry Pi 5 | Everything else: vision, classification, coordination, UI, sorting logic | Python + SvelteKit |

Communication: USB serial. The firmware sends a JSON config on startup describing its capabilities. The host sends commands; the firmware executes them. All actuators are addressable by name.

**Design principle:** "Bare minimum at every layer so we can pivot into features easily." — Spencer

## Firmware details

- **Two threads:** 10kHz stepgen thread (precise timing) + 1kHz motion control thread (trajectory planning).
- **Custom serial protocol.** Not Firmata, not gcode. Asynchronous commands with named actuators.
- **Stepper drivers:** 3× TMC2209 on a shared UART bus, addressable individually.
- **Timing constraint:** <10ms response to any USB message. The host must not micromanage — it sends goals, not individual steps.
- **Updates are rare.** Most development happens on the host side. Firmware changes only for new hardware support.

## Host details

- **Camera inference** runs in a separate thread to avoid blocking the main coordination loop.
- **State machines** per subsystem (feeder, distribution, carousel). Each reacts to signals from other subsystems independently.
- **Sorting logic:** `item_id` (part + color) → `category_id` → `bin`. MVP rule: "If category has a bin, use it; otherwise assign the next empty bin."
- **Classification:** Brickognize API (remote) with a planned local model for offline operation. Dual-mode: local for common parts, API for rare/uncertain.
- **Data output:** BrickStore XML export format for sellers to catalog sorted pieces.

## What was rejected

| Alternative | Why rejected |
|-------------|-------------|
| **Klipper** | Designed for 3D printers. Over-abstracted for sorting — carries assumptions about toolheads, bed geometry, and print-move semantics that do not map to sorting. |
| **ROS2** | Modularity is appealing, but the runtime weight and complexity are disproportionate for a single-machine sorting system. Too cumbersome for rapid iteration. |
| **Marlin** | Firmware-heavy — all logic lives on the MCU. Constrains feature development to C++ on resource-limited hardware. Cannot leverage Pi's compute for vision. |
| **Firmata** | V1 used Firmata. 7-bit encoding causes data mangling, the project is effectively dead, and threading behavior was unreliable. Abandoned after V1 experience. |
| **WiFi for MCU comms** | Non-deterministic latency. USB serial provides the consistent <10ms response time that real-time motion control requires. |
| **RS485 for multi-MCU** | Planned for future multi-machine setups (passing buckets between sorters for multi-phase sorts), but USB serial suffices for single-machine V2. |

## Trade-offs

- **Host-side logic vs firmware logic** — Keeping logic on the host means Python iteration speed but introduces serial latency. Acceptable because sorting decisions operate on ~100ms timescales, not microsecond timescales.
- **Custom protocol vs standard (gcode)** — A custom protocol fits the sorting domain better than repurposing 3D printer gcode. The cost is less ecosystem tooling — no existing slicers or visualizers.
- **Remote API vs local classification** — Remote API ships faster but needs internet. Local model needs training infrastructure. Dual-mode defers the hard choice.
- **Single MCU vs multi-MCU** — Current design uses one Pico. Multi-MCU (with time-synchronization for coordinated motion) is architecturally supported but not yet needed.

## What this is not

- **Not a recommendation for other projects.** This architecture fits a LEGO sorting machine with specific latency and throughput requirements. A pick-and-place robot or CNC machine has different constraints.
- **Not frozen.** The host-MCU split is stable, but the protocol, classification strategy, and deployment model are still evolving.

## Where to go next

- [Sorter architecture]({{ '/sorter/architecture/' | relative_url }}) — the detailed component map of coordinator, state machines, vision manager, and UI
- [Classification research]({{ '/lab/classification-research/' | relative_url }}) - the ML strategy behind the classification layer
- [C-channel singulation]({{ '/lab/c-channel-singulation/' | relative_url }}) - the mechanical system the firmware drives
