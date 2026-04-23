---
layout: default
title: Sorter Frontend Principles
type: explanation
audience: contributor reference
applies_to: sorter 2.x Svelte 5 / SvelteKit frontend
owner: lab
last_verified: 2026-04-23
section: lab
slug: lab-sorter-frontend-principles
kicker: Lab — Contributor Reference
lede: The active architectural guide for the Sorter frontend: how components, stores, services, and pages divide work in a Svelte 5 / SvelteKit app that already wants to grow mega-components.
permalink: /lab/sorter-frontend-principles/
---

## Why this exists

The Sorter UI has the same drift problem the backend has: useful, long-lived
features slowly absorb fetching, persistence, polling, domain typing, and
flow control until a single `.svelte` file carries an entire subsystem.
`ZoneSection.svelte` is 3762 lines. `setup/+page.svelte` is 1142. Several
feature components manage 30–60 runes and call `fetch()` inline a dozen
times. Every new feature makes the next one harder.

This page is the frontend companion to the
[backend architecture principles]({{ '/lab/sorter-architecture-principles/' | relative_url }}).
Same philosophy, Svelte/TS specifics:

- not a frozen blueprint;
- not a Svelte style guide;
- not an excuse for purity over progress.

It is a set of **leitplanken** for the UI: where fetching, state, flows,
persistence, and composition live so we can keep shipping without the
codebase converging on one mega-component per screen.

## What this is not

- **Not a ban on pragmatism.** Temporary inline fetches are allowed while
  a feature lands. Invisible inline fetches are not.
- **Not a style guide.** Visual language lives in
  [Styleguide]({{ '/lab/styleguide/' | relative_url }}). This is about
  ownership and boundaries.
- **Not a rewrite plan.** We pull one mega-component apart at a time.

## Core Principles

### 1. Pages are composition roots, not workspaces

A route file (`+page.svelte`, `+layout.svelte`) should wire children
together, read route params, and pass props down. It should not own
business state, fetch business data inline, or render 900-line
templates.

If the route carries behavior, that behavior wants a feature component
or a service under `$lib/`.

### 2. Components render state; services own HTTP

All network traffic goes through the typed API layer under `$lib/api/`
(`rest.ts`, `ws.ts`, `events.ts`, `index.ts`) or a feature-scoped
service in `$lib/<feature>/`.

A raw `fetch(` inside a `.svelte` file is a smell. The component should
import a named function: `loadPolygons()`, `savePictureSettings()`,
`registerHiveTarget()`. The service owns URL construction, error
parsing, type coercion, and retries.

### 3. Domain types live in `$lib/`, not in `<script>`

If a type would also make sense in a test, a sibling component, or a
service — extract it. Per-feature domain types live under
`$lib/settings/*.ts`, `$lib/setup/*.ts`, `$lib/dashboard/*.ts`, alongside
their `normalize*`, `clone*`, `*Equal`, and `DEFAULT_*` helpers.

A component's `<script>` should type its props and its local drag/animation
state. Not the business schema.

### 4. Runes stay local; cross-component state is a rune store

`$state`, `$derived`, `$effect` scope naturally to the component that
owns the behavior. When two components need the same state, that state
graduates to a rune store under `$lib/stores/*.svelte.ts` with explicit
`load()`, `save()`, and subscription-friendly getters.

Do not prop-drill mutable state three levels. Do not rebuild the same
`$state` in two siblings. Do not treat parent `$state` as a shared bus
via bindable props unless the binding is truly one-way UI plumbing.

### 5. `$effect` observes; it does not steer

Effects may sync to the DOM, localStorage, the URL, or a derived store.
They must not drive business workflows, fetch-on-mount entire feature
payloads, or orchestrate multi-step tasks.

Fetch-on-mount belongs in `onMount` with a named loader or — better — in
a store method the component calls explicitly. If an effect is long,
conditional, and async, it is probably a workflow in disguise.

