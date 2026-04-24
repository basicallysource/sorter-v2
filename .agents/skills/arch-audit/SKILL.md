---
name: arch-audit
description: Score the Sorter backend against the 14 Sorter Architecture Principles and produce a compact report (overall score, per-principle scores, top ~10 violations with file:line). Use when the user asks for an "arch audit", "architecture audit", "architecture check", "principle scoring", "principle compliance", or wants to measure drift against docs/lab/sorter-architecture-principles/. No refactoring — audit only.
---

# Sorter Architecture Audit

## Goal

Measure how far `software/sorter/backend/**` has drifted from the 14 principles in `docs/lab/sorter-architecture-principles/index.md` and report it compactly: an overall score, a per-principle score line, and the top ~10 most severe violations with file:line references.

The report is short on purpose. It is a dashboard, not an essay. No refactoring, no code changes — audit and report only.

## Scope

- In scope: `software/sorter/backend/**` (Python)
- Out of scope: `**/tests/**`, `**/__pycache__/**`, `**/models/**`, vendored assets, `scripts/`, frontend, hive

## Workflow (target: under ~20 min of tool use)

1. Re-read `docs/lab/sorter-architecture-principles/index.md` — it drifts.
2. Run the signal scan below; treat hits as **leads, not verdicts**.
3. For each suspect, open the file and verify: a grep hit without context is not a violation.
4. Score each principle 0–5 using the rubric.
5. Pick the **top ~10** findings weighted by severity × how hot the path is.
6. Emit the report block verbatim (see "Report format"). Nothing before or after.

## Scoring rubric

| Score | Meaning |
|------:|---------|
| 5 | Principle fully honored; no violations found. |
| 4 | Minor drift, bounded and contained. |
| 3 | Real drift in non-critical areas. |
| 2 | Drift in the hot path, or pattern repeats. |
| 1 | Structural violation — principle is not really in force. |
| 0 | Architecturally inverted — the anti-pattern is the norm. |
| n/a | Principle is directional (e.g. P14) and cannot be point-scored. |

**Overall score** = weighted mean × 20, clamped to 0–100.
Weights: P1, P2, P3, P5, P10 count **×2** (hot-path + ownership). Others ×1. P14 excluded.

## Signal scan (grep leads)

Run these from the repo root. Ignore tests/cache/models. Collect file paths; read the interesting ones before judging.

```bash
B=software/sorter/backend
SKIP='-g !**/tests/** -g !**/__pycache__/** -g !**/models/**'

# P2 — Core speaks infrastructure (FastAPI/ws in runtime, states, classification)
rg -n --type py $SKIP -g "$B/rt/**" -g "$B/states/**" -g "$B/classification/**" \
   'fastapi|starlette|uvicorn|WebSocket|\bwebsocket\b'

# P3 — Router-owned behavior / fat wiring. Largest server modules = candidates.
find $B/server -name '*.py' -exec wc -l {} + 2>/dev/null | sort -nr | head -10

# P3/P10 — Files too large for a one-sentence ownership story
find $B -name '*.py' -not -path '*/tests/*' -not -path '*/__pycache__/*' \
   -exec wc -l {} + | sort -nr | head -15

# P4 — Hidden config/state stores (JSON files, module-level dicts outside the sanctioned stores)
rg -n --type py $SKIP -g "$B/**" 'open\([^)]*\.json|json\.dump|json\.load' \
  | rg -v 'toml_config|machine_params|aruco_config|bin_layout|sorting_profile|polygons|servo_states'

# P5 — Subscribers that steer runtime instead of observing it
rg -n --type py $SKIP -g "$B/**" -C1 'subscribe|on_event|emit\(|publish\(' \
  | rg -i 'runtime|gate|release|purge|handoff|state\.'

# P6 — Private-field archaeology (many `._name` reads from outside)
rg -n --type py $SKIP -g "$B/**" -o '\b[a-z_]+\._[a-z_]+' | sort | uniq -c | sort -nr | head -15

# P9 — Visible bridges / legacy markers
rg -n --type py $SKIP -g "$B/**" -i '\b(legacy|compat|shim|bridge|HACK|XXX|FIXME|TODO[: ])' | head -40

# P11 — Startup/maintenance branches hidden inside steady-state loops
rg -n --type py $SKIP -g "$B/**" -C1 '\b(if|elif)\b.*(priming|recover|startup|maintenance|warmup)'

# P13 — Empty pass-through wrappers (method bodies that only `return self._x...`)
rg -nU --type py $SKIP -g "$B/**" 'def [a-z_]+\([^)]*\):\s*\n\s*return self\._[a-z_]+' | head

# P1 — Callback-convention coordination instead of named ports
rg -n --type py $SKIP -g "$B/rt/**" -g "$B/states/**" \
   'callback|_cb\b|on_[a-z_]+\s*=|\.register\('
```

Prefer reading 3–5 of the top offenders over skimming 50 hits. The report cites **lines you actually verified**.

## Report format (emit exactly this; nothing else)

```
# Sorter Architecture Audit — <YYYY-MM-DD>

**Overall score: <0–100> / 100**

## Per-principle scores

| # | Principle | Score |
|---|-----------|------:|
| 1 | Hot path explicit | x/5 |
| 2 | Core speaks ports | x/5 |
| 3 | Roots wire, services coordinate | x/5 |
| 4 | TOML for config, SQLite for state | x/5 |
| 5 | Side effects observe, not steer | x/5 |
| 6 | Introspection as a feature | x/5 |
| 7 | Durable debugging | x/5 |
| 8 | Deliberate prod/debug split | x/5 |
| 9 | Adapters visible, bridges shrink | x/5 |
| 10 | One-sentence ownership | x/5 |
| 11 | Startup/maintenance as real modes | x/5 |
| 12 | One shared path | x/5 |
| 13 | KISS / DRY / no empty wrappers | x/5 |
| 14 | Progress over purity | n/a |

## Top violations

| # | P | Where | What | Severity |
|---|---|-------|------|----------|
| 1 | P? | `path/to/file.py:LL` | one-line description | high/med/low |
| 2 | ... | ... | ... | ... |

## Highest-leverage next step

<one sentence — the single change that would move the score the most>
```

No preamble, no conclusion, no apologies about scope. If the user asks for depth after seeing the report, expand **then**.

## Guardrails

- Do not edit code. This skill only reads and reports.
- Do not invent findings to fill slots. If there are fewer than 10 real violations, list fewer.
- Prefer a severe finding on a hot-path file over a cosmetic finding on a cold one.
- Cite line numbers for every Top-10 entry. If you can't, it doesn't belong in the Top-10.
- If a principle legitimately scores 5, say so — clean areas are signal too.
