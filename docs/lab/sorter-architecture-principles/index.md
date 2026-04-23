---
layout: default
title: Sorter Architecture Principles
type: explanation
audience: contributor reference
applies_to: sorter 2.x runtime and backend architecture
owner: lab
last_verified: 2026-04-23
section: lab
slug: lab-sorter-architecture-principles
kicker: Lab — Contributor Reference
lede: The active architectural guide for the Sorter backend and runtime: principles, ownership boundaries, and a practical audit loop for iterative improvement.
permalink: /lab/sorter-architecture-principles/
---

## Why this exists

The Sorter is too large and too hardware-bound to be steered well by one big
"target architecture" document forever. Those documents help for a while, but
they drift, details get missed, and local fixes slowly pull the codebase in
different directions again.

This page is the active guide instead:

- not a frozen blueprint;
- not a detailed package map;
- not an excuse for purity over progress.

It is a set of architectural **leitplanken**: the shared direction we want the
system to converge toward while we keep shipping, debugging, and refactoring.

## What this is not

- **Not a ban on pragmatism.** Temporary bridges and compromises are allowed.
- **Not a replacement for live verification.** The machine still has the last word.
- **Not a one-shot rewrite plan.** The system should improve iteratively.
- **Not a style guide.** This is about ownership, boundaries, and behavior.

## Core Principles

### 1. The hot path should be explicit

The core piece flow must be easy to trace.

For the Sorter, that means the runtime path:
`C1 -> C2 -> C3 -> C4 -> Distributor`

This path should rely on direct, explicit contracts and observable state, not
hidden callbacks, implicit globals, or event side channels.

### 2. The core should speak in ports, not infrastructure

The runtime core should know things like:

- `Feed`
- `Classifier`
- `RulesEngine`
- `HandoffPort`
- `PurgePort`

It should not know FastAPI, websocket plumbing, legacy camera services, or
global mutable process bags.

### 3. Composition roots wire; services coordinate; runtimes own behavior

Each layer has a job:

- **composition roots** build and connect objects;
- **application services / use cases** coordinate named actions;
- **runtimes** own runtime behavior and state;
- **adapters** touch the outside world.

If wiring starts carrying real behavior, it is no longer just wiring.

### 4. Configuration belongs in TOML; persisted state belongs in SQLite

The default rule is simple:

- **configuration** lives in one declarative config source: TOML;
- **persisted state** lives in SQLite;
- **in-flight transient state** lives in explicitly owned runtime objects.

Routers, helpers, and random modules should not quietly invent their own config
stores or hidden state stores.

### 5. Side effects should observe the system, not secretly steer it

Telemetry, UI updates, persistence, uploads, and projections belong in
cross-cutting subscribers and adapters.

They must not quietly become part of the decision path for moving pieces.

### 6. Introspection is a feature, not an afterthought

If we want to debug the machine well, we need structured ways to look inside it.

That means the architecture should deliberately expose:

- runtime state;
- blocked reasons;
- piece / track / record flow;
- status snapshots;
- useful debug projections.

Needing to scrape private fields is a smell that a proper introspection surface
is missing.

### 7. Durable debugging beats one-off archaeology

One-off debug code is fine when we need it.

But when a question is likely to return, we should prefer durable observability:

- structured state snapshots;
- persistent debug records when useful;
- sustainable logging;
- reusable debug endpoints or views.

The goal is to avoid solving the same visibility problem from zero every time.

### 8. Production mode and debug mode may differ, but deliberately

It is acceptable for the system to persist or expose more information in a
debugging mode than in a lean production mode.

But that split should be explicit and designed, not accidental.

### 9. Adapters should be visible, and bridges should shrink over time

Anything touching legacy code, hardware APIs, or external services should be
recognizable as an adapter or bridge.

Temporary code is acceptable.
Invisible temporary code is dangerous.

The desired direction for a bridge is always one of these:

1. isolate it clearly;
2. replace it with a native implementation.

### 10. Every major module should have a one-sentence ownership story

If a file or class needs a paragraph to explain what it owns, it probably owns
too much.

Good examples:

- "This runtime coordinates C3 release behavior."
- "This rules engine maps classification results to bins."
- "This service supervises runtime lifecycle."

### 11. Startup, maintenance, and recovery are real modes

Priming, purge, recovery, and maintenance behavior should be explicit
strategies or services, not hidden branches inside normal steady-state logic.

### 12. Prefer one shared path over many local exceptions