### 6. Multi-step flows live in flow services, not in click handlers

A `while (!done) { await fetch; await sleep }` loop inside a button
handler is the UI equivalent of a router owning runtime behavior.
Long-running flows — calibration task polling, bulk downloads, wizard
steps with server round-trips — belong in `$lib/<feature>/*-flow.ts` or
a rune store that exposes a reactive status object.

The component binds to `flow.status`, `flow.progress`, `flow.error`. It
does not implement the state machine itself.

### 7. One scheduler per live resource

If three components poll the same endpoint on their own `setInterval`,
consolidate. A single live-query helper or store owns the interval,
exposes a reactive snapshot, and lets any number of components subscribe.

The WS bus in `$lib/api/ws.ts` is the model: one connection, many
subscribers. Polling should follow the same shape.

### 8. Persistence hides behind a helper

`localStorage.getItem` / `setItem` must not appear in a component. A
per-feature storage helper (`$lib/setup/wizard-storage.ts` is the
template) owns serialization, the SSR `typeof` guard, quota handling,
and the prefix/key convention.

Components import `load*` / `persist*` functions. Changing the storage
schema is then a single-file edit, not a grep sweep.

### 9. Primitives render; feature components compose; pages coordinate

Three layers, like the backend's roots / services / runtimes split:

- **primitives** (`$lib/components/primitives/*`) render — Button, Input,
  Alert, Tooltip. No business knowledge.
- **feature components** (`$lib/components/**`) compose primitives and
  own one feature area (a zone editor, a sidebar, a section card).
- **pages** (`src/routes/**`) coordinate feature components and connect
  them to route params, stores, and services.

A primitive that fetches, a feature component that owns an entire route,
or a page that declares 20 `$state` variables all signal a boundary
collapse.

### 10. Every `.svelte` file has a one-sentence ownership story

If a component needs a paragraph to explain what it owns, it owns too
much. Good examples:

- "Renders one camera feed with its zone overlay."
- "Lets the operator edit arc/polygon zones for a single channel."
- "Wizard step: pick cameras for the configured channels."

`ZoneSection.svelte` currently owns zone geometry, camera picking,
picture-preview toggles, drag state, calibration highlights, detection
highlights, and save/load of polygon payloads. That is a paragraph, not
a sentence.

### 11. Startup, loading, empty, error, recovery are real view modes

Do not paper over half-loaded state with chains of `{#if foo && bar}`
guards. Model the view modes explicitly — `'idle' | 'loading' | 'ok' |
'empty' | 'error'` — and render them as named blocks.

A component whose template starts with six cascading `{#if}` guards is
usually missing a view-mode enum.

### 12. Prefer one shared path over many local exceptions

Duplicated error rendering, duplicated poll loops, duplicated
`normalize*` calls across sibling components are anti-DRY signals. When
a pattern shows up in three components, extract the pattern — not the
data.

This includes cross-cutting UI concerns: notification shape, modal
shell, card frames, table headers, loading skeletons. One shared path
beats ten local clever ones.

### 13. KISS / DRY / no empty wrappers

Three rules, same as the backend:

- **KISS**: choose the simplest component tree that keeps ownership
  clear. Three siblings beat a premature abstraction.
- **DRY**: deduplicate stable concepts (the calibration flow,
  the picture-settings schema), not accidental template similarity.
- **No Abstraction Without Responsibility**: a wrapper component that
  only renames props, a helper that only forwards args, or a store that
  only re-exports a constant is noise. An abstraction should carry
  policy, validation, adaptation, or composition — not just rename.

### 14. Progress beats purity, direction must stay visible

We do not need to split every mega-component in one pass. Each edit to a
large file should make it a little leaner — extract one loader, lift one
type, delete one dead branch. The direction is what matters.

## What belongs where

