---
layout: default
title: Sorter architecture
type: explanation
audience: contributor
applies_to: Sorter V2 local software
owner: sorter
slug: sorter-architecture
kicker: Sorter — Under the hood
lede: The current high-level architecture view for contributors. Intentionally short: the durable architectural guidance lives in the lab principles document.
permalink: /sorter/architecture/
---

## The short version

Sorter V2 is two cooperating software layers:

| Layer | Responsibility |
|---|---|
| **Host backend** | runtime flow, hardware coordination, perception, classification, persistence, operator APIs |
| **Frontend UI** | view, controls, operator workflows; no authoritative machine state |

Within the backend, the current architectural direction is:

- a runtime core with explicit piece flow;
- ports and adapters instead of infrastructure-heavy coupling;
- application services for named actions like prepare, purge, rebuild, home;
- declarative configuration in TOML;
- persisted state and durable debug data in SQLite;
- reusable introspection surfaces instead of repeated one-off debug archaeology.

## The active guide

The active architectural guide is:

- [Sorter Architecture Principles]({{ '/lab/sorter-architecture-principles/' | relative_url }})

That document is the place to go for:

- ownership boundaries;
- what belongs where;
- anti-patterns to watch for;
- and the audit questions we use while iterating on the codebase.

## Related references

- [Software architecture decisions]({{ '/lab/software-architecture-decisions/' | relative_url }}) - why the project uses a smart-host / dumb-firmware split
- [Classification research]({{ '/lab/classification-research/' | relative_url }}) - how the classification layer fits into the system
- [C-channel singulation]({{ '/lab/c-channel-singulation/' | relative_url }}) - the mechanical system the backend runtime is driving