When multiple channels fail in similar ways, prefer a shared fix over another
special case.

The system should become more regular over time, not more locally clever.

### 13. Keep it simple; deduplicate carefully; leave things cleaner

Three supporting rules apply everywhere:

- **KISS**: choose the simplest design that keeps ownership and flow clear.
- **DRY**: deduplicate stable concepts, not accidental similarity.
- **No Decoupling Through Duplication**: extracting logic into a new module or
  service is not enough if the same rules continue to live in multiple places.
  When a refactor reveals shared policy, mapping, normalization, or helper
  logic, that shared logic should move into one clearly owned home.
- **No Abstraction Without Responsibility**: do not introduce wrappers,
  helpers, or classes that only rename another call. An abstraction should
  carry real responsibility such as policy, validation, adaptation, error
  mapping, lifecycle handling, or composition. If it only forwards arguments,
  prefer the direct call.
- **Boy Scout Rule**: leave the area a bit clearer, safer, or more observable
  than you found it.

### 14. Progress beats purity, but direction must stay visible

We do not need to finish the architecture in one pass.
We do need each change to move with the intended direction, not against it.

The point is not perfection.
The point is **consistent convergence**.

## What belongs where

| Concern | Preferred home | Notes |
|--------|-----------------|-------|
| Runtime behavior | runtime core | piece flow, gating, ownership, handoff, local state |
| Named actions | application services / use cases | prepare runtime, start purge, rebuild runner, home hardware |
| Configuration | TOML | single declarative source of truth |
| Persisted state | SQLite | operator state, durable debug data, piece records when persisted |
| In-flight state | owned runtime objects | explicit, local, introspectable |
| External systems | adapters / bridges | hardware, legacy systems, HTTP services |
| HTTP / WS | API transport layer | request parsing, response shaping, transport concerns only |
| Cross-cutting side effects | subscribers / projections | metrics, UI push, uploads, persistent debug projections |

## Anti-patterns to watch for

- **The helpful mega-file**: a router, bootstrap, or helper that slowly absorbs
  behavior, lifecycle, debug logic, and compatibility glue.
- **The hidden system core**: a global module or router that becomes the real
  source of truth.
- **Unnamed callback boundaries**: major subsystems coordinated by convention
  instead of a named port.
- **Router-owned business behavior**: transport code deciding runtime behavior.
- **Decoupling through duplication**: a refactor that improves boundaries on
  paper while leaving the same rules duplicated across router, service, and
  helper layers.
- **Empty semantic wrappers**: helpers or methods that do nothing except rename
  a single underlying call without adding any real ownership or behavior.
- **Leaking bridges**: temporary legacy code spreading across new modules.
- **Steady-state loops carrying startup/maintenance branches**: hidden modes.
- **Private-field archaeology**: status and debug views built by spelunking.

## Fast audit loop

When reviewing a part of the codebase:

1. Pick one hotspot or one responsibility boundary.
2. Ask which principle is being violated.
3. Prefer a central fix over a local patch when the pattern repeats.
4. Keep structural cleanup separate from behavioral change when possible.
5. Verify on the real machine when runtime or hardware behavior is involved.
6. Leave behind better introspection or observability if it helps next time.

## Fast audit questions

- Does this module have one clear ownership sentence?
- Is this logic in the core, or stuck in wiring?
- Is this boundary a named port, or just a callback convention?
- Does this state belong in TOML, SQLite, or a runtime object?
- Is this event really a side effect, or secretly part of the hot path?
- Is this bridge visible and containable?
- Is this router acting as transport, or as subsystem owner?
- Is this startup or maintenance behavior isolated as a real mode?
- Can I inspect what the system is doing without private-field archaeology?
- Did this refactor actually move ownership, or did it duplicate logic?
- Does this abstraction own real behavior, or does it only rename another call?
- Would this structure make the next debugging session easier?

## The intended effect

If this guide is used well, the codebase should gradually move toward:

- clearer ownership;
- more explicit runtime flow;
- stronger boundaries;
- less hidden global behavior;
- better reusable introspection;
- and less repeated debugging from zero.

That is the goal.

## Where to go next

- [Software architecture decisions]({{ '/lab/software-architecture-decisions/' | relative_url }}) - the larger host/firmware split behind the project
- [Sorter architecture]({{ '/sorter/architecture/' | relative_url }}) - the short current architecture overview for contributors
- [Lab index]({{ '/lab/' | relative_url }}) - current contributor references and research areas