| Concern | Preferred home | Notes |
|--------|-----------------|-------|
| Rendering a primitive | `$lib/components/primitives/*` | Button, Input, Alert, Tooltip, etc. |
| One feature area | `$lib/components/<area>/*` | zone editor, picture sidebar, hive models list |
| Route composition | `src/routes/**/+page.svelte` | params, store wiring, feature-component layout |
| Domain types + helpers | `$lib/<feature>/*.ts` | `picture-settings.ts`, `camera-choices.ts`, `wizard-types.ts` |
| HTTP calls | `$lib/api/*` or `$lib/<feature>/*-service.ts` | typed, named, error-parsing centralized |
| Multi-step flows | `$lib/<feature>/*-flow.ts` or rune store | status / progress / error as reactive data |
| Cross-component state | `$lib/stores/*.svelte.ts` | rune store with explicit load/save |
| Local UI state | component `<script>` runes | drag, hover, expanded, modal-open |
| Persisted preferences | `$lib/<feature>/*-storage.ts` | serialization + SSR guard + quota |
| WS / live updates | `$lib/api/ws.ts` + store subscribers | one connection, many consumers |

## Anti-patterns to watch for

- **The helpful mega-component**: a `.svelte` file slowly absorbing
  fetching, persistence, drag state, polling, normalizers, and business
  types until only one person can safely change it.
- **Inline fetch archaeology**: `fetch(\`${backendHttpBaseUrl}/api/…\`)`
  scattered across components, each with its own error handling,
  retry, and JSON coercion.
- **`$effect` as workflow engine**: effects that fetch, poll, or drive
  multi-step flows instead of observing state.
- **Click-handler orchestrators**: `while` loops with `await fetch` and
  `await sleep` inside button handlers.
- **Polling sprawl**: ten components each owning their own `setInterval`
  against overlapping endpoints.
- **Storage archaeology**: `localStorage.getItem` littered across the
  tree, each component inventing its own key prefix.
- **Script-block ontologies**: 20+ types declared inside a single
  component `<script>` block — a signal the domain model has no home.
- **Prop-drilled mutable state**: three-level `bind:` chains steering
  shared state instead of a rune store.
- **Empty wrapper components**: a feature component that only renames
  props and re-renders the primitive.
- **Cascading `{#if}` guards**: missing view-mode enum.

## Fast audit loop

When reviewing a part of the UI:

1. Pick one mega-file or one responsibility boundary.
2. Ask which principle is being violated.
3. Prefer extracting into `$lib/<feature>/` over adding another
   inline block.
4. Keep visual tweaks separate from structural extractions.
5. Verify in the browser on the real machine — runtime and hardware
   state matters.
6. Leave the component with a slightly clearer ownership story than
   you found it.

## Fast audit questions

- Does this component have one clear ownership sentence?
- Is this `fetch` inline, or routed through a service?
- Is this state local, or does it deserve a rune store?
- Is this `$effect` observing, or secretly steering a workflow?
- Are these types domain types hiding in a `<script>` block?
- Is this `setInterval` one more local poll, or can it share a scheduler?
- Is this `localStorage` call routed through a helper?
- Is this page a composition root, or is it carrying business logic?
- Are the loading / empty / error states modeled, or just `{#if}`
  chains?
- Would the next contributor find this component easier to split, or
  harder?

## The intended effect

If this guide is used well, the Sorter frontend should gradually move
toward:

- clearer page/component/service boundaries;
- fetching and persistence isolated behind named helpers;
- one scheduler per live resource;
- domain types that live with their helpers, not inside components;
- smaller, single-purpose `.svelte` files;
- less repeated UI plumbing, more shared primitives.

That is the goal.

## Where to go next

- [Sorter architecture principles]({{ '/lab/sorter-architecture-principles/' | relative_url }}) — backend companion to this page
- [Styleguide]({{ '/lab/styleguide/' | relative_url }}) — shared visual language for Sorter and Hive
- [Lab index]({{ '/lab/' | relative_url }}) — all contributor references and research areas
